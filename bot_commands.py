"""
Telegram Bot Command Handler — polling entrypoint.

Polls Telegram for new messages and dispatches them via bot_core. Runs every
15 minutes via GitHub Actions. All command logic lives in bot_core.py (shared
with the Vercel webhook) — this file only owns the poll loop + offset tracking.

NOTE: Telegram returns HTTP 409 for getUpdates while a webhook is configured.
If a webhook is set (the preferred, instant path), this poller self-disables so
the two paths never conflict and no Actions minutes are wasted.

That self-disabling is also a trap: a webhook that is registered but REJECTING
updates stops commands dead, and the poller steps aside rather than covering
for it. So before skipping, this checks the webhook is actually delivering and
alerts the owner if not. gold_monitor.py runs the same check, because this
workflow can itself be disabled — as it was for three months.
"""

import bot_core
import storage


def process_commands():
    """Poll Telegram for new commands and process them."""
    bot_state = storage.load_bot_state()

    if bot_core.webhook_is_configured():
        # Stepping aside is only safe if the webhook is actually working.
        if bot_core.warn_owner_if_webhook_broken(bot_state):
            storage.save_bot_state(bot_state)
        print("[bot] Webhook is configured — skipping poll to avoid 409 conflict")
        return

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
