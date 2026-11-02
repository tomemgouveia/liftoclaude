"""Worker entrypoint: authenticate via Cloudflare Access, then dispatch to
the route handlers in routes/. src/cloudflare_worker.py re-exports
`Default` as the module wrangler.toml's `main` points at."""

import logging
from urllib.parse import urlparse

from workers import Request, Response, WorkerEntrypoint

from liftostrava_worker.context import AppContext
from liftostrava_worker.routes.common import origin
from liftostrava_worker.routes.connect import handle_connect
from liftostrava_worker.routes.history import handle_history
from liftostrava_worker.routes.sync import handle_sync
from liftostrava_worker.security.access_jwt import process_jwt
from liftostrava_worker.storage.models import AccessIDKey

logger = logging.getLogger(__name__)


class Default(WorkerEntrypoint):
    async def fetch(self, request: Request) -> Response:
        id_key = await self.get_access_id_key(request)
        if id_key is None:
            return Response("Cloudflare Access authentication required", status=401)

        app = AppContext(self.env)
        path = urlparse(request.url).path.rstrip("/") or "/"
        if path.startswith("/connect") or path == "/api/settings":
            return await handle_connect(request, id_key, path, app)

        match (request.method, path):
            case ("POST", "/" | "/api/sync"):
                # Browsers always send Origin on POSTs; reject cross-site
                # ones. Service-token clients send none.
                request_origin = request.headers.get("origin")
                if request_origin is not None and request_origin != origin(request.url):
                    return Response("Forbidden", status=403)
                return await handle_sync(request, id_key, app)
            case ("GET", "/api/workouts"):
                return await handle_history(id_key, request, app)
            case ("GET", "/"):
                # Browsers get the app; API clients keep the JSON list.
                if "text/html" not in (request.headers.get("accept") or ""):
                    return await handle_history(id_key, request, app)
                return await self.env.ASSETS.fetch(request)
            case ("GET" | "HEAD", _):
                # Built frontend files (JS, CSS, icons).
                return await self.env.ASSETS.fetch(request)
            case _:
                return Response("Method Not Allowed", status=405)

    async def get_access_id_key(self, request: Request) -> AccessIDKey | None:
        assertion = request.headers.get("cf-access-jwt-assertion")
        if assertion:
            team_domain = self.env.CF_ACCESS_TEAM_DOMAIN
            expected_audience = self.env.CF_ACCESS_AUD
            if not isinstance(team_domain, str) or not isinstance(
                expected_audience, str
            ):
                logger.error(
                    "Cloudflare Access team domain or audience is not configured"
                )
                return None
            return await process_jwt(assertion, team_domain, expected_audience)

        access = self.ctx.access
        if access is None:
            logger.warning("Cloudflare Access identity and JWT assertion are missing")
            return None
        identity = await access.getIdentity()
        email = identity.email if identity is not None else None
        if not isinstance(email, str) or not email.strip():
            logger.warning("Cloudflare Access identity did not contain an email")
            return None
        return AccessIDKey(email=email.strip().lower())
