import logging
from urllib.parse import parse_qs, urlparse

import requests
from workers import Request, Response

from liftostrava.liftosaur.client import LiftosaurClient
from liftostrava_worker.context import AppContext
from liftostrava_worker.routes.history_range import (
    HistoryRangeError,
    parse_history_range,
)
from liftostrava_worker.routes.workout_json import workout_json
from liftostrava_worker.storage.models import AccessIDKey

logger = logging.getLogger(__name__)


async def handle_history(
    id_key: AccessIDKey, request: Request, app: AppContext
) -> Response:
    user = await app.repo.get_user(id_key)
    if user is None:
        return Response.from_json({"error": "User not found"}, status=404)

    if not user.has_credentials or not user.liftosaur_api_key:
        return Response.from_json(
            {"error": "User does not have credentials"}, status=404
        )
    try:
        start, end = parse_history_range(
            parse_qs(urlparse(request.url).query), user.timezone
        )
    except HistoryRangeError as e:
        return Response.from_json({"error": str(e)}, status=400)

    try:
        workout_history = LiftosaurClient(user.liftosaur_api_key).list_history(
            start_date=start, end_date=end
        )
    except requests.RequestException:
        logger.exception("Listing Liftosaur history failed")
        return Response.from_json({"error": "Could not reach Liftosaur"}, status=502)
    # The legacy root path keeps its original compact shape for
    # Shortcuts; /api/workouts is the full shape unless ?brief=1.
    query = parse_qs(urlparse(request.url).query)
    brief = urlparse(request.url).path.rstrip("/") == "" or query.get("brief") == ["1"]
    return Response.from_json(
        [
            workout_json(record, brief)
            for record in sorted(
                workout_history, key=lambda w: w.workout.start_time, reverse=True
            )
        ]
    )
