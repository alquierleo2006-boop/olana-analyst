"""Lancement : python -m analyst  (écoute uniquement sur 127.0.0.1)."""
import os

import uvicorn

from .app import create_app


def main() -> None:
    port = int(os.environ.get("ANALYST_PORT", "8765"))
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level=os.environ.get("ANALYST_LOG", "warning"))


if __name__ == "__main__":
    main()
