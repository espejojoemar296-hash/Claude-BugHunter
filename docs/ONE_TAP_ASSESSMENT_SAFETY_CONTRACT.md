# One-Tap Automated Assessment — Safety and Acceptance Contract

Status: required design contract; implementation is not complete until every acceptance test below passes.

## Product outcome

A user selects a bounty program, reviews the imported current policy and scope, and starts one orchestrated assessment. The backend runs all automatically permitted local and synthetic work, persists progress and artifacts, and prepares a report draft for human review. One tap never means unrestricted target testing.

## Required workflow

1. **Select program and import policy**
   - Import the program's published policy, in-scope assets, explicit exclusions, asset types, bounty eligibility, prohibited methods, rate limits, automation rules, disclosure requirements, and policy URL/version/timestamp.
   - Record source and retrieval time. Mark cached or stale policy as unverified.
   - Show the complete imported scope for review. Ambiguous assets remain unresolved; never promote them to in-scope automatically.
2. **Authorization gate**
   - Require a current policy snapshot and explicit user confirmation that the selected program and testing purpose are authorized.
   - Revalidate policy freshness and scope immediately before any network activity and periodically during long jobs.
   - Fail closed if the policy cannot be retrieved, parsed, or reconciled, or if authorization expires or changes.
   - Never infer authorization for a subdomain, IP, endpoint, API, mobile app, or third-party service from a parent domain.
3. **Local source/document scan**
   - Scan only user-provided or locally accessible repositories and documents.
   - Use static analysis, secret-pattern detection with redacted output, dependency/configuration checks, and document inspection.
   - Do not upload private source or documents to external services without a separate explicit opt-in.
4. **Correlate and deduplicate**
   - Normalize findings, link source locations and evidence, identify duplicates, and preserve provenance.
   - Keep candidate, reviewed, and verified states distinct. Heuristic candidates are never presented as confirmed vulnerabilities.
5. **Automatic safe verification**
   - Run static checks and deterministic synthetic-fixture tests automatically.
   - Use synthetic data only. Never probe production accounts, access real user data, or perform state-changing operations.
   - Record exact test, inputs, outputs, limits, and reason for any skipped test.
6. **Attack-path and impact simulation**
   - Build graph-based attack paths and explain possible impact using synthetic assets and data.
   - Simulations must be offline by default and must not send exploit payloads to real targets.
7. **Behavioral testing gate**
   - Disabled by default. Enable only for an explicitly authorized asset and a separately hardened sandbox with resource limits, synthetic data, network egress allowlists, audit logging, and a kill switch.
   - If sandbox guarantees cannot be demonstrated, block the test. Do not fall back to testing the live target.
8. **Save and report**
   - Persist job state, logs, findings, evidence, policy snapshot, scope decisions, and report drafts atomically.
   - Redact secrets and unnecessary personal data from logs, screenshots, notifications, and reports.
   - Prepare a professional platform-specific submission draft; never submit it automatically.
9. **Resume, notify, compare**
   - Recover interrupted jobs from persisted checkpoints without repeating completed state-changing work.
   - Deduplicate repeated findings across runs and show changes between assessment versions.
   - Send Telegram notifications only after applying the same redaction policy as local logs.

## Safety state model

- **GREEN — permitted:** local static analysis, offline document inspection, deterministic synthetic tests, and offline attack-path simulation.
- **YELLOW — review required:** unclear policy language, ambiguous assets, stale policy, prohibited-method uncertainty, or behavioral tests requiring separate authorization.
- **RED — blocked:** out-of-scope assets, explicit exclusions, prohibited techniques, expired/withdrawn authorization, unsafe sandbox configuration, destructive behavior, credential harvesting, persistence, denial of service, data theft, or uncontrolled network activity.

The backend—not the Android UI alone—must enforce every state. A UI label is never a security boundary.

## Emergency stop

Provide a server-side stop flag checked between every phase and before every network request. Stop immediately on user request, authorization/policy change, scope mismatch, rate-limit breach, resource limit, unexpected redirect/host change, sandbox escape signal, or safety uncertainty. Persist the stop reason and partial results.

## Minimum persisted assessment record

- Unique assessment ID; selected program/platform/handle
- Policy URL, content hash, retrieval timestamp, freshness status
- Reviewed scope snapshot, inclusions, exclusions, unresolved assets
- Authorization confirmation timestamp and user action
- Phase state, checkpoints, timestamps, cancellation/stop reason
- Tool/version/configuration and resource limits
- Findings with provenance, confidence, severity rationale, deduplication key
- Verification method and outcome (candidate / supported / not reproduced / blocked / not tested)
- Evidence references with redaction metadata
- Report draft path and manual-submission status

## Required acceptance tests

1. Out-of-scope host, sibling subdomain, excluded path, IP, redirect destination, and ambiguous asset are blocked before network activity.
2. Stale, missing, changed, or unparsable policy blocks network phases.
3. Prohibited method and rate-limit instructions are enforced server-side.
4. One-tap starts local static and synthetic phases without per-finding approval.
5. No production exploit payload is sent by static verification or attack simulation.
6. Behavioral phase cannot start without a validated sandbox and separate authorization.
7. Emergency stop halts queued and running phases and prevents subsequent requests.
8. App/process restart resumes from persisted checkpoints without losing evidence or duplicating completed work.
9. Secrets and personal data are redacted from logs, reports, and Telegram messages.
10. Reports remain drafts and require a deliberate user action to submit.
11. Duplicate findings across repeated scans are linked, not silently duplicated.
12. All safety decisions are tested at the backend/API layer, not only in UI tests.

## Non-goals

- No guarantee of bounty acceptance, earnings, or legal immunity.
- No automatic vulnerability submission.
- No stealth, anonymity features intended to evade platform identity checks, or bypass of program controls.
- No destructive exploitation, credential theft, persistence, denial of service, or access to real user data.
