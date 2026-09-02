"""
db.py — SQLite persistence for trades, decisions, and positions.
"""

import sqlite3
import json
import os
import logging
from datetime import datetime

logger = logging.getLogger("icarus.db")

DB_PATH = os.environ.get("DB_DIR", ".") + "/icarus.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            strike REAL,
            expiry TEXT,
            option_type TEXT,
            qty INTEGER DEFAULT 1,
            price REAL,
            status TEXT DEFAULT 'open',
            pnl REAL DEFAULT 0,
            ai_reasoning TEXT,
            metadata TEXT
        );

        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            reasoning TEXT,
            confidence REAL,
            candidate_data TEXT
        );

        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbols_scanned INTEGER DEFAULT 0,
            candidates_found INTEGER DEFAULT 0,
            trades_executed INTEGER DEFAULT 0,
            summary TEXT
        );
    """)
    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")


def log_trade(symbol, action, strike=None, expiry=None, option_type=None,
              qty=1, price=None, ai_reasoning=None, metadata=None):
    conn = get_db()
    conn.execute(
        """INSERT INTO trades (timestamp, symbol, action, strike, expiry,
           option_type, qty, price, ai_reasoning, metadata)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(), symbol, action, strike, expiry,
         option_type, qty, price, ai_reasoning,
         json.dumps(metadata) if metadata else None)
    )
    conn.commit()
    conn.close()


def log_decision(symbol, action, reasoning, confidence, candidate_data=None):
    conn = get_db()
    conn.execute(
        """INSERT INTO decisions (timestamp, symbol, action, reasoning,
           confidence, candidate_data)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(), symbol, action, reasoning, confidence,
         json.dumps(candidate_data) if candidate_data else None)
    )
    conn.commit()
    conn.close()


def log_scan(symbols_scanned, candidates_found, trades_executed, summary=""):
    conn = get_db()
    conn.execute(
        """INSERT INTO scans (timestamp, symbols_scanned, candidates_found,
           trades_executed, summary) VALUES (?, ?, ?, ?, ?)""",
        (datetime.now().isoformat(), symbols_scanned, candidates_found,
         trades_executed, summary)
    )
    conn.commit()
    conn.close()


def get_trades(limit=50):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_decisions(limit=50):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_scans(limit=20):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats():
    conn = get_db()
    total_trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    approvals = conn.execute(
        "SELECT COUNT(*) FROM decisions WHERE action='APPROVE'"
    ).fetchone()[0]
    rejections = conn.execute(
        "SELECT COUNT(*) FROM decisions WHERE action='REJECT'"
    ).fetchone()[0]
    total_scans = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    conn.close()

    return {
        "total_trades": total_trades,
        "total_decisions": approvals + rejections,
        "approvals": approvals,
        "rejections": rejections,
        "approval_rate": round(approvals / max(1, approvals + rejections) * 100, 1),
        "total_scans": total_scans,
    }