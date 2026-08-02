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
    print(f"  Last error: {info.get('last_error_message', 'none')}")


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
