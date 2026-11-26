"""Read-only public bug bounty opportunity discovery."""
from __future__ import annotations

from cbh import scope_import as si

PLATFORMS = ("hackerone", "bugcrowd", "intigriti", "yeswehack")


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _reward(platform, rec):
    if platform == "hackerone":
        if rec.get("offers_bounties") is True:
            return "Bounty offered; amount not published in dataset", True
        return "No bounty indicated", False

    if platform == "bugcrowd":
        maximum = _number(rec.get("max_payout"))
        if maximum is not None and maximum > 0:
            return f"Up to {maximum:g} (currency unspecified)", True
        return "No published maximum", False

    if platform == "intigriti":
        low, high = rec.get("min_bounty") or {}, rec.get("max_bounty") or {}
        minimum = _number(low.get("value")) if isinstance(low, dict) else None
        maximum = _number(high.get("value")) if isinstance(high, dict) else None
        currency = high.get("currency") if isinstance(high, dict) else None
        if minimum is not None and maximum is not None:
            return f"{minimum:g}–{maximum:g} {currency or '(currency unspecified)'}", maximum > 0
        return "Reward range unavailable", False

    minimum = _number(rec.get("min_bounty"))
    maximum = _number(rec.get("max_bounty"))
    if minimum is not None and maximum is not None:
        return f"{minimum:g}–{maximum:g} (currency unspecified)", maximum > 0
    return "Reward range unavailable", False


def _availability(platform, rec):
    if platform == "hackerone":
        state = str(rec.get("submission_state") or "unknown")
        return state, state == "open"

    if platform == "intigriti":
        state = str(rec.get("status") or "unknown")
        public = str(rec.get("confidentiality_level") or "").lower() == "public"
        return f"{state}; {'public' if public else 'visibility unverified'}", state.lower() == "open" and public

    if platform == "yeswehack":
        public = rec.get("public") is True
        enabled = rec.get("disabled") is False
        return ("public and enabled" if public and enabled else
                "not confirmed public/enabled"), public and enabled

    return "status not supplied by dataset", None


def _asset_counts(program):
    usable = [e for e in program.entries if e.side == "in" and e.status == "rule"]
    review = [e for e in program.entries if e.side == "in" and e.status == "review"]
    web_api_types = {
        "api", "url", "website", "web-application", "web application", "webapp"
    }
    web_api = sum(
        str(e.asset_type or "").strip().lower().replace("_", "-") in web_api_types
        for e in usable
    )
    bounty_assets = sum(e.bounty is True for e in usable)
    return len(usable), len(review), web_api, bounty_assets


def _score(reward, usable, review, web_api, availability):
    # A transparent prioritization heuristic, not a payout prediction.
    reward_points = 25 if reward else 0
    web_api_points = min(25, web_api * 0.5)
    clarity_points = 20 * usable / max(1, usable + review)
    breadth_points = min(20, usable * 0.25)
    status_points = 10 if availability is True else 0
    review_penalty = min(10, review * 2)
    return round(max(0, reward_points + web_api_points + clarity_points
                     + breadth_points + status_points - review_penalty))


def discover(platforms=None, search=None, bounty_only=False,
             open_only=False, refresh=False, limit=20):
    selected = tuple(platforms or PLATFORMS)
    if any(p not in PLATFORMS for p in selected):
        raise ValueError("unsupported platform")

    results, warnings = [], []

    for platform in selected:
        try:
            records, cache_path = si.load_platform(platform, refresh=refresh)
        except Exception as exc:
            warnings.append(f"{platform}: {exc}")
            continue

        for rec in records:
            handle = str(si._record_handle(platform, rec) or "")
            name = str(rec.get("name") or handle or "Unnamed program")

            if search:
                needle = search.casefold()
                if needle not in name.casefold() and needle not in handle.casefold():
                    continue

            reward_label, has_reward = _reward(platform, rec)
            availability_label, is_open = _availability(platform, rec)

            if platform == "intigriti" and is_open is not True:
                continue
            if platform == "yeswehack" and is_open is not True:
                continue
            if platform == "hackerone" and is_open is not True:
                continue
            if open_only and is_open is not True:
                continue
            if bounty_only and not has_reward:
                continue

            program = si.program_from_record(platform, rec)
            usable, review, web_api, bounty_assets = _asset_counts(program)
            score = _score(has_reward, usable, review, web_api, is_open)

            results.append({
                "platform": platform, "handle": handle, "name": name,
                "url": rec.get("url") or "", "reward": reward_label,
                "has_reward": has_reward, "availability": availability_label,
                "usable_assets": usable, "review_assets": review,
                "web_api_assets": web_api, "bounty_assets": bounty_assets,
                "score": score, "cache": cache_path,
            })

    results.sort(key=lambda x: (-x["score"], x["name"].casefold()))
    return results[:max(1, limit)], warnings
