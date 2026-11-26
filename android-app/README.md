# BugHunter AI — Android companion

Native Kotlin + Jetpack Compose companion for the Python engine in Termux. This is an Android application, not a browser dashboard.

## Build an APK

Open this folder in Android Studio and build the app with the assembleDebug Gradle task, or use the GitHub Actions workflow named Android APK. The debug APK is written to app/build/outputs/apk/debug/app-debug.apk.

## Connect to Termux

From the repository root in Termux, start:

    python -m cbh.api

At first startup it creates a random API token under ~/.config/claude-bughunter/api-token and prints it once. Keep the Termux session running. Open BugHunter AI, paste the token, and tap Connect / Refresh.

The service binds only to 127.0.0.1:8765; it refuses non-loopback bind addresses. The Android app calls only that loopback address. The API requires a bearer token and exposes opportunity and ledger views. No scan or exploit endpoint is exposed.

Run the API tests with:

    python -m unittest discover -s tests -p test_api.py -v
