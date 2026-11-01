"""Serveur de démonstration branché sur le faux réseau (pour tester l'interface sans Internet).
Usage : python -m tests.demo_server   puis ouvrir http://localhost:1420/?backend=http://127.0.0.1:8765"""
import os
import tempfile

import uvicorn

os.environ.pop("ANALYST_TOKEN", None)
from analyst.app import create_app  # noqa: E402

from .fakes import Fake  # noqa: E402

if __name__ == "__main__":
    db = os.path.join(tempfile.mkdtemp(), "demo.sqlite3")
    import math
    walk = [32 + 6 * math.sin(i / 6) + i * 0.15 for i in range(2000)]  # courbe de démo qui monte et redescend
    uvicorn.run(create_app(transport=Fake(curve_seq=walk).transport(), db_path=db), host="127.0.0.1", port=8765, log_level="warning")
