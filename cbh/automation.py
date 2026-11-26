"""Persistent bounty discovery, approved-scope recon, and local ledger."""
from __future__ import annotations

import math
import os
import re
import json
import shutil
import sqlite3
import subprocess
import time
import sys
from pathlib import Path
from datetime import datetime, timezone


def data_dir():
    root = Path(os.environ.get(
        "CBH_DATA_DIR",
        str(Path.home() / ".local/share/claude-bughunter"),
    )).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def connect(path=None):
    db = Path(path) if path else data_dir() / "state.sqlite3"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS opportunities (
            platform TEXT NOT NULL, handle TEXT NOT NULL, name TEXT NOT NULL,
            url TEXT, reward TEXT, availability TEXT,
            score INTEGER NOT NULL DEFAULT 0,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
            PRIMARY KEY(platform, handle)
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK(kind IN ('income','expense')),
            amount REAL NOT NULL CHECK(amount > 0),
            currency TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
            program TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
    """)
    return con


def record_opportunities(results, path=None):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    added = 0
    with connect(path) as con:
        for item in results:
            platform = str(item.get("platform") or "").strip()
            handle = str(item.get("handle") or "").strip()
            if not platform or not handle:
                continue
            old = con.execute(
                "SELECT 1 FROM opportunities WHERE platform=? AND handle=?",
                (platform, handle),
            ).fetchone()
            added += int(old is None)
            con.execute("""
                INSERT INTO opportunities
                (platform,handle,name,url,reward,availability,score,first_seen,last_seen)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(platform,handle) DO UPDATE SET
                name=excluded.name,url=excluded.url,reward=excluded.reward,
                availability=excluded.availability,score=excluded.score,
                last_seen=excluded.last_seen
            """, (
                platform, handle, str(item.get("name") or handle),
                str(item.get("url") or ""), str(item.get("reward") or ""),
                str(item.get("availability") or ""), int(item.get("score") or 0),
                now, now,
            ))
    return added


def list_opportunities(path=None, limit=50):
    with connect(path) as con:
        rows = con.execute(
            "SELECT * FROM opportunities ORDER BY score DESC,name LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
    return [dict(x) for x in rows]


def add_transaction(kind, amount, currency="USD", note="", program="", path=None):
    if kind not in ("income", "expense"):
        raise ValueError("kind must be income or expense")
    amount = float(amount)
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError("amount must be a positive finite number")
    currency = str(currency).strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("currency must be a three-letter code, e.g. USD or PHP")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect(path) as con:
        cur = con.execute("""
            INSERT INTO transactions(kind,amount,currency,note,program,created_at)
            VALUES(?,?,?,?,?,?)
        """, (kind, amount, currency, str(note), str(program), now))
        return cur.lastrowid


def list_transactions(path=None, limit=50):
    with connect(path) as con:
        rows = con.execute(
            "SELECT * FROM transactions ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
    return [dict(x) for x in rows]


def ledger_summary(path=None):
    with connect(path) as con:
        rows = con.execute("""
            SELECT currency,kind,ROUND(SUM(amount),2) AS total,COUNT(*) AS entries
            FROM transactions GROUP BY currency,kind ORDER BY currency,kind
        """).fetchall()
    return [dict(x) for x in rows]


def notify(title, message):
    command = shutil.which("termux-notification")
    if command:
        try:
            subprocess.run(
                [command, "--title", title, "--content", message,
                 "--id", "cbh-opportunities"],
                check=False, timeout=10, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    print(f"[notification] {title}: {message}", flush=True)


def scan_approved_targets(approved_dir):
    """Recon only explicit JSON approvals whose targets pass the scope engine."""
    root = Path(approved_dir).expanduser().resolve()
    if not root.is_dir():
        print(f"[approved recon] directory not found: {root}")
        return
    engine = Path(__file__).resolve().parent.parent / "engine"
    if str(engine) not in sys.path:
        sys.path.insert(0, str(engine))
    try:
        from scope import _scope_from_md
        from cbh import cli
        from types import SimpleNamespace
    except Exception as exc:
        print(f"[approved recon] required components unavailable: {exc}")
        return

    for config_path in sorted(root.glob("*.json")):
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise ValueError("configuration must be a JSON object")
            target = str(config.get("target") or "").strip()
            scope_value = config.get("scope_file")
            if not target or not isinstance(scope_value, str) or not scope_value.strip():
                raise ValueError("target and scope_file are required")
            scope_path = (config_path.parent / scope_value).resolve()
            if not scope_path.is_file():
                raise ValueError("scope file does not exist")
            scope = _scope_from_md(str(scope_path))
            reason = scope.reject_reason(target)
            if reason:
                raise ValueError(f"scope rejected target: {reason}")
            print(f"[approved recon] starting {target}")
            args = SimpleNamespace(
                target=target, scope_file=str(scope_path), out=None,
                proxy=None, burp=False,
            )
            code = cli.cmd_recon(args)
            print(f"[approved recon] {target}: exit {code}")
        except Exception as exc:
            print(f"[approved recon] skipped {config_path.name}: {exc}")


def watch(interval=21600, once=False, platforms=None,
          scan_approved=False, approved_dir="targets/approved"):
    from cbh.hunt import PLATFORMS, discover

    interval = max(300, int(interval))
    selected = [platforms] if isinstance(platforms, str) else list(platforms or PLATFORMS)
    print("CBH AUTOPILOT — public bounty discovery")
    print("Recon is disabled unless --scan-approved is explicitly supplied.")
    print("No exploitation or automatic report submission.")
    while True:
        try:
            results, warnings = discover(
                platforms=selected, refresh=True, limit=1000
            )
            for warning in warnings:
                print(f"[warning] {warning}")
            added = record_opportunities(results)
            print(
                f"{datetime.now().astimezone().isoformat(timespec='seconds')}: "
                f"{len(results)} programs checked; {added} new"
            )
            if added:
                notify("Claude-BugHunter", f"{added} new bounty programs found")
            if scan_approved:
                scan_approved_targets(approved_dir)
        except KeyboardInterrupt:
            print("\nAutopilot stopped.")
            return 0
        except Exception as exc:
            print(f"[autopilot warning] {exc}")
        if once:
            return 0
        print(f"Next discovery cycle in {interval} seconds.")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nAutopilot stopped.")
            return 0
