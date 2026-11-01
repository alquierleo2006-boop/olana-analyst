"""Configuration : paramètres en base SQLite, secrets dans le coffre du système (keyring)."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

APP_NAME = "SolanaAIDesktopAnalyst"


def data_dir() -> Path:
    base = os.environ.get("ANALYST_DATA_DIR")
    if base:
        p = Path(base)
    elif os.name == "nt":
        p = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    else:
        p = Path.home() / ".local" / "share" / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


DEFAULT_SETTINGS: dict = {
    "shortcut": "CommandOrControl+Shift+Space",
    "auto_analyze_on_shortcut": True,
    "always_on_top": True,
    "compact_mode": False,
    "launchpads": ["pumpfun", "letsbonk", "meteora_dbc", "stonkfun"],
    "providers": {
        "dexscreener": True, "geckoterminal": True, "jupiter": True, "rugcheck": True,
        "pumpfun_api": True, "gdelt": True, "rss": True, "reddit_rss": True,
        "x_oembed": True, "telegram_public": True, "discord_public": True, "github": True, "rdap": True,
    },
    "rpc_url": "https://api.mainnet-beta.solana.com",
    "llm": {"provider": "none", "base_url": "http://localhost:11434/v1", "model": "llama3.1:8b"},
    "weights": {"onchain": 25, "momentum": 20, "narrative": 25, "social": 20, "credibility": 10, "smart_money": 0},
    # Style de trading : chaque mode a ses propres pondérations (la sécurité garde toujours un poids fort).
    "trading_mode": "scalp",  # scalp | standard | hold
    "mode_weights": {
        "scalp": {"onchain": 35, "momentum": 40, "narrative": 10, "social": 10, "credibility": 0, "smart_money": 5},
        "hold": {"onchain": 25, "momentum": 10, "narrative": 20, "social": 20, "credibility": 25, "smart_money": 0},
    },
    "scalp": {"auto_watch": True, "interval_s": 3, "max_minutes": 60, "reversal_pct": 15, "pump_alert_pct": 25,
              "target_multiple": 2.0, "stop_pct": 30, "position_sol": 0.5},
    "thresholds": {"buy_setup_min": 7.0, "avoid_below": 4.0, "min_confidence_buy": 0.6,
                   "min_confidence": 0.35, "max_risk_buy": 5.0},
    "rise_definition_pct": 20.0,
    "probability_min_test_samples": 100,
    "risk_tolerance": "normal",  # prudent | normal | agressif
    "default_horizon": "1h",
    "notifications": {"enabled": True, "score_above": 8.0, "critical_risk": True,
                      "smart_money": True, "narrative_acceleration": True, "score_change": 1.5, "claim_confirmed": True,
                      "telegram": False},
    "narrative_refresh_minutes": 10,
    "history_retention_days": 365,
    "tracking_enabled": True,
}

# Noms des secrets (stockés via keyring, jamais en clair dans la base).
SECRET_NAMES = ["helius_api_key", "birdeye_api_key", "llm_api_key", "telegram_bot_token",
                "telegram_chat_id", "github_token"]


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Secrets:
    """Coffre du système (Windows Credential Manager / Keychain). Repli : variables d'environnement."""

    def __init__(self) -> None:
        try:
            import keyring  # noqa: F401
            from keyring.backends.fail import Keyring as FailKeyring
            import keyring as kr
            self._kr = None if isinstance(kr.get_keyring(), FailKeyring) else kr
        except Exception:
            self._kr = None
        self._mem: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        env = os.environ.get(name.upper())
        if env:
            return env
        if self._kr:
            try:
                v = self._kr.get_password(APP_NAME, name)
                if v:
                    return v
            except Exception:
                pass
        return self._mem.get(name)

    def set(self, name: str, value: str | None) -> str:
        if name not in SECRET_NAMES:
            raise ValueError("secret inconnu")
        if self._kr:
            try:
                if value:
                    self._kr.set_password(APP_NAME, name, value)
                else:
                    try:
                        self._kr.delete_password(APP_NAME, name)
                    except Exception:
                        pass
                return "keyring"
            except Exception:
                pass
        # Pas de coffre disponible : mémoire uniquement (perdu au redémarrage), jamais en clair sur disque.
        if value:
            self._mem[name] = value
        else:
            self._mem.pop(name, None)
        return "memory"

    def status(self) -> dict[str, bool]:
        return {n: bool(self.get(n)) for n in SECRET_NAMES}


def active_weights(settings: dict) -> dict:
    mode = settings.get("trading_mode", "standard")
    if mode in (settings.get("mode_weights") or {}):
        return settings["mode_weights"][mode]
    return settings.get("weights", {})


class Settings:
    def __init__(self, db) -> None:
        self.db = db
        self._cache: dict | None = None

    def all(self) -> dict:
        if self._cache is None:
            row = self.db.one("SELECT value FROM application_settings WHERE key='settings'")
            stored = json.loads(row["value"]) if row else {}
            self._cache = deep_merge(DEFAULT_SETTINGS, stored)
        return self._cache

    def get(self, key: str, default=None):
        return self.all().get(key, default)

    def update(self, patch: dict) -> dict:
        new = deep_merge(self.all(), patch)
        self.db.execute(
            "INSERT INTO application_settings(key, value) VALUES('settings', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(new),))
        self._cache = new
        return new
