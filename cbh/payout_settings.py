"""Privacy-minimizing local payout preference storage.

Stores only a provider label and a masked account reference. Never store credentials,
full account numbers, card data, PINs, recovery phrases, or identity documents here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_ALLOWED = {"PayPal", "Bank transfer", "GCash", "Maya", "Other"}


def _path() -> Path:
    return Path(os.environ.get(
        "CBH_PAYOUT_SETTINGS",
        str(Path.home() / ".config" / "claude-bughunter" / "payout-settings.json"),
    )).expanduser()


def load() -> dict:
    path = _path()
    if not path.exists():
        return {"provider": "", "masked_reference": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"provider": "", "masked_reference": ""}
        provider = data.get("provider", "")
        masked = data.get("masked_reference", "")
        return {
            "provider": provider if provider in _ALLOWED else "",
            "masked_reference": masked if isinstance(masked, str) else "",
        }
    except (OSError, ValueError, TypeError):
        return {"provider": "", "masked_reference": ""}


def save(provider: str, masked_reference: str) -> dict:
    provider = str(provider or "").strip()
    masked_reference = str(masked_reference or "").strip()
    if provider not in _ALLOWED:
        raise ValueError("Choose a supported payout provider.")
    if len(masked_reference) > 80:
        raise ValueError("Masked reference is too long.")
    if any(ch.isdigit() for ch in masked_reference) and not any(
        marker in masked_reference for marker in ("*", "•", "x", "X")
    ):
        raise ValueError("Use a masked reference only, such as ••••1234.")
    if any(ch in masked_reference for ch in "\\r\\n"):
        raise ValueError("Invalid masked reference.")
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({
        "provider": provider,
        "masked_reference": masked_reference,
    }, ensure_ascii=False) + "\\n", encoding="utf-8")
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    temp.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return {"provider": provider, "masked_reference": masked_reference}
