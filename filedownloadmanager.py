import customtkinter as ctk
import requests
import threading
import os
import time
import json
from tkinter import filedialog, messagebox

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class RikiDownloaderBackend:
    def __init__(self, url, save_path, num_threads, progress_callback):
        self.url = url
        self.save_path = save_path
        self.num_threads = num_threads
        self.progress_callback = progress_callback
        self.file_size = 0
        self.total_downloaded = 0
        self.is_running = True

    def download_part(self, start, end, part_id):
        part_name = f"{self.save_path}.part{part_id}"
        initial_pos = os.path.getsize(part_name) if os.path.exists(part_name) else 0
        if initial_pos >= (end - start + 1): return

        headers = {'Range': f'bytes={start + initial_pos}-{end}'}
        try:
            with requests.get(self.url, headers=headers, stream=True, timeout=25) as r:
                r.raise_for_status()
                with open(part_name, "ab") as f:
                    for chunk in r.iter_content(chunk_size=1024*64):
                        if not self.is_running: return
                        if chunk:
                            f.write(chunk)
                            with threading.Lock(): self.total_downloaded += len(chunk)
        except: pass

    def start(self):
        try:
            head = requests.head(self.url, allow_redirects=True, timeout=10)
            self.file_size = int(head.headers.get('content-length', 0))
            chunk_size = self.file_size // self.num_threads if self.file_size > 0 else 0
            
            self.total_downloaded = 0
            for i in range(self.num_threads):
                p = f"{self.save_path}.part{i}"
                if os.path.exists(p): self.total_downloaded += os.path.getsize(p)

            start_time = time.time()
            threads = []
            for i in range(self.num_threads):
                start = i * chunk_size
                end = self.file_size - 1 if i == self.num_threads - 1 else (i + 1) * chunk_size - 1
                t = threading.Thread(target=self.download_part, args=(start, end, i))
                threads.append(t)
                t.start()

            while any(t.is_alive() for t in threads) and self.is_running:
                time.sleep(0.5)
                if self.file_size > 0:
                    pct = self.total_downloaded / self.file_size
                    elapsed = time.time() - start_time
                    spd = (self.total_downloaded / elapsed) / (1024 * 1024) if elapsed > 0 else 0
                    self.progress_callback(pct, spd)

            if self.is_running and self.file_size > 0:
                self.merge()
                self.progress_callback(1.0, 0)
        except: pass

    def merge(self):
        try:
            with open(self.save_path, "wb") as final:
                for i in range(self.num_threads):
                    p = f"{self.save_path}.part{i}"
                    if os.path.exists(p):
                        with open(p, "rb") as pf: final.write(pf.read())
                        os.remove(p)
        except: pass

class RikiDownloadManager(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Riki Multi-Download Manager v4.1")
        self.geometry("900x650")
        
        # Lokasi penyimpanan histori di folder sistem APPDATA
        appdata_path = os.path.join(os.environ.get('APPDATA'), 'RikiDownloader')
        if not os.path.exists(appdata_path):
            os.makedirs(appdata_path)
            
        self.history_file = os.path.join(appdata_path, 'history.json')
        self.default_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
        self.downloads = self.load_history()
        self.row_widgets = {}
        self.active_backends = {}

        self.setup_ui()
        self.refresh_history_ui()

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text="RIKI MULTI-DOWNLOAD MANAGER", font=("Segoe UI", 28, "bold"), text_color="#3498db").pack(pady=20)

        frame_in = ctk.CTkFrame(self)
        frame_in.pack(padx=20, fill="x")
        self.entry_url = ctk.CTkEntry(frame_in, placeholder_text="Paste URL di sini...", height=45, font=("Arial", 14))
        self.entry_url.pack(padx=10, pady=15, fill="x")

        self.btn_add = ctk.CTkButton(self, text="+ TAMBAH & MULAI DOWNLOAD", font=("Arial", 16, "bold"), fg_color="#2ecc71", hover_color="#27ae60", height=50, command=self.start_new_download)
        self.btn_add.pack(pady=10)

        self.history_frame = ctk.CTkScrollableFrame(self, height=400, fg_color="#1e1e1e")
        self.history_frame.pack(padx=20, pady=10, fill="both", expand=True)

    def load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f: return json.load(f)
            except: return {}
        return {}

    def save_history(self):
        with open(self.history_file, 'w') as f: json.dump(self.downloads, f)

    def refresh_history_ui(self):
        for w in self.history_frame.winfo_children(): w.destroy()
        self.row_widgets = {}
        for url, data in list(self.downloads.items())[::-1]:
            self.create_download_row(url, data)

    def create_download_row(self, url, data):
        f = ctk.CTkFrame(self.history_frame, fg_color="#2b2b2b")
        f.pack(fill="x", pady=5, padx=5)
        
        name = os.path.basename(data['path'])
        ctk.CTkLabel(f, text=name, width=200, anchor="w", font=("Arial", 12, "bold")).grid(row=0, column=0, padx=15, pady=15)

        p_bar = ctk.CTkProgressBar(f, width=220, height=12)
        p_bar.set(1.0 if data['status'] == 'Selesai' else 0)
        p_bar.grid(row=0, column=1, padx=10)

        lbl_info = ctk.CTkLabel(f, text=data['status'], width=180, font=("Consolas", 14, "bold"), text_color="#2ecc71")
        lbl_info.grid(row=0, column=2, padx=10)

        btn = ctk.CTkButton(f, text="Buka" if data['status'] == 'Selesai' else "Mulai", width=100, height=32, font=("Arial", 12, "bold"))
        btn.configure(command=lambda u=url: self.handle_action(u))
        btn.grid(row=0, column=3, padx=15)

        self.row_widgets[url] = {"p_bar": p_bar, "lbl_info": lbl_info, "btn": btn}

    def handle_action(self, url):
        data = self.downloads.get(url)
        if not data: return
        if data['status'] == 'Selesai':
            folder = os.path.dirname(data['path'])
            if os.path.exists(folder): os.startfile(folder)
        else:
            if url in self.active_backends: return
            self.row_widgets[url]["btn"].configure(state="disabled", text="Running")
            threading.Thread(target=self.worker, args=(url, data['path']), daemon=True).start()

    def start_new_download(self):
        url = self.entry_url.get().strip()
        if not url:
            messagebox.showwarning("Peringatan", "Silakan masukkan URL terlebih dahulu!")
            return
        
        original_filename = url.split('/')[-1].split('?')[0] or "file_download"
        path = filedialog.asksaveasfilename(
            initialdir=self.default_dir,
            initialfile=original_filename,
            title="Simpan File Sebagai...",
            defaultextension=".*", 
            filetypes=[("All Files", "*.*")]
        )
        
        if path:
            self.downloads[url] = {'path': path, 'status': 'Running'}
            self.save_history()
            self.create_download_row(url, self.downloads[url])
            self.entry_url.delete(0, 'end')
            self.handle_action(url)
        self.focus_force()

    def worker(self, url, path):
        def update_row(pct, spd):
            if url in self.row_widgets:
                try:
                    if self.row_widgets[url]["p_bar"].winfo_exists():
                        self.row_widgets[url]["p_bar"].set(pct)
                        status_text = f"{spd:.2f} MB/s | {int(pct*100)}%" if pct < 1 else "SELESAI"
                        self.row_widgets[url]["lbl_info"].configure(text=status_text)
                        if pct >= 1:
                            self.row_widgets[url]["btn"].configure(state="normal", text="Buka", fg_color="#3498db")
                            self.downloads[url]['status'] = 'Selesai'
                            self.save_history()
                            if url in self.active_backends: del self.active_backends[url]
                except: pass

        backend = RikiDownloaderBackend(url, path, 8, update_row)
        self.active_backends[url] = backend
        backend.start()

if __name__ == "__main__":
    app = RikiDownloadManager()
    app.mainloop()