# 🚀 Riki Multi-Download Manager (v4.1)

A modern, fast, and lightweight multi-threaded download manager built with **Python** and **CustomTkinter**. Designed to handle multiple downloads simultaneously with an intuitive UI.

## ✨ Features
* **Multi-Threading Power**: Download files in 8 simultaneous chunks for maximum speed.
* **Parallel Downloads**: Handle multiple file downloads at the same time without interference.
* **Persistent History**: Your download list is safely stored in `%APPDATA%`, so it stays even if you move the app.
* **Modern UI**: Built with a dark-themed, responsive interface using `CustomTkinter`.
* **Resume Capability**: Stop and resume downloads anytime.
* **Real-time Stats**: Big, clear labels for download speed (MB/s) and progress percentage.

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