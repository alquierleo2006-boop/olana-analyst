import os
import subprocess
import sys
from pathlib import Path


def test_tech_edition_in_separate_process():
    env = dict(os.environ, ANALYST_EDITION="tech")
    root = Path(__file__).resolve().parents[1]
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-W", "ignore", "tests/test_tech_edition.py"],
                       cwd=root, env=env, capture_output=True, text=True, timeout=1200)
    assert p.returncode == 0 and "6 passed" in p.stdout, p.stdout[-3000:] + p.stderr[-2000:]
