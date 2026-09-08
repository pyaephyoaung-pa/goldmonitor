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

    # Commit the offset BEFORE dispatching anything, and only proceed if the
    # write actually landed.
    #
    # Commands here have side effects that must not repeat: /bought writes a
    # portfolio entry, /alert consumes a slot, /sold moves gold out. Saving the
    # offset afterwards meant any interruption — the 3-minute workflow timeout,
    # or a Gist write that failed and was swallowed — replayed the whole batch
    # on the next poll, logging the same purchase twice. At-most-once is the
    # right trade here: a dropped command is one the user can simply retype.
    new_offset = max(u.get("update_id", -1) for u in updates) + 1
    if new_offset > offset:
        bot_state["update_offset"] = new_offset
        if not storage.save_bot_state(bot_state):
            print("[bot] Could not persist update_offset — skipping this batch "
                  "rather than risking a replay of /bought, /sold or /alert")
            return

    for update in updates:
        bot_core.dispatch_update(update)

    print(f"[bot] Processed {len(updates)} updates, new offset={new_offset}")


if __name__ == "__main__":
    process_commands()
    # Same reasoning as gold_monitor: a rejected token cannot announce itself
    # over Telegram, so a failed run is the only signal left.
    if bot_core.auth_failed():
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN was rejected (401). Update it in the GitHub "
            "repo secrets and in Vercel."
        )
