"""
Vercel Serverless Function — Telegram Webhook Handler.

Receives POST updates from Telegram and replies instantly. All command logic
lives in bot_core.py (shared with the polling entrypoint); this file only owns
the HTTP plumbing + webhook-secret verification.
"""

import hmac
import json
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler

# Make the repo-root modules importable from within api/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytz

import bot_core

BANGKOK_TZ = pytz.timezone("Asia/Bangkok")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            update = json.loads(body)
        except Exception as e:
            print(f"[webhook] Parse error: {e}")
            self.send_response(400)
            self.end_headers()
            return

        # Verify Telegram's secret token — REQUIRED, and fail closed when it is
        # not configured. The owner check downstream trusts message.chat.id
        # straight out of this payload, so an unauthenticated endpoint lets
        # anyone who knows the URL forge the owner's chat id and run
        # /delete, /sold or /setthreshold against their portfolio.
        if not WEBHOOK_SECRET:
            print("[webhook] WEBHOOK_SECRET is not set — refusing update. "
                  "Set it in the environment and re-run setup_webhook.py.")
            self.send_response(403)
            self.end_headers()
            return
        if not hmac.compare_digest(
            self.headers.get("X-Telegram-Bot-Api-Secret-Token", ""), WEBHOOK_SECRET
        ):
            print("[webhook] Invalid secret token")
            self.send_response(403)
            self.end_headers()
            return

        # Respond 200 to Telegram immediately, then process.
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

        try:
            bot_core.dispatch_update(update)
        except Exception as e:
            print(f"[webhook] Dispatch error: {e}")

    def do_GET(self):
        """Health check endpoint."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ok",
            "service": "Gold Monitor Telegram Webhook",
            "timestamp": datetime.now(BANGKOK_TZ).isoformat(),
        }).encode())

    def log_message(self, format, *args):
        """Suppress default HTTP logging."""
        pass
