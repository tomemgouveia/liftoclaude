"""Self-service onboarding: a signed-in (email) user saves their Liftosaur
key and timezone and connects Strava via OAuth. The UI is the React app;
this serves it plus the settings API and the OAuth redirects."""

import logging
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from workers import Request, Response

from liftostrava.liftosaur.client import LiftosaurClient
from liftostrava_worker.context import AppContext
from liftostrava_worker.crypto import STATE_LABEL
from liftostrava_worker.http import origin
from liftostrava_worker.models import AccessIDKey, User
from liftostrava_worker.oauth_state import sign_state, verify_state

logger = logging.getLogger(__name__)


async def handle_connect(
    request: Request, id_key: AccessIDKey, path: str, app: AppContext
) -> Response:
    if id_key.email is None:
        return Response("Sign in with your email to use this page", status=403)
    base = origin(request.url)
    try:
        repo = app.repo
        match (request.method, path):
            case ("GET", "/connect"):
                return await app.env.ASSETS.fetch(request)
            case ("GET", "/api/settings"):
                user = await repo.get_or_create_user(id_key.email)
                return Response.from_json(
                    {
                        "email": user.email,
                        "liftosaur_set": bool(user.liftosaur_api_key),
                        "strava_connected": bool(user.strava_refresh_token),
                        "timezone": user.timezone,
                    }
                )
            case ("POST", "/api/settings"):
                user = await repo.get_or_create_user(id_key.email)
                return await handle_settings(request, user, base, app)
            case ("GET", "/connect/strava"):
                user = await repo.get_or_create_user(id_key.email)
                return handle_strava_start(user, base, app)
            case ("GET", "/connect/strava/callback"):
                user = await repo.get_or_create_user(id_key.email)
                return await handle_strava_callback(request, user, base, app)
            case _:
                return Response("Not Found", status=404)
    except Exception:
        logger.exception("Connect flow failed")
        return Response("Something went wrong", status=500)


async def handle_settings(
    request: Request, user: User, base: str, app: AppContext
) -> Response:
    """Saves settings from JSON. Answers {"status": <code>} where the
    code is one the frontend maps to a message (saved, bad_key,
    bad_timezone)."""
    # Browsers always send Origin on POSTs; reject anything else
    # so another site can't submit this form with the user's session.
    if request.headers.get("origin") != base:
        return Response("Forbidden", status=403)
    try:
        body = await request.json()
    except Exception:
        return Response("Request body must be valid JSON", status=400)
    if not isinstance(body, dict):
        return Response("Request body must be a JSON object", status=400)
    liftosaur_api_key = str(body.get("liftosaur_api_key") or "").strip()
    timezone = str(body.get("timezone") or "").strip()

    def result(status: str, http: int = 200) -> Response:
        return Response.from_json({"status": status}, status=http)

    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return result("bad_timezone", 422)
    if liftosaur_api_key and not LiftosaurClient(liftosaur_api_key).health_check():
        return result("bad_key", 422)

    await app.repo.save_settings(user.user_id, timezone, liftosaur_api_key)
    return result("saved")


def handle_strava_start(user: User, base: str, app: AppContext) -> Response:
    client_id = app.env.STRAVA_CLIENT_ID
    if not isinstance(client_id, str):
        raise TypeError("STRAVA_CLIENT_ID is not configured")
    state = sign_state(user.user_id, app.secret_key(STATE_LABEL))
    return Response.redirect(
        app.strava_oauth.authorize_url(f"{base}/connect/strava/callback", state)
    )


async def handle_strava_callback(
    request: Request, user: User, base: str, app: AppContext
) -> Response:
    params = parse_qs(urlparse(request.url).query)

    def back(status: str) -> Response:
        return Response.redirect(f"{base}/connect?status={status}", 303)

    if "error" in params:
        return back("strava_denied")
    state_user = verify_state(params.get("state", [""])[0], app.secret_key(STATE_LABEL))
    if state_user != user.user_id:
        return back("bad_state")
    code = params.get("code", [""])[0]
    if not code:
        return back("strava_failed")
    if "activity:write" not in params.get("scope", [""])[0].split(","):
        return back("strava_scope")

    try:
        authorization = app.strava_oauth.exchange_code(code)
    except (requests.RequestException, KeyError):
        logger.exception("Strava token exchange failed")
        return back("strava_failed")
    await app.repo.save_strava_tokens(user.user_id, authorization.tokens)
    return back("strava_connected")
