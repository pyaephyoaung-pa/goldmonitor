"""Put a /backup file back into the Gist.

    GIST_GITHUB_TOKEN=... GIST_ID=... python restore_backup.py goldmonitor-backup-2026-11-01.json
        shows what would change, and writes nothing

    GIST_GITHUB_TOKEN=... GIST_ID=... python restore_backup.py FILE --apply
        writes the backed-up files back

Only the files in the backup are written. The rest of the Gist — model data,
which the 3am retrain rebuilds, and the day state — is left as it is.
"""

import json
import sys

import requests

import storage


def _size(obj) -> str:
    if isinstance(obj, list):
        return f"{len(obj)} items"
    if isinstance(obj, dict):
        return f"{len(obj)} keys"
    return "missing" if obj is None else type(obj).__name__


def restore(path: str, apply: bool = False) -> int:
    with open(path, encoding="utf-8") as f:
        backup = json.load(f)
    if backup.get("format") != storage.BACKUP_FORMAT or not isinstance(backup.get("files"), dict):
        print(f"{path} is not a Gold Monitor backup file")
        return 2
    if not storage.GITHUB_TOKEN or not storage.GIST_ID:
        print("Set GIST_GITHUB_TOKEN and GIST_ID first")
        return 2

    files = {name: data for name, data in backup["files"].items()
             if name in storage.BACKUP_FILES and data is not None}
    print(f"Backup taken {backup.get('created')}:")
    for name in storage.BACKUP_FILES:
        current = storage._read_file(name)
        print(f"  {name}: now {_size(current)} -> backup {_size(files.get(name))}")

        # Never move the Telegram update offset BACKWARDS. The poller would
        # fetch the last day's updates again and replay them — a /bought
        # twice is a ledger entry twice.
        if name == storage.BOT_STATE_FILE and isinstance(files.get(name), dict) \
                and isinstance(current, dict):
            files[name] = dict(files[name], update_offset=max(
                current.get("update_offset") or 0, files[name].get("update_offset") or 0))

    if not apply:
        print("\nNothing written. Run again with --apply to restore.")
        return 0
    r = requests.patch(
        f"https://api.github.com/gists/{storage.GIST_ID}",
        headers=storage.HEADERS, timeout=30,
        json={"files": {name: {"content": json.dumps(data, indent=2)}
                        for name, data in files.items()}},
    )
    r.raise_for_status()
    print(f"\nRestored: {', '.join(files)}")
    return 0


def main(argv: list) -> int:
    paths = [a for a in argv if not a.startswith("--")]
    if len(paths) != 1:
        print(__doc__)
        return 2
    return restore(paths[0], apply="--apply" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
