"""Validate the configured bot without printing secrets or message contents."""
import json
import os
import sys
from urllib.request import Request, urlopen


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN secret is missing or empty")
        return 1
    try:
        request = Request(
            "https://api.telegram.org/bot" + token + "/getMe",
            data=b"", method="POST",
        )
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except Exception:
        # Network exceptions may contain the token-bearing URL. Never print them.
        print("ERROR: Telegram token validation failed; no credentials were logged")
        return 1
    if not payload.get("ok"):
        print("ERROR: Telegram rejected the request")
        return 1
    username = payload.get("result", {}).get("username", "")
    if username.lower() != "donvalue_approval_bot":
        print("ERROR: The token belongs to a different bot")
        return 1
    print("OK: @donvalue_approval_bot token is valid")
    print("Owner chat pairing and approval publishing are not configured yet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
