"""Petits utilitaires partagés : horodatage, points de données sourcés, validation d'adresse."""
from __future__ import annotations

import re
import time
from typing import Any

BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

# Statuts d'une donnée — jamais « vérifié » si la vérification n'a pas eu lieu.
OBSERVED = "observé"        # lu directement à la source (blockchain, API de marché)
VERIFIED = "vérifié"        # confirmé par recoupement
ESTIMATED = "estimé"        # calculé / approximé
UNVERIFIED = "non vérifié"  # affirmé mais non vérifiable avec les moyens disponibles
UNAVAILABLE = "indisponible"


def now() -> float:
    return time.time()


def dp(value: Any, source: str, status: str = OBSERVED, ts: float | None = None) -> dict:
    """Point de donnée traçable : valeur + source + horodatage + statut."""
    return {"v": value, "src": source, "ts": ts or now(), "st": status}


def val(point: Any, default: Any = None) -> Any:
    if isinstance(point, dict) and "v" in point:
        return point["v"] if point["v"] is not None else default
    return default if point is None else point


def is_valid_mint_format(address: str) -> bool:
    """Vérifie le format base58 et la longueur de 32 octets d'une adresse Solana."""
    if not address or not BASE58_RE.match(address):
        return False
    try:
        from solders.pubkey import Pubkey
        Pubkey.from_string(address)
        return True
    except Exception:
        return False


def clamp(x: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return max(lo, min(hi, x))


def fnum(x: Any) -> float | None:
    try:
        if x is None or x == "":
            return None
        return float(x)
    except (TypeError, ValueError):
        return None
