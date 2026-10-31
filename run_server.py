"""Start INTRINSIC:  python run_server.py

Opens http://127.0.0.1:8000 in your browser. Press Ctrl+C to stop.
"""
import os
import sys
import threading
import webbrowser

import uvicorn

HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

if sys.platform == "win32":  # make the console show symbols correctly on Windows
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def open_browser():
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    print("=" * 64)
    print(" INTRINSIC - Subscription & Invoicing Management")
    print(f" App:      http://{HOST}:{PORT}")
    print(f" API docs: http://{HOST}:{PORT}/docs")
    print(" Demo sign-in: admin@intrinsic.io / Intrinsic@2026")
    print(" Press Ctrl+C to stop.")
    print("=" * 64)
    if os.getenv("NO_BROWSER") != "1":
        threading.Timer(1.5, open_browser).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT)
