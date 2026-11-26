"""Loopback-only JSON API for the native BugHunter AI Android companion."""
from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from cbh import automation

_JOB_LOCK = threading.Lock()
_JOB = {"status": "idle"}
_DISCOVERY_LOCK = threading.Lock()
_DISCOVERY_JOB = {"status": "idle"}


def _start_discovery():
    global _DISCOVERY_JOB
    with _DISCOVERY_LOCK:
        if _DISCOVERY_JOB.get("status") == "running":
            return False

        _DISCOVERY_JOB = {"status": "running"}

    def worker():
        global _DISCOVERY_JOB
        try:
            from cbh.hunt import discover
            results, warnings = discover(refresh=True, limit=1000)
            added = automation.record_opportunities(results)
            with _DISCOVERY_LOCK:
                _DISCOVERY_JOB = {
                    "status": "completed", "checked": len(results),
                    "added": added, "warnings": warnings[:20],
                }
        except Exception as exc:
            with _DISCOVERY_LOCK:
                _DISCOVERY_JOB = {"status": "failed", "error": str(exc)[:500]}

    thread = threading.Thread(target=worker, name="cbh-discovery", daemon=True)
    thread.start()
    return True


def _start_engagement(config_name):
    global _JOB
    if not isinstance(config_name, str) or not config_name or Path(config_name).name != config_name or not config_name.endswith(".json"):
        raise ValueError("config must be the filename of an approved .json file")
    approved_root = (Path.cwd() / "targets" / "approved").resolve()
    config_path = (approved_root / config_name).resolve()
    if config_path.parent != approved_root or not config_path.is_file():
        raise ValueError("approved target config was not found")
    with _JOB_LOCK:
        if _JOB.get("status") == "running":
            return False
        _JOB = {"status": "running", "config": config_name}

    def worker():
        global _JOB
        try:
            from cbh.engagement import run_approved_engagement
            result = run_approved_engagement(config_path)
            with _JOB_LOCK:
                _JOB = {"status": "completed", "config": config_name, "result": result}
        except Exception as exc:
            with _JOB_LOCK:
                _JOB = {"status": "failed", "config": config_name, "error": str(exc)[:500]}

    thread = threading.Thread(target=worker, name="cbh-engagement", daemon=True)
    thread.start()
    return True


def token_path() -> Path:
    return Path(os.environ.get(
        "CBH_API_TOKEN_FILE",
        str(Path.home() / ".config/claude-bughunter/api-token"),
    )).expanduser()


def load_or_create_token() -> str:
    override = os.environ.get("CBH_API_TOKEN")
    if override:
        return override.strip()
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    if path.is_file():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def _workspace_snapshot():
    root = Path.cwd().resolve()

    def files_in(folder):
        base = root / folder
        result = []
        if not base.is_dir():
            return result
        for path in sorted(base.rglob("*")):
            try:
                if not path.is_file() or path.is_symlink():
                    continue
                resolved = path.resolve()
                if root not in resolved.parents:
                    continue
                result.append({
                    "path": resolved.relative_to(root).as_posix(),
                    "name": path.name,
                    "size": path.stat().st_size,
                })
                if len(result) >= 100:
                    break
            except OSError:
                continue
        return result

    scope_path = root / "scope.md"
    scope = {"exists": scope_path.is_file(), "path": "scope.md", "preview": ""}
    if scope_path.is_file():
        try:
            scope["preview"] = scope_path.read_text(encoding="utf-8")[:5000]
        except (OSError, UnicodeError):
            scope["preview"] = "[scope file could not be read]"

    approved = []
    approved_dir = root / "targets" / "approved"
    if approved_dir.is_dir():
        for path in sorted(approved_dir.glob("*.json"))[:100]:
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(item, dict):
                    scope_value = str(item.get("scope_file") or "")
                    scope_preview = ""
                    if scope_value:
                        scope_path = (path.parent / scope_value).resolve()
                        if root == scope_path or root in scope_path.parents:
                            try:
                                if scope_path.is_file():
                                    scope_preview = scope_path.read_text(encoding="utf-8")[:3000]
                            except (OSError, UnicodeError):
                                scope_preview = "[scope file could not be read]"
                    approved.append({
                        "file": path.name,
                        "target": str(item.get("target") or ""),
                        "scope_file": scope_value,
                        "scope_preview": scope_preview,
                    })
            except (OSError, UnicodeError, json.JSONDecodeError):
                approved.append({"file": path.name, "target": "", "scope_file": ""})

    engagement_reports = []
    engagement_root = Path.home() / ".bughunter-engagements"
    if engagement_root.is_dir():
        engagement_files = list(engagement_root.glob("*/report.md")) + list(
            engagement_root.glob("*/submission-drafts/*.md")
        )
        for path in sorted(engagement_files)[-100:]:
            try:
                if path.is_file() and not path.is_symlink():
                    engagement_reports.append({"path": str(path), "name": path.name, "size": path.stat().st_size})
            except OSError:
                continue

    try:
        from cbh.telegram import load_config
        telegram_configured = bool(load_config())
    except Exception:
        telegram_configured = False

    return {
        "findings": files_in("findings"),
        "evidence": files_in("evidence"),
        "reports": files_in("reports") + files_in("drafts") + engagement_reports,
        "scope": scope,
        "approved_targets": approved,
        "telegram_configured": telegram_configured,
    }



def _opportunity_details(rows):
    """Attach published scope metadata from the local bounty-targets-data cache."""
    from cbh import scope_import as si

    wanted = {(str(row.get("platform") or ""), str(row.get("handle") or "")) for row in rows}
    by_platform = {}
    for platform, handle in wanted:
        if platform not in by_platform:
            try:
                records, _ = si.load_platform(platform, refresh=False)
                by_platform[platform] = {
                    str(si._record_handle(platform, rec) or ""): rec
                    for rec in records
                }
            except Exception:
                by_platform[platform] = {}

    result = []
    for row in rows:
        item = dict(row)
        platform, handle = str(item.get("platform") or ""), str(item.get("handle") or "")
        rec = by_platform.get(platform, {}).get(handle)
        details = {
            "in_scope": [], "out_of_scope": [], "needs_review": [],
            "other_assets": [], "conduct": [],
            "scope_source": "public program dataset; verify on the platform before testing",
        }
        if rec:
            try:
                program = si.program_from_record(platform, rec)
                for entry in program.entries[:500]:
                    asset = {
                        "asset": str(entry.raw)[:200],
                        "type": str(entry.asset_type)[:80],
                        "status": str(entry.status)[:40],
                        "bounty_eligible": entry.bounty,
                        "severity": str(entry.severity)[:80],
                        "instruction": str(entry.instruction)[:200],
                        "notes": str(entry.reason)[:200],
                        "rules": [str(rule)[:200] for rule in entry.rules[:20]],
                    }
                    if entry.side == "out":
                        details["out_of_scope"].append(asset)
                    elif entry.status == "rule":
                        details["in_scope"].append(asset)
                    elif entry.status == "other":
                        details["other_assets"].append(asset)
                    else:
                        details["needs_review"].append(asset)
                details["conduct"] = [str(x)[:300] for x in program.conduct[:50]]
            except Exception as exc:
                details["scope_source"] = "scope details unavailable: " + type(exc).__name__
        else:
            details["scope_source"] = "scope data not present in local cache; open the platform page to verify"
        item["details"] = details
        result.append(item)
    return result

def make_handler(token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CBHLocalAPI/1"

        def _send(self, status: int, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, "Bearer " + token):
                self._send(401, {"error": "unauthorized"})
                return False
            return True

        def do_GET(self):
            if not self._authorized():
                return
            route = urlparse(self.path).path
            if route == "/health":
                self._send(200, {"ok": True, "service": "claude-bughunter", "api": 1})
            elif route == "/opportunities":
                query = parse_qs(urlparse(self.path).query)
                try:
                    limit = max(1, min(int(query.get("limit", ["50"])[0]), 200))
                except (TypeError, ValueError):
                    limit = 50
                rows = automation.list_opportunities(limit=limit)
                self._send(200, {"opportunities": _opportunity_details(rows)})
            elif route == "/opportunities/status":
                with _DISCOVERY_LOCK:
                    self._send(200, dict(_DISCOVERY_JOB))
            elif route == "/ledger":
                self._send(200, {
                    "summary": automation.ledger_summary(),
                    "transactions": automation.list_transactions(limit=100),
                })
            elif route == "/workspace":
                self._send(200, _workspace_snapshot())
            elif route == "/engagement/status":
                with _JOB_LOCK:
                    self._send(200, dict(_JOB))
            else:
                self._send(404, {"error": "not_found"})

        def do_POST(self):
            if not self._authorized():
                return
            route = urlparse(self.path).path
            if route == "/opportunities/refresh":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 0 or length > 1024:
                        raise ValueError("invalid request size")
                    if length:
                        self.rfile.read(length)
                    started = _start_discovery()
                    if not started:
                        self._send(409, {"error": "opportunity discovery is already running"})
                    else:
                        self._send(202, {"started": True})
                except (ValueError, TypeError) as exc:
                    self._send(400, {"error": str(exc)[:200]})
                return
            if route == "/engagement/run":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 1 or length > 8192:
                        raise ValueError("invalid request size")
                    data = json.loads(self.rfile.read(length).decode("utf-8"))
                    if not isinstance(data, dict):
                        raise ValueError("JSON body must be an object")
                    started = _start_engagement(data.get("config"))
                    if not started:
                        self._send(409, {"error": "an engagement is already running"})
                    else:
                        self._send(202, {"started": True, "config": data.get("config")})
                except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
                    self._send(400, {"error": str(exc)[:200]})
                return
            if route != "/ledger":
                self._send(404, {"error": "not_found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 65536:
                    raise ValueError("invalid request size")
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("JSON body must be an object")
                row_id = automation.add_transaction(
                    data.get("kind"), data.get("amount"),
                    data.get("currency", "USD"), data.get("note", ""),
                    data.get("program", ""),
                )
                self._send(201, {"id": row_id, "created": True})
            except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
                self._send(400, {"error": str(exc)[:200]})

        def log_message(self, fmt, *args):
            print("[cbh-api] " + (fmt % args), flush=True)

    return Handler


def serve(host="127.0.0.1", port=8765):
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("CBH API may only bind to loopback")
    token = load_or_create_token()
    server = ThreadingHTTPServer((host, int(port)), make_handler(token))
    print("BugHunter AI local API listening on " + host + ":" + str(port), flush=True)
    print("Paste this API token into the Android app (shown only at startup):", flush=True)
    print(token, flush=True)
    print("Keep this Termux session running. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCBH API stopped.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
