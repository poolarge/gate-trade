#!/usr/bin/env python3
"""gate-admin — CLI for managing the Gate Trade bot.

Phase 3.3: Provides status, config reload, and two-step confirmation
of dangerous config changes.

Usage::

    gate-admin status                  # Show current config state
    gate-admin pending                 # List pending dangerous changes
    gate-admin confirm <token>         # Confirm a pending change batch
    gate-admin reject <token>          # Reject a pending change batch
"""

from __future__ import annotations

import argparse
import os
import sys

from gate_trade.config.guard import ConfigGuard
from gate_trade.config.watcher import ConfigWatcher

DEFAULT_CONFIG = os.environ.get("GATE_CONFIG", "config/default.yaml")


def _watcher() -> ConfigWatcher:
    path = DEFAULT_CONFIG
    # Prefer local.yaml if it exists
    local = "config/local.yaml"
    if os.path.exists(local):
        path = local
    return ConfigWatcher(path)


def cmd_status() -> int:
    w = _watcher()
    changes = w.poll()
    print(f"Watching: {w._path}")
    print(f"Hot-reload detected: {len([c for c in changes if c.level == 1])}")
    confirm = len([c for c in changes if c.level == 2])
    restart = len([c for c in changes if c.level == 3])
    if confirm:
        print(f"Pending confirmations: {confirm} change(s)")
        for c in changes:
            if c.level == 2:
                print(f"  {c.key}: {c.old_value} -> {c.new_value}")
    if restart:
        print(f"Restart required: {restart} change(s)")
        for c in changes:
            if c.level == 3:
                print(f"  {c.key}: changed (requires restart)")
    if not changes:
        print("No pending changes.")
    return 0


def cmd_pending() -> int:
    w = _watcher()
    w.poll()
    pending = w.pending_confirmations
    if not pending:
        print("No pending confirmations.")
        return 0

    print(f"{len(pending)} change(s) pending confirmation:")
    for c in pending:
        print(f"  [{c.key}]  {c.old_value!r} -> {c.new_value!r}  (L{c.level})")
    return 0


def cmd_confirm(token: str) -> int:
    guard = ConfigGuard()
    w = _watcher()
    w.poll()
    # Submit pending changes to guard
    pending = w.pending_confirmations
    if not pending:
        print("No pending confirmations to confirm.")
        return 1
    guard.submit(pending)
    result = guard.confirm(token)
    if result is None:
        print(f"Invalid token: {token}")
        return 1
    w.confirm()
    print(f"Confirmed {len(result)} change(s):")
    for c in result:
        print(f"  {c.key}: {c.old_value!r} -> {c.new_value!r}")
    return 0


def cmd_reject(token: str) -> int:
    guard = ConfigGuard()
    w = _watcher()
    w.poll()
    pending = w.pending_confirmations
    if not pending:
        print("No pending confirmations to reject.")
        return 1
    guard.submit(pending)
    if guard.reject(token):
        w.reject()
        print("Changes rejected.")
        return 0
    print(f"Invalid token: {token}")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="gate-admin — Gate Trade bot management CLI",
        prog="gate-admin",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    sub.add_parser("status", help="Show current config state")
    sub.add_parser("pending", help="List pending dangerous changes")

    conf = sub.add_parser("confirm", help="Confirm a pending change batch")
    conf.add_argument("token", help="Confirmation token")

    rej = sub.add_parser("reject", help="Reject a pending change batch")
    rej.add_argument("token", help="Confirmation token")

    args = parser.parse_args()

    if args.command == "status":
        sys.exit(cmd_status())
    elif args.command == "pending":
        sys.exit(cmd_pending())
    elif args.command == "confirm":
        sys.exit(cmd_confirm(args.token))
    elif args.command == "reject":
        sys.exit(cmd_reject(args.token))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
