"""
Telegram Bot Command Handler — polling entrypoint.

Polls Telegram for new messages and dispatches them via bot_core. Runs every
5 minutes via GitHub Actions. All command logic lives in bot_core.py (shared
with the Vercel webhook) — this file only owns the poll loop + offset tracking.

NOTE: Telegram returns HTTP 409 for getUpdates while a webhook is configured.
If a webhook is set (the preferred, instant path), this poller self-disables so
the two paths never conflict and no Actions minutes are wasted.
"""

import storage
import bot_core


def process_commands():
    """Poll Telegram for new commands and process them."""
    if bot_core.webhook_is_configured():
        print("[bot] Webhook is configured — skipping poll to avoid 409 conflict")
        return

    bot_state = storage.load_bot_state()
    offset = bot_state.get("update_offset", 0)

    updates = bot_core.get_updates(offset)
    if not updates:
        print("[bot] No new messages")
        return

    for update in updates:
        bot_core.dispatch_update(update)
        offset = update["update_id"] + 1

    bot_state["update_offset"] = offset
    storage.save_bot_state(bot_state)
    print(f"[bot] Processed {len(updates)} updates, new offset={offset}")


if __name__ == "__main__":
    process_commands()
