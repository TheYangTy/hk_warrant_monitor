from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from hk_warrant_monitor.infra.config_loader import project_path


SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  direction TEXT NOT NULL,
  risk_level TEXT NOT NULL,
  allow_overnight INTEGER NOT NULL DEFAULT 0,
  enable INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS market_snapshot (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL,
  name TEXT,
  last_price REAL,
  change_rate REAL,
  volume REAL,
  turnover REAL,
  amplitude REAL,
  turnover_rate REAL,
  bid_price REAL,
  ask_price REAL,
  bid_volume REAL,
  ask_volume REAL,
  snapshot_time TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS indicator_snapshot (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL,
  ktype TEXT NOT NULL,
  ma5 REAL,
  ma10 REAL,
  ma20 REAL,
  ma60 REAL,
  vwap REAL,
  rsi REAL,
  macd REAL,
  macd_signal REAL,
  macd_hist REAL,
  boll_mid REAL,
  boll_upper REAL,
  boll_lower REAL,
  calculated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS derivative_product (
  id INTEGER PRIMARY KEY,
  underlying_code TEXT NOT NULL,
  product_code TEXT NOT NULL UNIQUE,
  name TEXT,
  product_type TEXT,
  issuer TEXT,
  leverage REAL,
  strike_price REAL,
  expire_date TEXT,
  iv REAL,
  street_ratio REAL,
  spread REAL,
  volume REAL,
  turnover REAL,
  last_price REAL,
  extra_json TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trade_signal (
  id INTEGER PRIMARY KEY,
  underlying_code TEXT NOT NULL,
  product_code TEXT,
  action TEXT NOT NULL,
  confidence INTEGER NOT NULL,
  reason TEXT NOT NULL,
  risk TEXT NOT NULL,
  payload_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS position (
  id INTEGER PRIMARY KEY,
  product_code TEXT NOT NULL,
  buy_price REAL NOT NULL,
  quantity INTEGER NOT NULL,
  buy_time TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'OPEN',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS push_record (
  id INTEGER PRIMARY KEY,
  dedupe_key TEXT NOT NULL UNIQUE,
  level TEXT NOT NULL,
  scene TEXT NOT NULL,
  target_code TEXT,
  content TEXT,
  pushed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_call_record (
  id INTEGER PRIMARY KEY,
  target_code TEXT NOT NULL,
  action TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  total_tokens INTEGER,
  success INTEGER NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS runtime_state (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, db_path: str):
        path = Path(db_path)
        if not path.is_absolute():
            path = project_path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.connect() as conn:
            conn.execute(sql, tuple(params))

    def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute(sql, tuple(params)).fetchall())

    def fetchone(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(sql, tuple(params)).fetchone()

    def set_state(self, key: str, value: str) -> None:
        self.execute(
            """
            INSERT INTO runtime_state (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
              value=excluded.value,
              updated_at=CURRENT_TIMESTAMP
            """,
            (key, value),
        )


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
