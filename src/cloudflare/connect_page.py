"""The /connect onboarding page: server-rendered HTML, no I/O, so the
escaping and status handling are unit-testable."""

from html import escape

# Query-string status codes -> (message, is_error). A fixed table, so
# nothing from the URL is ever reflected into the page.
STATUS_MESSAGES = {
    "saved": ("Settings saved.", False),
    "strava_connected": ("Strava connected.", False),
    "bad_key": ("Liftosaur rejected that API key. Check it and try again.", True),
    "bad_timezone": ("That isn't a valid timezone name, e.g. Europe/London.", True),
    "strava_denied": ("Strava authorization was cancelled.", True),
    "strava_scope": (
        (
            "Strava needs permission to upload activities. Connect again and "
            "leave the activity checkboxes ticked."
        ),
        True,
    ),
    "strava_failed": ("Connecting to Strava failed. Please try again.", True),
    "bad_state": ("That Strava link expired. Please try connecting again.", True),
}

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Liftosaur to Strava</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 34rem; margin: 2rem auto;
         padding: 0 1rem; }}
  fieldset {{ margin: 1.5rem 0; padding: 1rem; }}
  label {{ display: block; margin: .5rem 0 .25rem; font-weight: 600; }}
  input {{ width: 100%; box-sizing: border-box; padding: .5rem; font: inherit; }}
  button, .button {{ margin-top: 1rem; padding: .5rem 1rem; font: inherit; }}
  .ok {{ color: #1a7f37; }} .err {{ color: #cf222e; }}
  .status {{ font-weight: 600; }}
</style>
</head>
<body>
<h1>Liftosaur to Strava</h1>
<p>Signed in as <strong>{email}</strong>.</p>
{banner}
<form method="post" action="/connect/settings">
<fieldset>
<legend>Liftosaur</legend>
<p class="status {liftosaur_class}">{liftosaur_status}</p>
<label for="key">API key (Liftosaur app: Settings &rarr; API Keys, needs Premium)</label>
<input id="key" name="liftosaur_api_key" type="password" autocomplete="off"
       placeholder="Leave blank to keep the current key">
<label for="tz">Timezone</label>
<input id="tz" name="timezone" value="{timezone}" placeholder="Europe/London" required>
<button type="submit">Save</button>
</fieldset>
</form>
<fieldset>
<legend>Strava</legend>
<p class="status {strava_class}">{strava_status}</p>
<a class="button" href="/connect/strava"><button type="button">{strava_button}</button></a>
</fieldset>
<script>
  var tz = document.getElementById("tz");
  if (!tz.value) {{
    try {{ tz.value = Intl.DateTimeFormat().resolvedOptions().timeZone; }} catch (e) {{}}
  }}
</script>
</body>
</html>
"""


def render_connect_page(
    email: str,
    liftosaur_set: bool,
    strava_connected: bool,
    timezone: str | None,
    status: str | None = None,
) -> str:
    banner = ""
    if status in STATUS_MESSAGES:
        message, is_error = STATUS_MESSAGES[status]
        banner = f'<p class="{"err" if is_error else "ok"}">{escape(message)}</p>'
    return _PAGE.format(
        email=escape(email),
        banner=banner,
        liftosaur_class="ok" if liftosaur_set else "err",
        liftosaur_status="API key saved." if liftosaur_set else "No API key yet.",
        timezone=escape(timezone or "", quote=True),
        strava_class="ok" if strava_connected else "err",
        strava_status="Connected." if strava_connected else "Not connected.",
        strava_button="Reconnect Strava" if strava_connected else "Connect Strava",
    )
