"""Run the existing engagement engine from an explicitly approved CBH target."""
from __future__ import annotations

import json
import re
import shutil
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent


def _engine_scope(scope_file: Path, config: dict):
    engine_dir = REPO_ROOT / "engine"
    if str(engine_dir) not in sys.path:
        sys.path.insert(0, str(engine_dir))
    from scope import _scope_from_md

    scope = _scope_from_md(str(scope_file))
    target = str(config.get("target") or "").strip()
    if not target:
        raise ValueError("approved target config must contain target")
    reason = scope.reject_reason(target)
    if reason:
        raise ValueError(f"target is not authorized by scope.md: {reason}")

    raw_seeds = config.get("seeds")
    if raw_seeds is None:
        raw_seeds = [target]
    if not isinstance(raw_seeds, list) or not raw_seeds:
        raise ValueError("seeds must be a non-empty JSON array")
    seeds = []
    for raw in raw_seeds:
        value = str(raw or "").strip()
        if not value:
            raise ValueError("seed entries must not be empty")
        if "://" not in value:
            value = "https://" + value
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f"invalid HTTP(S) seed: {raw!r}")
        reason = scope.reject_reason(value)
        if reason:
            raise ValueError(f"seed is not authorized by scope.md: {reason}")
        seeds.append(value)
    return scope, seeds


def run_approved_engagement(config_path, *, max_hunts=10, parallel=2,
                            model="claude-sonnet-4-6", mock=False,
                            expand=False, base=None):
    """Execute recon -> rank -> map -> hunt -> validate -> report.

    Normal runs require the Claude Code CLI and are read-only by default.
    mock=True is an offline wiring test and never contacts the configured target.
    """
    config_path = Path(config_path).expanduser().resolve()
    if not config_path.is_file():
        raise ValueError(f"approved target config not found: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("approved target config must be a JSON object")

    scope_value = config.get("scope_file")
    if not isinstance(scope_value, str) or not scope_value.strip():
        raise ValueError("approved target config must contain scope_file")
    scope_file = (config_path.parent / scope_value).resolve()
    if not scope_file.is_file():
        raise ValueError(f"scope file not found: {scope_file}")

    scope, seeds = _engine_scope(scope_file, config)
    if not mock and shutil.which("claude") is None:
        raise RuntimeError(
            "AI hunting requires the Claude Code CLI (claude) to be installed "
            "and authenticated in Termux. No target requests were sent."
        )

    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(config.get("name") or scope.name)).strip("-")
    safe_name = (safe_name or "engagement")[:48]
    run_id = uuid.uuid4().hex[:10]
    state_root = Path(base or (Path.home() / ".bughunter-engagements")).expanduser()
    generated_scope_dir = Path.home() / ".config" / "claude-bughunter" / "engagement-scopes"
    generated_scope_dir.mkdir(parents=True, exist_ok=True)
    generated_scope = generated_scope_dir / f"{safe_name}-{run_id}.json"
    generated_scope.write_text(json.dumps({
        "name": safe_name,
        "in_scope": scope.in_scope,
        "out_of_scope": scope.out_of_scope,
        "seeds": seeds,
    }, indent=2) + "\n", encoding="utf-8")

    if str(REPO_ROOT / "engine") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "engine"))
    from engine.engine import Engine, ALL_PHASES

    runner = Engine(
        str(generated_scope), str(state_root), model, max(1, min(int(max_hunts), 100)),
        40, 600, mock=mock, allow_intrusive=False,
        parallel=max(1, min(int(parallel), 4)), expand=expand,
        use_memory=False, use_metrics=False,
    )
    runner.run(ALL_PHASES)
    report_path = Path(runner.eng.dir) / "report.md"
    return {
        "ok": report_path.is_file(),
        "name": safe_name,
        "run_id": run_id,
        "engagement_dir": str(runner.eng.dir),
        "report": str(report_path) if report_path.is_file() else "",
        "summary": runner.eng.summary(),
        "mock": bool(mock),
    }
