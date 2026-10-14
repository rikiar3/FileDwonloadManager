import json
import os
import re
import threading
import time
from tkinter import filedialog, messagebox, TclError
from urllib.parse import unquote, urlparse

import customtkinter as ctk
import requests


ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class DownloadRateLimiter:
    def __init__(self, bytes_per_second):
        self._lock = threading.Lock()
        self._bytes_per_second = bytes_per_second
        self._capacity = max(64 * 1024, bytes_per_second * 0.25)
        self._tokens = self._capacity
        self._updated_at = time.monotonic()

    def set_limit(self, bytes_per_second):
        with self._lock:
            self._refill()
            self._bytes_per_second = bytes_per_second
            self._capacity = max(64 * 1024, bytes_per_second * 0.25)
            self._tokens = min(self._tokens, self._capacity)

    def _refill(self):
        now = time.monotonic()
        if self._bytes_per_second > 0:
            self._tokens = min(
                self._capacity,
                self._tokens + (now - self._updated_at) * self._bytes_per_second,
            )
        else:
            self._tokens = self._capacity
        self._updated_at = now

    def consume(self, byte_count, cancel_event):
        while not cancel_event.is_set():
            with self._lock:
                self._refill()
                if self._bytes_per_second <= 0:
                    return True
                if self._tokens >= byte_count:
                    self._tokens -= byte_count
                    return True
                wait_time = (byte_count - self._tokens) / self._bytes_per_second
            cancel_event.wait(min(wait_time, 0.1))
        return False


class RikiDownloaderBackend:
    def __init__(
        self, url, save_path, num_threads, progress_callback, finish_callback, rate_limiter=None
    ):
        self.url = url
        self.save_path = save_path
        self.num_threads = num_threads
        self.progress_callback = progress_callback
        self.finish_callback = finish_callback
        self.rate_limiter = rate_limiter or DownloadRateLimiter(0)
        self.file_size = 0
        self.total_downloaded = 0
        self.pause_requested = threading.Event()
        self._download_lock = threading.Lock()

    def pause(self):
        self.pause_requested.set()

    def _probe_server(self):
        headers = {"Range": "bytes=0-0", "Accept-Encoding": "identity"}
        with requests.get(self.url, headers=headers, stream=True, timeout=25) as response:
            if response.status_code == 206:
                content_range = response.headers.get("Content-Range", "")
                match = re.fullmatch(r"bytes\s+0-0/(\d+)", content_range)
                if match:
                    return int(match.group(1)), True
                return 0, False

            response.raise_for_status()
            if response.status_code != 200:
                raise requests.RequestException(
                    f"Server mengembalikan status HTTP {response.status_code}."
                )
            return int(response.headers.get("Content-Length", 0)), False

    def _download_part(self, start, end, part_id, errors):
        part_path = f"{self.save_path}.part{part_id}"
        try:
            expected_size = end - start + 1
            initial_size = os.path.getsize(part_path) if os.path.exists(part_path) else 0
            if initial_size > expected_size:
                raise IOError(f"Ukuran bagian unduhan {part_id + 1} melebihi batas.")
            if initial_size == expected_size:
                return

            headers = {
                "Range": f"bytes={start + initial_size}-{end}",
                "Accept-Encoding": "identity",
            }
            with requests.get(self.url, headers=headers, stream=True, timeout=25) as response:
                if response.status_code != 206:
                    response.raise_for_status()
                    raise requests.RequestException(
                        "Server tidak mendukung unduhan bersegmen."
                    )
                content_range = response.headers.get("Content-Range", "")
                match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+)", content_range)
                if (
                    not match
                    or int(match.group(1)) != start + initial_size
                    or int(match.group(2)) != end
                    or int(match.group(3)) != self.file_size
                ):
                    raise requests.RequestException(
                        "Server mengirim rentang byte yang tidak sesuai."
                    )
                with open(part_path, "ab") as part_file:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if self.pause_requested.is_set():
                            return
                        if chunk:
                            if not self.rate_limiter.consume(len(chunk), self.pause_requested):
                                return
                            part_file.write(chunk)
                            with self._download_lock:
                                self.total_downloaded += len(chunk)
        except requests.RequestException as exc:
            if not self.pause_requested.is_set():
                errors.append(exc)
        except OSError as exc:
            if not self.pause_requested.is_set():
                errors.append(exc)

    def _download_single(self, supports_ranges):
        part_path = f"{self.save_path}.part0"
        offset = os.path.getsize(part_path) if os.path.exists(part_path) else 0
        if self.file_size and offset > self.file_size:
            raise OSError("Ukuran file sementara melebihi ukuran file di server.")
        if self.file_size and offset == self.file_size:
            self.total_downloaded = offset
            return

        headers = {"Accept-Encoding": "identity"}
        if supports_ranges:
            headers["Range"] = f"bytes={offset}-"

        try:
            with requests.get(self.url, headers=headers, stream=True, timeout=25) as response:
                if supports_ranges and response.status_code == 200:
                    offset = 0
                else:
                    response.raise_for_status()
                    if response.status_code != (206 if supports_ranges else 200):
                        raise requests.RequestException(
                            f"Server mengembalikan status HTTP {response.status_code}."
                        )
                    if supports_ranges:
                        content_range = response.headers.get("Content-Range", "")
                        match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+)", content_range)
                        if (
                            not match
                            or int(match.group(1)) != offset
                            or int(match.group(2)) != self.file_size - 1
                            or int(match.group(3)) != self.file_size
                        ):
                            raise requests.RequestException(
                                "Server melanjutkan unduhan dari rentang byte yang tidak sesuai."
                            )

                mode = "ab" if offset else "wb"
                self.total_downloaded = offset
                bytes_to_skip = offset if not supports_ranges else 0
                previous_bytes = offset
                previous_time = time.monotonic()
                last_report = previous_time
                with open(part_path, mode) as part_file:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if self.pause_requested.is_set():
                            return
                        if chunk:
                            if bytes_to_skip:
                                skipped = min(bytes_to_skip, len(chunk))
                                bytes_to_skip -= skipped
                                chunk = chunk[skipped:]
                            if not chunk:
                                continue
                            if not self.rate_limiter.consume(len(chunk), self.pause_requested):
                                return
                            part_file.write(chunk)
                            with self._download_lock:
                                self.total_downloaded += len(chunk)
                                downloaded = self.total_downloaded
                            now = time.monotonic()
                            if now - last_report >= 0.5:
                                elapsed = now - previous_time
                                speed = (downloaded - previous_bytes) / elapsed if elapsed else 0
                                eta = (
                                    max(0, self.file_size - downloaded) / speed
                                    if self.file_size and speed > 0
                                    else None
                                )
                                pct = min(downloaded / self.file_size, 1) if self.file_size else 0
                                self.progress_callback(pct, speed, eta)
                                previous_bytes = downloaded
                                previous_time = now
                                last_report = now
                    if bytes_to_skip:
                        raise OSError("Server mengirim file lebih pendek dari data sementara.")
        except requests.RequestException:
            if self.pause_requested.is_set():
                return
            raise

    def start(self):
        try:
            self.file_size, supports_ranges = self._probe_server()
            self.total_downloaded = 0

            if self.num_threads <= 1 or not supports_ranges or self.file_size <= 0:
                self._download_single(supports_ranges)
            else:
                workers = []
                errors = []
                for part_id in range(self.num_threads):
                    start = self.file_size * part_id // self.num_threads
                    end = self.file_size * (part_id + 1) // self.num_threads - 1
                    if start > end:
                        continue
                    part_path = f"{self.save_path}.part{part_id}"
                    if os.path.exists(part_path):
                        self.total_downloaded += os.path.getsize(part_path)
                    worker = threading.Thread(
                        target=self._download_part,
                        args=(start, end, part_id, errors),
                    )
                    workers.append(worker)
                    worker.start()

                started = time.monotonic()
                previous_bytes = self.total_downloaded
                previous_time = started
                while any(worker.is_alive() for worker in workers):
                    time.sleep(0.5)
                    with self._download_lock:
                        downloaded = self.total_downloaded
                    now = time.monotonic()
                    elapsed = now - previous_time
                    speed = (downloaded - previous_bytes) / elapsed if elapsed else 0
                    remaining = max(0, self.file_size - downloaded)
                    eta = remaining / speed if speed > 0 else None
                    self.progress_callback(
                        min(downloaded / self.file_size, 1), speed, eta
                    )
                    previous_bytes = downloaded
                    previous_time = now

                for worker in workers:
                    worker.join()
                if errors:
                    raise errors[0]

            if self.pause_requested.is_set():
                self.finish_callback("Dijeda")
                return

            if self.file_size and self.total_downloaded != self.file_size:
                raise IOError("Unduhan belum lengkap; file sementara tetap disimpan.")
            self._merge_parts()
            self.progress_callback(1.0, 0, 0)
            self.finish_callback("Selesai")
        except (requests.RequestException, OSError, ValueError) as exc:
            self.finish_callback(f"Gagal: {exc}")

    def _merge_parts(self):
        assembling_path = f"{self.save_path}.assembling"
        with open(assembling_path, "wb") as final_file:
            for part_id in range(self.num_threads):
                part_path = f"{self.save_path}.part{part_id}"
                if not os.path.exists(part_path):
                    continue
                with open(part_path, "rb") as part_file:
                    while True:
                        block = part_file.read(1024 * 1024)
                        if not block:
                            break
                        final_file.write(block)
        os.replace(assembling_path, self.save_path)
        for part_id in range(self.num_threads):
            part_path = f"{self.save_path}.part{part_id}"
            if os.path.exists(part_path):
                os.remove(part_path)


class RikiDownloadManager(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Riki Multi-Download Manager v4.1")
        self.geometry("900x650")

        appdata_path = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "RikiDownloader")
        os.makedirs(appdata_path, exist_ok=True)

        self.history_file = os.path.join(appdata_path, "history.json")
        self.default_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        self.downloads = self.load_history()
        self.row_widgets = {}
        self.active_backends = {}
        self.last_clipboard_text = None
        self.last_auto_filled_url = None
        self.speed_limit_options = {
            "256 KB/s": 256 * 1024,
            "512 KB/s": 512 * 1024,
            "1 MB/s": 1024 * 1024,
            "2 MB/s": 2 * 1024 * 1024,
            "5 MB/s": 5 * 1024 * 1024,
            "Kecepatan penuh": 0,
        }
        self.rate_limiter = DownloadRateLimiter(self.speed_limit_options["1 MB/s"])

        self.setup_ui()
        self.refresh_history_ui()
        self.check_clipboard()

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self,
            text="RIKI MULTI-DOWNLOAD MANAGER",
            font=("Segoe UI", 28, "bold"),
            text_color="#3498db",
        ).pack(pady=20)

        frame_in = ctk.CTkFrame(self)
        frame_in.pack(padx=20, fill="x")
        self.entry_url = ctk.CTkEntry(
            frame_in, placeholder_text="Paste URL di sini...", height=45, font=("Arial", 14)
        )
        self.entry_url.pack(padx=10, pady=15, fill="x")

        options = ctk.CTkFrame(self, fg_color="transparent")
        options.pack(pady=(10, 0))
        ctk.CTkLabel(options, text="Jumlah bagian:").pack(side="left", padx=(0, 8))
        self.segment_count = ctk.StringVar(value="8")
        ctk.CTkOptionMenu(
            options,
            variable=self.segment_count,
            values=["1", "2", "4", "8", "16"],
            width=90,
        ).pack(side="left")
        ctk.CTkLabel(options, text="Batas kecepatan:").pack(side="left", padx=(18, 8))
        self.speed_limit = ctk.StringVar(value="1 MB/s")
        ctk.CTkOptionMenu(
            options,
            variable=self.speed_limit,
            values=list(self.speed_limit_options),
            width=150,
            command=self.set_speed_limit,
        ).pack(side="left")

        self.btn_add = ctk.CTkButton(
            self,
            text="+ TAMBAH & MULAI DOWNLOAD",
            font=("Arial", 16, "bold"),
            fg_color="#2ecc71",
            hover_color="#27ae60",
            height=50,
            command=self.start_new_download,
        )
        self.btn_add.pack(pady=10)

        self.history_frame = ctk.CTkScrollableFrame(self, height=400, fg_color="#1e1e1e")
        self.history_frame.pack(padx=20, pady=10, fill="both", expand=True)

    def load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as history_file:
                    return json.load(history_file)
            except (OSError, json.JSONDecodeError):
                return {}
        return {}

    def save_history(self):
        with open(self.history_file, "w", encoding="utf-8") as history_file:
            json.dump(self.downloads, history_file)

    def set_speed_limit(self, choice):
        self.rate_limiter.set_limit(self.speed_limit_options[choice])

    def check_clipboard(self):
        try:
            clipboard_text = self.clipboard_get().strip()
        except TclError:
            clipboard_text = ""

        if clipboard_text != self.last_clipboard_text:
            self.last_clipboard_text = clipboard_text
            parsed_url = urlparse(clipboard_text)
            if (
                parsed_url.scheme in ("http", "https")
                and parsed_url.netloc
                and self.entry_url.get().strip() in ("", self.last_auto_filled_url)
            ):
                self.entry_url.delete(0, "end")
                self.entry_url.insert(0, clipboard_text)
                self.last_auto_filled_url = clipboard_text
        self.after(700, self.check_clipboard)

    def refresh_history_ui(self):
        for widget in self.history_frame.winfo_children():
            widget.destroy()
        self.row_widgets = {}
        for url, data in list(self.downloads.items())[::-1]:
            self.create_download_row(url, data)

    @staticmethod
    def _short_name(name):
        return f"{name[:20]}..." if len(name) > 20 else name

    def create_download_row(self, url, data):
        frame = ctk.CTkFrame(self.history_frame, fg_color="#2b2b2b")
        frame.pack(fill="x", pady=5, padx=5)

        name = os.path.basename(data["path"])
        ctk.CTkLabel(
            frame,
            text=self._short_name(name),
            width=190,
            anchor="w",
            font=("Arial", 12, "bold"),
        ).grid(row=0, column=0, padx=15, pady=15)

        progress = ctk.CTkProgressBar(frame, width=190, height=12)
        progress.set(1.0 if data["status"] == "Selesai" else 0)
        progress.grid(row=0, column=1, padx=10)

        info = ctk.CTkLabel(
            frame,
            text=data["status"],
            width=250,
            font=("Consolas", 12, "bold"),
            text_color="#2ecc71",
        )
        info.grid(row=0, column=2, padx=10)

        button_text = "Buka" if data["status"] == "Selesai" else "Lanjutkan"
        button = ctk.CTkButton(frame, text=button_text, width=90, height=32)
        button.configure(command=lambda download_url=url: self.handle_action(download_url))
        button.grid(row=0, column=3, padx=15)

        self.row_widgets[url] = {"p_bar": progress, "lbl_info": info, "btn": button}

    def handle_action(self, url):
        data = self.downloads.get(url)
        if not data:
            return
        if data["status"] == "Selesai":
            folder = os.path.dirname(data["path"])
            if os.path.exists(folder):
                os.startfile(folder)
            return

        backend = self.active_backends.get(url)
        if backend:
            backend.pause()
            self.row_widgets[url]["btn"].configure(state="disabled", text="Menjeda...")
            return

        self.row_widgets[url]["btn"].configure(state="disabled", text="Memulai...")
        num_threads = int(data.get("segments", 8))
        threading.Thread(
            target=self.worker,
            args=(url, data["path"], num_threads),
            daemon=True,
        ).start()

    def start_new_download(self):
        url = self.entry_url.get().strip()
        if not url:
            messagebox.showwarning("Peringatan", "Silakan masukkan URL terlebih dahulu!")
            return
        parsed_url = urlparse(url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            messagebox.showwarning("Peringatan", "URL harus diawali dengan http:// atau https://.")
            return

        original_filename = unquote(os.path.basename(parsed_url.path)) or "file_download"
        path = filedialog.asksaveasfilename(
            initialdir=self.default_dir,
            initialfile=original_filename,
            title="Simpan File Sebagai...",
            defaultextension=".*",
            filetypes=[("All Files", "*.*")],
        )

        if path:
            self.downloads[url] = {
                "path": path,
                "status": "Menunggu",
                "segments": int(self.segment_count.get()),
            }
            self.save_history()
            self.create_download_row(url, self.downloads[url])
            self.entry_url.delete(0, "end")
            self.handle_action(url)
        self.focus_force()

    def _set_progress(self, url, pct, speed, eta):
        widgets = self.row_widgets.get(url)
        if not widgets:
            return
        widgets["p_bar"].set(pct)
        speed_mb = speed / (1024 * 1024)
        if eta is None:
            eta_text = "Sisa --:--"
        else:
            eta_seconds = max(0, int(eta))
            minutes, seconds = divmod(eta_seconds, 60)
            hours, minutes = divmod(minutes, 60)
            eta_text = f"Sisa {hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"Sisa {minutes:02d}:{seconds:02d}"
        widgets["lbl_info"].configure(
            text=f"{speed_mb:.2f} MB/s | {int(pct * 100)}% | {eta_text}"
        )
        self.downloads[url]["status"] = "Running"

    def _mark_running(self, url):
        self.downloads[url]["status"] = "Running"
        self.save_history()
        widgets = self.row_widgets.get(url)
        if widgets:
            widgets["btn"].configure(state="normal", text="Jeda", fg_color="#c0392b")
            widgets["lbl_info"].configure(text="Mengunduh...", text_color="#2ecc71")

    def _finish_download(self, url, status):
        self.active_backends.pop(url, None)
        data = self.downloads[url]
        data["status"] = status
        self.save_history()

        widgets = self.row_widgets.get(url)
        if not widgets:
            return
        widgets["btn"].configure(state="normal")
        if status == "Selesai":
            widgets["p_bar"].set(1.0)
            widgets["lbl_info"].configure(text="SELESAI")
            widgets["btn"].configure(text="Buka", fg_color="#3498db")
        elif status == "Dijeda":
            widgets["btn"].configure(text="Lanjutkan", fg_color="#1f6aa5")
            widgets["lbl_info"].configure(text="Dijeda")
        else:
            widgets["btn"].configure(text="Coba Lagi", fg_color="#1f6aa5")
            widgets["lbl_info"].configure(text=status, text_color="#e74c3c")

    def worker(self, url, path, num_threads):
        def update_progress(pct, speed, eta):
            self.after(0, lambda: self._set_progress(url, pct, speed, eta))

        def finish(status):
            self.after(0, lambda: self._finish_download(url, status))

        backend = RikiDownloaderBackend(
            url, path, num_threads, update_progress, finish, self.rate_limiter
        )
        self.active_backends[url] = backend
        self.after(0, lambda: self._mark_running(url))
        backend.start()


if __name__ == "__main__":
    app = RikiDownloadManager()
    app.mainloop()
