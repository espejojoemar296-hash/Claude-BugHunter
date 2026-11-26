"""Offline, fail-closed scope and captured HTTP evidence checks."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

STATES = {"NOT_TESTED", "REPRODUCED", "NOT_REPRODUCED", "INCONCLUSIVE"}


def _scope(scope_file):
    engine = Path(__file__).resolve().parent.parent / "engine"
    if str(engine) not in sys.path:
        sys.path.insert(0, str(engine))
    from scope import _scope_from_md
    return _scope_from_md(str(scope_file))


def _artifact(root, relative):
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("artifact path must be a non-empty string")
    base = root.resolve()
    path = (base / relative).resolve()
    if path == base or base not in path.parents:
        raise ValueError("artifact path escapes evidence directory")
    if not path.is_file():
        raise ValueError(f"artifact not found: {relative}")
    return path


def validate_finding(finding_path, metadata, evidence_path, scope_file):
    result = {
        "scope": "NOT_CHECKED", "artifacts": "NOT_CHECKED",
        "reproduction": "NOT_REPORTED", "status": "INCONCLUSIVE",
        "reasons": [],
    }
    scope_file, evidence_path = Path(scope_file), Path(evidence_path)
    if not scope_file.is_file():
        result["status"] = "BLOCKED"
        result["reasons"].append(f"scope file not found: {scope_file}")
        return result

    target = str(metadata.get("asset") or metadata.get("endpoint") or "").strip()
    if not target:
        result["status"] = "BLOCKED"
        result["reasons"].append("finding must declare asset or endpoint")
        return result

    try:
        reason = _scope(scope_file).reject_reason(target)
    except Exception as exc:
        result["status"] = "BLOCKED"
        result["reasons"].append(f"scope could not be verified: {exc}")
        return result
    if reason:
        result["scope"] = "FAIL"
        result["status"] = "BLOCKED"
        result["reasons"].append(f"scope rejected target: {reason}")
        return result
    result["scope"] = "PASS"

    if not evidence_path.is_file():
        result["reasons"].append(f"evidence manifest not found: {evidence_path}")
        return result

    try:
        manifest = json.loads(evidence_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("version") != 1:
            raise ValueError("manifest must be an object with version: 1")
        manifest_target = manifest.get("target")
        if not isinstance(manifest_target, str) or manifest_target.strip().casefold() != target.casefold():
            raise ValueError("manifest target does not match finding asset/endpoint")

        reproduction = manifest.get("reproduction", {})
        if not isinstance(reproduction, dict):
            raise ValueError("reproduction must be an object")
        state = reproduction.get("status", "NOT_TESTED")
        if state not in STATES:
            raise ValueError("invalid reproduction status")
        result["reproduction"] = state

        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise ValueError("artifacts must be a list")
        found = {}
        for item in artifacts:
            if not isinstance(item, dict):
                raise ValueError("each artifact must be an object")
            kind = item.get("type")
            if kind not in ("http_request", "http_response"):
                continue
            if kind in found:
                raise ValueError(f"duplicate artifact: {kind}")
            path = _artifact(evidence_path.parent, item.get("path"))
            content = path.read_text(encoding="utf-8", errors="replace")
            if not content.strip():
                raise ValueError(f"empty artifact: {item.get('path')}")
            found[kind] = content

        missing = {"http_request", "http_response"} - set(found)
        if missing:
            raise ValueError("missing artifacts: " + ", ".join(sorted(missing)))
        request_line = found["http_request"].splitlines()[0]
        if not re.match(
            r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) \S+ HTTP/1\.[01]$",
            request_line, re.I,
        ):
            raise ValueError("invalid HTTP request line")
        if not re.search(r"^HTTP/1\.[01] \d{3}\b", found["http_response"], re.M):
            raise ValueError("response has no valid HTTP status line")
        result["artifacts"] = "PASS"
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        result["artifacts"] = "FAIL"
        result["reasons"].append(str(exc))
        return result

    if state == "REPRODUCED":
        result["status"] = "READY_FOR_REVIEW"
        result["reasons"].append(
            "Scope and evidence structure passed. Reproduction is operator-reported, not independently proven."
        )
    else:
        result["reasons"].append(
            "Scope and artifacts passed, but reproduction is not reported as reproduced."
        )
    return result
