# BugHunter AI — Android companion

Native Kotlin + Jetpack Compose companion for the Python engine in Termux.

## Build an APK

Open this folder in Android Studio and build the app with the assembleDebug Gradle task, or use the GitHub Actions workflow named Android APK. The debug APK is written to app/build/outputs/apk/debug/app-debug.apk.

## Connect to Termux

From the repository root in Termux, start:

    python -m cbh.api

At first startup it creates a random API token under ~/.config/claude-bughunter/api-token and prints it once. Keep the Termux session running. Open BugHunter AI, paste the token, and tap Connect / Refresh.

The service binds only to 127.0.0.1:8765 and requires a bearer token. It exposes bounty opportunities, the income ledger, workspace file names, scope preview, approved-target summaries, Telegram status, and engagement status.

## Run an approved engagement

1. Import the program's published scope and read its rules:
   
       python -m cbh.cli scope import h1:PROGRAM_HANDLE -o scopes/PROGRAM_HANDLE.md

2. Create a JSON file directly inside targets/approved/ (see targets/approved/README.md). Set target, scope_file, and optionally seeds. Do not add assets unless the program explicitly authorizes them.
3. In the Android app, tap Connect / Refresh, review the displayed scope and target, then tap **Start read-only hunt** for that approved target.
4. Refresh to view the engagement status. The report and run artifacts are stored under ~/.bughunter-engagements/ on the Termux device.

The engagement pipeline runs recon, surface ranking, mapping, AI-assisted hunting, adversarial validation, a consolidated report, and HackerOne/Bugcrowd/Intigriti submission drafts. It is read-only by default. Drafts require your review and manual submission; the app does not automatically submit reports or claim bounty rewards.

AI-assisted hunting requires the Claude Code CLI to be installed and authenticated in the same Termux environment. If it is missing, the engagement fails before sending target requests and the status explains the missing dependency. The offline test command does not need Claude Code and never contacts a target:

    python -m cbh.cli engage targets/approved/example.json --mock

Configure Telegram in Termux with cbh telegram-setup. Run opportunity discovery separately with cbh autopilot.
