"""One-request, low-impact HTTP inspection for explicitly authorized bounty assets.

This is a signal collector, not an exploit or a vulnerability verdict. It performs
exactly one GET, does not follow redirects, does not send cookies, and never crawls.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ORIGIN = "https://cbh-audit.invalid"
MAX_RESPONSE_BYTES = 65536


def _load_scope(scope_file: str):
    engine = Path(__file__).resolve().parent.parent / "engine"
    import sys
    if str(engine) not in sys.path:
        sys.path.insert(0, str(engine))
    from scope import _scope_from_md
    return _scope_from_md(str(scope_file))


def _safe_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("URL must be an absolute http:// or https:// URL")
    if parsed.username or parsed.password:
        raise ValueError("URL must not contain embedded credentials")
    if parsed.fragment:
        raise ValueError("URL fragments are not sent to the server; remove the fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL has an invalid port") from exc
    expected = 443 if parsed.scheme == "https" else 80
    if port not in (None, expected):
        raise ValueError("only standard HTTP/HTTPS ports are allowed by this low-impact check")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def cors_signal(headers: dict[str, str]) -> dict:
    lowered = {str(k).lower(): str(v).strip() for k, v in headers.items()}
    allow_origin = lowered.get("access-control-allow-origin", "")
    allow_credentials = lowered.get("access-control-allow-credentials", "").lower()
    reflected = allow_origin == ORIGIN
    credentials = allow_credentials == "true"
    return {
        "candidate": bool(reflected and credentials),
        "origin_reflected": reflected,
        "credentials_allowed": credentials,
        "reason": (
            "Server reflected the supplied cross-origin Origin and allowed credentials; "
            "browser-based impact and sensitive response exposure still require manual verification."
            if reflected and credentials else
            "No high-confidence credentialed-origin-reflection signal observed."
        ),
    }


def inspect_url(url: str, scope_file: str, out_dir: str) -> dict:
    target = _safe_url(url)
    scope_path = Path(scope_file).expanduser().resolve()
    if not scope_path.is_file():
        raise ValueError(f"scope file not found: {scope_path}")
    scope = _load_scope(str(scope_path))
    reason = scope.reject_reason(target)
    if reason:
        raise PermissionError("target is not authorized by the supplied scope: " + reason)

    request = urllib.request.Request(
        target,
        headers={"User-Agent": "BugHunterAI-Authorized-Research/1.0", "Origin": ORIGIN,
                 "Accept": "*/*"},
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirect())
    status, response_headers, body = 0, {}, b""
    try:
        with opener.open(request, timeout=8) as response:
            status = response.status
            response_headers = dict(response.headers.items())
            body = response.read(MAX_RESPONSE_BYTES)
    except urllib.error.HTTPError as exc:
        status = exc.code
        response_headers = dict(exc.headers.items()) if exc.headers else {}
        body = exc.read(MAX_RESPONSE_BYTES)
    except Exception as exc:
        raise RuntimeError(f"single-request inspection failed: {type(exc).__name__}: {exc}") from exc

    signal = cors_signal(response_headers)
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "request.txt").write_text(
        f"GET {urllib.parse.urlsplit(target).path or '/'}"
        f"{'?' + urllib.parse.urlsplit(target).query if urllib.parse.urlsplit(target).query else ''} HTTP/1.1\n"
        f"Host: {urllib.parse.urlsplit(target).netloc}\nOrigin: {ORIGIN}\n"
        "User-Agent: BugHunterAI-Authorized-Research/1.0\n\n",
        encoding="utf-8",
    )
    safe_headers = "\n".join(f"{k}: {v}" for k, v in response_headers.items())
    (root / "response.txt").write_bytes(
        f"HTTP/1.1 {status} RESPONSE\n{safe_headers}\n\n".encode("utf-8", "replace") + body
    )
    manifest = {
        "version": 1, "target": target,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "GET", "requests_sent": 1, "redirects_followed": 0,
        "response_status": status,
        "reproduction": {"status": "INCONCLUSIVE"},
        "artifacts": [
            {"type": "http_request", "path": "request.txt"},
            {"type": "http_response", "path": "response.txt"},
        ],
        "checks": {"cors": signal},
        "limitations": [
            "One GET only; no cookies, authentication, crawling, payload injection, or state changes.",
            "A CORS signal is a lead, not proof of exploitable impact; verify with an authorized test account and browser.",
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="cbh-inspect",
        description="Perform one low-impact, scope-gated GET and save HTTP evidence.",
    )
    parser.add_argument("url", help="one explicitly authorized HTTP(S) URL")
    parser.add_argument("--scope-file", default="scope.md")
    parser.add_argument("--out", default="evidence/inspection")
    args = parser.parse_args(argv)
    try:
        result = inspect_url(args.url, args.scope_file, args.out)
    except (ValueError, PermissionError, RuntimeError, OSError) as exc:
        print("[blocked/error] " + str(exc))
        return 2
    print("One request completed; no redirects followed.")
    print("HTTP status:", result["response_status"])
    print("Evidence:", str(Path(args.out).expanduser().resolve()))
    print("Credentialed CORS candidate:", "YES — manual verification required"
          if result["checks"]["cors"]["candidate"] else "not observed")
    print("Reproduction status remains INCONCLUSIVE; this is not a validated vulnerability.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
