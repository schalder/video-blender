"""Desktop entrypoint: start local server and open Video Blender in the browser."""

from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Ensure project root is importable when running from source
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _wait_health(url: str, seconds: float = 20.0) -> bool:
    import urllib.request

    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as res:
                if res.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    return False


def main() -> int:
    port = 8765
    if not _port_free(port):
        # Already running — just open UI
        webbrowser.open(f"http://127.0.0.1:{port}")
        return 0

    from backend.main import app
    import uvicorn

    url = f"http://127.0.0.1:{port}"

    def open_when_ready() -> None:
        if _wait_health(f"{url}/api/health"):
            webbrowser.open(url)

    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
