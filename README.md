# 🚀 Riki Multi-Download Manager (v4.1)

A modern, fast, and lightweight multi-threaded download manager built with **Python** and **CustomTkinter**. Designed to handle multiple downloads simultaneously with an intuitive UI.

## ✨ Features
* **Configurable Segments**: Download supported files in 1, 2, 4, 8, or 16 chunks.
* **Parallel Downloads**: Handle multiple file downloads at the same time without interference.
* **Persistent History**: Your download list is safely stored in `%APPDATA%`, so it stays even if you move the app.
* **Modern UI**: Built with a dark-themed, responsive interface using `CustomTkinter`.
* **Pause and Resume**: Continue from saved chunks; servers without byte-range support may require re-downloading the saved prefix.
* **Download Speed Limit**: Cap the combined speed of all active downloads, with presets from 256 KB/s to 5 MB/s or an unlimited full-speed option. The default limit is 1 MB/s.
* **Automatic URL Detection**: An HTTP or HTTPS link copied to the clipboard is filled into the URL field automatically.
* **Real-time Stats**: View download speed, progress, and estimated remaining time.
* **Compact File Names**: Long names are shortened in the download list to keep the interface tidy.

## 🛠️ Tech Stack
* **Language**: Python 3.13
* **GUI**: CustomTkinter (Modern Tkinter)
* **Networking**: Requests library
* **Concurrency**: Threading module
* **Data Persistence**: JSON-based storage in System AppData

## 🚀 How to Run (Development)
1. Clone this repository:
   ```bash
   git clone [https://github.com/username/riki-download-manager.git](https://github.com/username/riki-download-manager.git)

Install dependencies:

Bash
pip install customtkinter requests
Run the application:

Bash
python filedownloadmanager.py
📦 How to Build EXE
To create a standalone executable, use PyInstaller:

pyinstaller --noconfirm --onefile --windowed --add-data "C:/Path/To/customtkinter;customtkinter/" filedownloadmanager.py