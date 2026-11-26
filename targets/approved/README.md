# Approved target configurations

Only place targets here after you have read the current program policy and confirmed the asset is eligible for testing and bounty submission.

Create one JSON file per program, for example targets/approved/acme.json:

    {
      "name": "Acme",
      "target": "app.example.com",
      "scope_file": "../../scopes/acme.md",
      "seeds": [
        "https://app.example.com/"
      ]
    }

- target is the approved hostname or URL used as the engagement identity.
- scope_file is relative to this JSON file and must point to the imported, reviewed scope markdown.
- seeds is optional; if omitted, the target is used as the only seed. Every seed is checked against the scope before the engine starts.
- Do not put credentials, session cookies, API keys, or other secrets in this file.
- Do not copy wildcard or broad program scope into seeds. Add only the exact hostnames you intend to assess.

Import a public program scope, then review the generated file and its manual-review section:

    python -m cbh.cli scope import h1:PROGRAM_HANDLE -o scopes/acme.md

Run the full workflow from Termux:

    python -m cbh.cli engage targets/approved/acme.json

The engagement is read-only by default. The offline pipeline wiring test is:

    python -m cbh.cli engage targets/approved/acme.json --mock

The Android app can start the same approved config using its Start read-only hunt control. Reports are drafts only; submission is always a separate, human-approved action.
