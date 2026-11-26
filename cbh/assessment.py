"""Safe local-only one-tap assessment orchestration.

Performs bounded local inspection, deterministic static checks and offline
synthetic impact summaries. It never makes network requests or executes code.
"""
from __future__ import annotations
import hashlib, json, os, re, threading, time, uuid, zipfile
from pathlib import Path
from xml.etree import ElementTree

_LOCK = threading.RLock()
_STOP = threading.Event()
_JOB = {"status": "idle", "phase": "idle"}
_THREAD = None
_SKIP_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__", "node_modules", ".gradle", "build", "dist", "target", ".bughunter-assessments", ".idea", ".pytest_cache"}
_TEXT_EXTS = {".py", ".kt", ".java", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".php", ".rb", ".cs", ".c", ".h", ".cpp", ".swift", ".sh", ".sql", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".json", ".xml", ".properties", ".gradle", ".md", ".txt", ".html", ".css"}
_DOC_EXTS = {".pdf", ".docx"}
_MAX_FILES, _MAX_FILE_BYTES, _MAX_TOTAL_BYTES = 5000, 1_500_000, 50_000_000
_SECRET_PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("token_assignment", re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\b\s*[:=]\s*['\"]?([A-Za-z0-9_./+=-]{12,})")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
]
_RULES = [
    ("dynamic_code_execution", re.compile(r"\b(?:eval|exec)\s*\("), "Review untrusted input reaching dynamic code execution."),
    ("command_execution", re.compile(r"\b(?:subprocess\.(?:run|Popen|call)|os\.system|Runtime\.getRuntime\(\)\.exec)\s*\("), "Review command construction and argument handling."),
    ("sql_string_concatenation", re.compile(r"(?i)(?:execute|rawQuery)\s*\(\s*['\"].*(?:\+|%s|\.format\()"), "Review whether SQL is parameterized."),
    ("weak_tls_verification", re.compile(r"(?i)(?:verify\s*=\s*False|trustAllCerts|ALLOW_ALL_HOSTNAME_VERIFIER)"), "Review disabled TLS certificate or hostname verification."),
    ("debug_mode", re.compile(r"(?i)(?:debug\s*=\s*True|DEBUG\s*=\s*true)"), "Ensure debug mode is disabled in production."),
]

def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    try: path.chmod(0o600)
    except OSError: pass

def _read_document(path):
    suffix = path.suffix.lower()
    if suffix == ".docx":
        with zipfile.ZipFile(path) as archive: raw = archive.read("word/document.xml")
        root = ElementTree.fromstring(raw)
        return "\n".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages[:100])
        except ImportError:
            return "[PDF skipped: install pypdf for local PDF text extraction]"
    return path.read_text(encoding="utf-8", errors="replace")

def _redact(value):
    value = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/-]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(password|token|secret|api[_-]?key)(\s*[:=]\s*)['\"]?[^'\"\s,;]{8,}", r"\1\2[REDACTED]", value)
    return value[:1600]

def _key(item):
    raw = "|".join((item["path"], str(item["line"]), item["category"], item["snippet"]))
    return hashlib.sha256(raw.encode()).hexdigest()[:20]

def _persist(root, state):
    _atomic_json(root / ".bughunter-assessments" / state["id"] / "state.json", state)

def _scan(root, aid):
    findings, scanned, skipped, total = [], 0, 0, 0
    evidence = root / ".bughunter-assessments" / aid / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    for current, dirs, files in os.walk(root):
        if _STOP.is_set(): break
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".") and not (Path(current) / d).is_symlink()]
        for name in files:
            if _STOP.is_set(): break
            path = Path(current) / name
            if path.is_symlink() or (path.suffix.lower() not in (_TEXT_EXTS | _DOC_EXTS) and not path.name.lower().startswith(".env") and path.name.lower() not in ("dockerfile", "makefile")): continue
            try:
                size = path.stat().st_size
                if size > _MAX_FILE_BYTES or total + size > _MAX_TOTAL_BYTES:
                    skipped += 1
                    continue
                text = _read_document(path)
                total += size
                scanned += 1
                rel = path.relative_to(root).as_posix()
                for number, line in enumerate(text.splitlines(), 1):
                    for category, pattern, guidance in _RULES:
                        if pattern.search(line):
                            item = {"path": rel, "line": number, "category": category, "severity": "review", "status": "CANDIDATE_NOT_CONFIRMED", "snippet": _redact(line.strip()), "guidance": guidance}
                            item["deduplication_key"] = _key(item)
                            findings.append(item)
                    for category, pattern in _SECRET_PATTERNS:
                        if pattern.search(line):
                            item = {"path": rel, "line": number, "category": "possible_" + category, "severity": "sensitive", "status": "REDACTED_CANDIDATE", "snippet": "[POTENTIAL SECRET REDACTED]", "guidance": "Confirm privately and rotate if exposed; never copy the value into a report."}
                            item["deduplication_key"] = _key(item)
                            findings.append(item)
                    if len(findings) >= 1000: break
            except (OSError, UnicodeError, zipfile.BadZipFile, KeyError, ElementTree.ParseError):
                skipped += 1
            if scanned >= _MAX_FILES or len(findings) >= 1000: break
        if scanned >= _MAX_FILES or len(findings) >= 1000: break
    unique = {}
    for item in findings: unique.setdefault(item["deduplication_key"], item)
    findings = list(unique.values())
    _atomic_json(evidence / "findings.json", findings)
    return {"files_scanned": scanned, "files_skipped": skipped, "bytes_scanned": total, "findings": findings}

def _simulate(findings):
    cats = {x["category"] for x in findings}
    paths = []
    candidates = [
        ({"command_execution", "dynamic_code_execution"}, "Untrusted input to code or command execution", "Potential execution with application privileges if an attacker-controlled input path exists.", "Reasoning only; no code or payload executed."),
        ({"sql_string_concatenation"}, "Input to dynamically assembled SQL", "Potential query manipulation if input is attacker-controlled and not parameterized.", "Synthetic scenario only; no database connection or query executed."),
        ({"weak_tls_verification"}, "TLS peer verification disabled", "Potential interception exposure if used across a production trust boundary.", "Configuration review only; no network traffic generated."),
    ]
    for required, name, impact, validation in candidates:
        if cats & required: paths.append({"name": name, "possible_impact": impact, "validation": validation})
    return {"mode": "offline_synthetic", "network_requests": 0, "executed_target_code": False, "paths": paths}

def _worker(root, state):
    global _JOB
    try:
        state.update(status="running", phase="local_scan")
        _persist(root, state)
        result = _scan(root, state["id"])
        state["summary"] = {k: v for k, v in result.items() if k != "findings"}
        state["findings"] = result["findings"]
        if _STOP.is_set():
            state.update(status="stopped", phase="stopped", stop_reason="Emergency stop requested.")
            _persist(root, state)
            return
        state.update(phase="offline_simulation")
        _persist(root, state)
        state["simulation"] = _simulate(result["findings"])
        if _STOP.is_set():
            state.update(status="stopped", phase="stopped", stop_reason="Emergency stop requested.")
            _persist(root, state)
            return
        state.update(phase="report")
        _persist(root, state)
        report_dir = root / ".bughunter-assessments" / state["id"]
        lines = ["# BugHunterAI Local Assessment Draft", "", "> Draft only. Heuristic candidates are not confirmed vulnerabilities.", "> Local-only run: no target was contacted and no target code was executed.", "", "## Summary", "", "- Files scanned: " + str(result["files_scanned"]), "- Files skipped: " + str(result["files_skipped"]), "- Candidate findings: " + str(len(result["findings"])), "- Network requests: 0", "", "## Findings", ""]
        if not result["findings"]: lines.append("No candidate patterns detected by enabled checks.")
        for item in result["findings"]:
            lines.extend(["### " + item["category"], "", "- Location: " + item["path"] + ":" + str(item["line"]), "- Status: " + item["status"], "- Evidence: " + item["snippet"], "- Review: " + item["guidance"], ""])
        lines.extend(["## Offline impact simulation", ""])
        if not state["simulation"]["paths"]: lines.append("No synthetic impact paths generated from these candidates.")
        for item in state["simulation"]["paths"]:
            lines.extend(["### " + item["name"], "", item["possible_impact"], "", item["validation"], ""])
        lines.extend(["## Authorization boundary", "", "No live-target testing was performed. A separate current-policy and exact-scope review is mandatory before any network activity."])
        report = report_dir / "report-draft.md"
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try: report.chmod(0o600)
        except OSError: pass
        state.update(status="completed", phase="completed", report=str(report), finished_at=int(time.time()))
        _persist(root, state)
    except Exception as exc:
        state.update(status="failed", phase="failed", error=(type(exc).__name__ + ": " + str(exc))[:400])
        try: _persist(root, state)
        except Exception: pass
    finally:
        with _LOCK: _JOB = dict(state)

def start(root_path=None, program=None):
    global _JOB, _THREAD
    root = Path(root_path or Path.cwd()).expanduser().resolve()
    if not root.is_dir(): raise ValueError("assessment root must be an existing local directory")
    with _LOCK:
        if _JOB.get("status") in ("running", "queued"): return False, dict(_JOB)
        _STOP.clear()
        state = {"id": uuid.uuid4().hex, "status": "queued", "phase": "queued", "created_at": int(time.time()), "root": str(root), "mode": "local_only", "program_label": str(program or "")[:120], "policy_gate": "NOT_VERIFIED", "network_testing": "BLOCKED", "report_submission": "MANUAL_ONLY", "stop_reason": ""}
        _JOB = dict(state)
        _persist(root, state)
        _THREAD = threading.Thread(target=_worker, args=(root, state), name="cbh-assessment", daemon=True)
        _THREAD.start()
        return True, dict(state)

def status():
    with _LOCK: return dict(_JOB)

def stop():
    global _JOB
    with _LOCK:
        if _JOB.get("status") not in ("running", "queued"): return False, dict(_JOB)
        _STOP.set()
        _JOB = {**_JOB, "stop_requested": True}
        return True, dict(_JOB)

def history(root_path=None, limit=20):
    root = Path(root_path or Path.cwd()).expanduser().resolve()
    base = root / ".bughunter-assessments"
    output = []
    if base.is_dir() and not base.is_symlink():
        paths = sorted(base.glob("*/state.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in paths[:max(1, min(int(limit), 100))]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                output.append({k: data.get(k) for k in ("id", "status", "phase", "created_at", "finished_at", "summary", "report", "stop_reason", "error")})
            except (OSError, ValueError): pass
    return output
