"""Python package facade for the BugHunter engine modules.

The repository also contains a top-level engine.py compatibility entry point.
Making this directory an explicit package allows imports such as engine.scope
to resolve consistently in tests and integrations.
"""