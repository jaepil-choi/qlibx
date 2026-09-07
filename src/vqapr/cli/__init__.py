"""Command-line surface whose first user is an agent.

The entry point is `vqapr.cli.main:main`, not this package: `main` imports every command
through the package (`from vqapr.cli import check, ...`), so an `__init__` that imported `main`
was the one import cycle Python could not report (one-shape Step 7, record 162). This file
imports nothing.
"""
