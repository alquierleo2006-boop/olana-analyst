"""Base SQLite locale. Chaque analyse est stockée intégralement (JSON) pour être traçable et reproductible."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS application_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS tokens (
    mint TEXT PRIMARY KEY, name TEXT, symbol TEXT, launchpad TEXT, decimals INTEGER,
    created_at REAL, first_seen REAL NOT NULL, last_analysis_id INTEGER
);

CREATE TABLE IF NOT EXISTS model_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL, weights TEXT NOT NULL,
    thresholds TEXT NOT NULL, note TEXT
);

CREATE TABLE IF NOT EXISTS token_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT NOT NULL, created_at REAL NOT NULL,
    finished_at REAL, status TEXT NOT NULL, mode TEXT, launchpad TEXT, name TEXT, symbol TEXT,
    score REAL, verdict TEXT, confidence REAL, risk REAL,
    mcap REAL, liquidity REAL, volume_24h REAL, price_usd REAL,
    first_result_ms INTEGER, total_ms INTEGER, model_version_id INTEGER,
    result_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_analyses_mint ON token_analyses(mint);
CREATE INDEX IF NOT EXISTS idx_analyses_created ON token_analyses(created_at);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT NOT NULL, ts REAL NOT NULL, source TEXT,
    price_usd REAL, mcap REAL, fdv REAL, liquidity REAL, volume_24h REAL, holders INTEGER
);
CREATE INDEX IF NOT EXISTS idx_market_mint ON market_snapshots(mint, ts);

CREATE TABLE IF NOT EXISTS holder_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT NOT NULL, ts REAL NOT NULL,
    top10_pct REAL, top20_pct REAL, holders INTEGER, data TEXT
);

CREATE TABLE IF NOT EXISTS wallets (
    address TEXT PRIMARY KEY, label TEXT, added_at REAL NOT NULL, tracked INTEGER NOT NULL DEFAULT 1,
    stats TEXT, stats_updated REAL
);

CREATE TABLE IF NOT EXISTS developer_profiles (
    address TEXT PRIMARY KEY, updated_at REAL NOT NULL, data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS social_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT NOT NULL, platform TEXT NOT NULL, url TEXT,
    status TEXT, reasons TEXT, checked_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS news_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE, title TEXT NOT NULL, domain TEXT,
    source_type TEXT, published_at REAL, fetched_at REAL NOT NULL, country TEXT, lang TEXT,
    story_key TEXT, terms TEXT
);
CREATE INDEX IF NOT EXISTS idx_news_pub ON news_articles(published_at);

CREATE TABLE IF NOT EXISTS narratives (
    id INTEGER PRIMARY KEY AUTOINCREMENT, computed_at REAL NOT NULL, rank INTEGER, name TEXT,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS token_narratives (
    id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER, mint TEXT, narrative TEXT,
    score REAL, data TEXT
);

CREATE TABLE IF NOT EXISTS fact_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER, mint TEXT, claim TEXT,
    origin TEXT, status TEXT, confidence REAL, sources TEXT, checked_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER, mint TEXT, level TEXT,
    code TEXT, message TEXT, source TEXT, ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS smart_money_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER, mint TEXT, wallet TEXT,
    kind TEXT, data TEXT, ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS historical_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id INTEGER NOT NULL, horizon TEXT NOT NULL,
    due_at REAL NOT NULL, taken_at REAL, delay_s REAL, price_usd REAL, mcap REAL, liquidity REAL,
    max_mcap REAL, min_mcap REAL, change_pct REAL, status TEXT NOT NULL DEFAULT 'pending',
    UNIQUE(analysis_id, horizon)
);
CREATE INDEX IF NOT EXISTS idx_perf_due ON historical_performance(status, due_at);

CREATE TABLE IF NOT EXISTS scalp_outcomes (
    analysis_id INTEGER PRIMARY KEY, due_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
    outcome TEXT, minutes REAL, entry_price REAL, max_gain_pct REAL, max_drawdown_pct REAL, final_change_pct REAL,
    tp_pct REAL, sl_pct REAL, cost_pct REAL, pnl_pct REAL, score REAL, decision TEXT, evaluated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_scalp_due ON scalp_outcomes(status, due_at);

CREATE TABLE IF NOT EXISTS api_providers (
    name TEXT PRIMARY KEY, status TEXT, last_ok REAL, last_error TEXT, last_latency_ms INTEGER,
    calls INTEGER DEFAULT 0, errors INTEGER DEFAULT 0
);
"""


class DB:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple | list = ()) -> int:
        with self._lock:
            cur = self.conn.execute(sql, params)
            return cur.lastrowid

    def executemany(self, sql: str, rows: list) -> None:
        with self._lock:
            self.conn.executemany(sql, rows)

    def one(self, sql: str, params: tuple | list = ()) -> dict | None:
        with self._lock:
            row = self.conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: tuple | list = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    # ---- modèle de scoring versionné : jamais modifié silencieusement
    def current_model_version(self, weights: dict, thresholds: dict) -> int:
        w, t = json.dumps(weights, sort_keys=True), json.dumps(thresholds, sort_keys=True)
        row = self.one("SELECT id, weights, thresholds FROM model_versions ORDER BY id DESC LIMIT 1")
        if row and row["weights"] == w and row["thresholds"] == t:
            return row["id"]
        import time
        note = "version initiale" if not row else "pondérations/seuils modifiés par l'utilisateur"
        return self.execute("INSERT INTO model_versions(created_at, weights, thresholds, note) VALUES(?,?,?,?)",
                            (time.time(), w, t, note))
