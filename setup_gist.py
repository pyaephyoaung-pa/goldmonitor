"""
One-time setup script: Creates the GitHub Gist for data storage.
Run locally: GIST_GITHUB_TOKEN=ghp_xxx python setup_gist.py
Then add the printed GIST_ID to your GitHub repo secrets.
"""

import os
import storage

def main():
    token = os.environ.get("GIST_GITHUB_TOKEN", "")
    if not token:
        print("❌ Set GIST_GITHUB_TOKEN environment variable first!")
        print("   Get a token at: https://github.com/settings/tokens")
        print("   Required scope: 'gist'")
        return

    print("Creating private GitHub Gist for Gold Monitor...")
    gist_id = storage.create_gist_if_needed()

    if gist_id:
        print(f"\n✅ Gist created successfully!")
        print(f"   GIST_ID = {gist_id}")
        print(f"   URL: https://gist.github.com/{gist_id}")
        print(f"\n👉 Add this as a secret in your GitHub repo:")
        print(f"   Repo → Settings → Secrets → New: GIST_ID = {gist_id}")
    else:
        print("❌ Failed to create Gist. Check your token permissions.")


if __name__ == "__main__":
    main()
