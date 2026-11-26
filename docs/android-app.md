# BugHunter AI Android companion

The android-app directory contains a native Kotlin + Jetpack Compose Android application. The Python CLI and automation remain in Termux; the app is a local companion UI.

## First run

1. In Termux, enter the repository and start python -m cbh.api.
2. Copy the one-time API token printed by the service.
3. Open the Android app, paste the token, and connect.
4. Keep the Termux session running while using the app.

The local API stores its token outside the repository at ~/.config/claude-bughunter/api-token with restrictive file permissions. It binds only to loopback (127.0.0.1) and requires Authorization: Bearer token.

## Current app capabilities

- Native dashboard for saved bounty opportunities.
- Reads the local bounty income/expense ledger.
- Lists finding, evidence, and report-draft files.
- Shows the scope file preview and approved-target configuration summaries.
- Shows whether Telegram notifications are configured.
- Does not expose recon, exploitation, or report-submission controls through the mobile API.

## Build

GitHub Actions builds a debug APK on pushes that touch android-app and supports manual workflow dispatch. Android Studio can also open android-app directly.
