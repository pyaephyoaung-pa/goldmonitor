"""
One-time setup: Register Vercel URL as Telegram webhook.

Usage:
  python setup_webhook.py <VERCEL_URL>

Example:
  python setup_webhook.py https://goldmonitor-abc123.vercel.app

Requires env vars: TELEGRAM_BOT_TOKEN, WEBHOOK_SECRET (optional)
"""

import os
import sys
import time
from datetime import datetime

import requests

TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


def set_webhook(base_url: str):
    if not TG_BOT_TOKEN:
        print("ERROR: Set TELEGRAM_BOT_TOKEN environment variable first")
        sys.exit(1)

    webhook_url = f"{base_url.rstrip('/')}/api/webhook"
    secret = os.environ.get("WEBHOOK_SECRET", "")
    if not secret:
        # The handler fails closed without it, so registering the webhook now
        # would just produce silent 403s on every update.
        print("ERROR: WEBHOOK_SECRET is not set.")
        print("  The webhook rejects every update unless it is configured.")
        print("  Generate one:  python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
        print("  Then set it BOTH here and in the Vercel project environment.")
        sys.exit(1)

    payload = {
        "url": webhook_url,
        # callback_query is required for inline keyboard buttons to work
        "allowed_updates": ["message", "callback_query"],
        "secret_token": secret,
    }

    print(f"Setting webhook to: {webhook_url}")
    # Recorded BEFORE the call: any error newer than this is post-registration,
    # i.e. the fix did not work.
    registered_at = time.time()
    r = requests.post(
        f"https://api.telegram.org/bot{TG_BOT_TOKEN}/setWebhook",
        json=payload,
        timeout=10,
    )
    result = r.json()
    if result.get("ok"):
        print(f"Webhook set successfully!")
        print(f"Description: {result.get('description')}")
    else:
        print(f"ERROR: {result.get('description')}")
        sys.exit(1)

    # Verify
    r2 = requests.get(
        f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getWebhookInfo",
        timeout=10,
    )
    info = r2.json().get("result", {})
    print(f"\nWebhook info:")
    print(f"  URL: {info.get('url')}")
    print(f"  Pending updates: {info.get('pending_update_count', 0)}")
    _report_last_error(info, registered_at)


def _report_last_error(info: dict, registered_at: float):
    """Print the last webhook error WITH ITS AGE, and say what it means.

    Telegram keeps `last_error_message` long after the fault clears, so a bare
    print makes a stale error from hours ago look identical to one happening
    right now — which is actively misleading at exactly the moment you are
    trying to confirm a fix. Comparing its timestamp against the moment we
    re-registered separates the two.
    """
    error = info.get("last_error_message")
    if not error:
        print("  Last error: none — webhook is healthy ✅")
        return

    when = info.get("last_error_date")
    if not when:
        print(f"  Last error: {error} (no timestamp)")
        return

    age = time.time() - when
    stamp = datetime.fromtimestamp(when).strftime("%H:%M:%S")
    print(f"  Last error: {error}")
    print(f"              at {stamp}, {_ago(age)}")

    if when >= registered_at:
        print("\n  ❌ STILL FAILING — this error is NEWER than the registration"
              " you just made.")
        print("     Most likely: WEBHOOK_SECRET here does not match the value in")
        print("     the Vercel environment, or Vercel has not been redeployed")
        print("     since it was set. Both sides must hold the same string.")
    else:
        print("\n  ℹ️  This error PRE-DATES the registration you just made, so it")
        print("     may already be fixed. Telegram keeps the last error around")
        print("     even after it clears.")
        print("     Confirm: send your bot a message, wait ~10s, then re-run")
        print("     getWebhookInfo. If the error timestamp does NOT advance,")
        print("     the webhook is working.")


def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m ago"
    return f"{seconds // 86400}d ago"


def delete_webhook():
    """Remove webhook (switch back to polling mode)."""
    if not TG_BOT_TOKEN:
        print("ERROR: Set TELEGRAM_BOT_TOKEN environment variable first")
        sys.exit(1)

    r = requests.post(
        f"https://api.telegram.org/bot{TG_BOT_TOKEN}/deleteWebhook",
        json={"drop_pending_updates": False},
        timeout=10,
    )
    result = r.json()
    if result.get("ok"):
        print("Webhook removed. Bot is back in polling mode.")
    else:
        print(f"ERROR: {result.get('description')}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python setup_webhook.py <VERCEL_URL>     — Set webhook")
        print("  python setup_webhook.py --delete          — Remove webhook")
        sys.exit(1)

    if sys.argv[1] == "--delete":
        delete_webhook()
    else:
        set_webhook(sys.argv[1])
