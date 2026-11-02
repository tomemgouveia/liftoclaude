class StravaUploadError(RuntimeError):
    """Strava processed the upload and reported an error (e.g. it is a
    duplicate of an existing activity)."""


class MissingCredentials(RuntimeError):
    """A required credential (Strava app keys, refresh token, Liftosaur
    API key) isn't configured."""
