"""
One-time Strava OAuth authorization.

Run this once to get a refresh token. It:
  1. Prints an authorization URL for you to open in a browser.
  2. Strava redirects you to a localhost URL (it doesn't need to
     actually load — just copy the `code` param from the address bar).
  3. Exchanges that code for a refresh token and writes it into .env.

Requires STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET to already be set in
.env (get these by creating an app at https://www.strava.com/settings/api).
"""

import os
import sys

import requests
from dotenv import load_dotenv

from liftostrava.cli import config
from liftostrava.cli.env_store import save_refresh_token
from liftostrava.strava.oauth import StravaOAuth, extract_code


def main():
    if not os.path.exists(config.ENV_PATH):
        print(
            "No .env found. Copy .env.example to .env and fill in "
            "STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET first."
        )
        sys.exit(1)

    load_dotenv(config.ENV_PATH)
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET are missing from .env.")
        sys.exit(1)

    oauth = StravaOAuth(client_id, client_secret)

    print("1. Open this URL in a browser and authorize the app:\n")
    print(f"   {oauth.authorize_url()}\n")
    print(
        "2. Strava will redirect to a localhost URL that won't load (that's expected)."
    )
    print(
        "   Copy the full redirected URL, or just the 'code=' value "
        "from it, and paste it below.\n"
    )

    raw = input("Paste the redirect URL or code: ").strip()
    code = extract_code(raw)

    try:
        authorization = oauth.exchange_code(code)
    except requests.HTTPError as e:
        resp = e.response
        # .response is typed Optional since HTTPError can in principle be
        # raised without one, but raise_for_status() (inside
        # exchange_code) always attaches the response it saw.
        assert resp is not None
        print(f"\nStrava rejected the token exchange (HTTP {resp.status_code}):")
        print(f"   {resp.text}\n")
        print("Common causes:")
        print(
            "  - The code was already used, or the page sat open too long "
            "(codes are single-use and expire quickly). Re-run this script "
            "to get a fresh authorization URL and code."
        )
        print(
            "  - STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET in .env don't match "
            "the app you authorized against at "
            "https://www.strava.com/settings/api."
        )
        print(
            "  - Only part of the code was pasted (make sure you copied the "
            "full 'code=' value, not truncated by the terminal)."
        )
        sys.exit(1)

    save_refresh_token(config.ENV_PATH, authorization.tokens.refresh_token)
    athlete = authorization.athlete
    print(
        f"\nAuthorized as {athlete.get('firstname', '')} {athlete.get('lastname', '')}."
    )
    print(
        "Refresh token saved to .env. You're set — run sync-to-strava "
        "whenever you want to sync a workout."
    )


if __name__ == "__main__":
    main()
