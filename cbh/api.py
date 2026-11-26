"""Loopback-only JSON API for the native BugHunter AI Android companion."""
from __future__ import annotations

import hmac
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from cbh import automation


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
                    approved.append({
                        "file": path.name,
                        "target": str(item.get("target") or ""),
                        "scope_file": str(item.get("scope_file") or ""),
                    })
            except (OSError, UnicodeError, json.JSONDecodeError):
                approved.append({"file": path.name, "target": "", "scope_file": ""})

    try:
        from cbh.telegram import load_config
        telegram_configured = bool(load_config())
    except Exception:
        telegram_configured = False

    return {
        "findings": files_in("findings"),
        "evidence": files_in("evidence"),
        "reports": files_in("reports") + files_in("drafts"),
        "scope": scope,
        "approved_targets": approved,
        "telegram_configured": telegram_configured,
    }


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
                self._send(200, {"opportunities": automation.list_opportunities(limit=limit)})
            elif route == "/ledger":
                self._send(200, {
                    "summary": automation.ledger_summary(),
                    "transactions": automation.list_transactions(limit=100),
                })
            elif route == "/workspace":
                self._send(200, _workspace_snapshot())
            else:
                self._send(404, {"error": "not_found"})

        def do_POST(self):
            if not self._authorized():
                return
            if urlparse(self.path).path != "/ledger":
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
