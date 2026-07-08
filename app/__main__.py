"""One-click launcher: `python -m app` starts the server and opens the browser.

Kept minimal — no CLI flags. For development use `uvicorn app.main:app --reload`.
"""

from __future__ import annotations

import threading
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8000


def _open_browser() -> None:
    webbrowser.open(f"http://{HOST}:{PORT}/")


if __name__ == "__main__":
    threading.Timer(1.5, _open_browser).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT)
