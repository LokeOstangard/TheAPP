# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

`google_health_client.py` and `google_calendar_client.py` are the first pieces of a larger planned system: Google Health API, Google Calendar, and Strava data are meant to feed a backend that normalizes them into a daily record (`daily_records.py`), which gets handed to the Claude API once a day to produce a training-readiness recommendation. `sync_daily.py` is the first real wiring between them: it pulls yesterday's health data and tomorrow's calendar and upserts both into `daily_records`, auth-tested and run live end-to-end. See Roadmap below for what's planned but not yet built (Strava, the actual Claude analysis call, deployment, delivery).

## Git workflow

Commit to git and push to the GitHub remote (`origin`, already configured) when a bigger change lands — a new module, a refactor across files, a new integration — not after every small edit within one. Small in-progress edits can stay uncommitted; don't let a full session's worth of new files (a new client, a shared module) go unstaged.

## Setup and commands

There is no `[build-system]` table in `pyproject.toml` and no lockfile, so dependencies are installed directly (not via `pip install -e .`):

```bash
python3 -m venv .venv
.venv/bin/pip install google-auth google-auth-oauthlib google-api-python-client requests sqlalchemy
```

Run any entry point directly:

```bash
.venv/bin/python google_health_client.py 2026-07-01 2026-07-25   # sleep/heart-rate/activity for a date range
.venv/bin/python google_calendar_client.py                        # tomorrow's events, split workouts vs. work meetings
.venv/bin/python sync_daily.py                                    # the real job: yesterday's health + tomorrow's calendar -> daily_records
```

The first run of each client triggers its own interactive OAuth step (see `google_auth.py` below) and opens a browser tab automatically; every run after that is silent. Health and Calendar each need their **own separate consent** the first time (two browser round-trips, not one) — see the token-per-client note below for why.

No test suite or linter is configured in this repo yet.

**Known inconsistency:** `pyproject.toml` declares `requires-python = ">=3.10"`, but the committed `.venv` was created with the system Python (3.9.6). Don't assume 3.10+ only syntax will run under `.venv/bin/python` until this is reconciled.

## Secrets

`client_secret*.json` (one shared Google OAuth client) and `token_health.json` / `token_calendar.json` (per-client cached tokens, populated after each one's first successful auth) are all gitignored via `client_secret*.json` / `token*.json` and must never be committed. `.gitignore` also excludes `.env*`, key/pem files, common credential filenames, and `*.db` — the local SQLite file (`theapp.db` by default) holds real personal health/calendar data once `sync_daily.py` has run, not just schema, so it's excluded the same way a secret would be. Extend `.gitignore` rather than working around it if a new secret or personal-data file type is introduced. Future secrets from later phases (a Strava OAuth token, an Anthropic API key) should follow the same convention once they're added.

## Architecture: `google_auth.py` (shared logic, per-client tokens)

Every Google API client in this app shares this module's *logic* and one OAuth client (`client_secret*.json`), but **each client must use its own separate token file** — `get_credentials(scopes, token_file)` and `ensure_fresh(creds, token_file)` both take the token path explicitly rather than assuming a single shared one.

**This is a hard requirement discovered live, not a stylistic choice.** The original design used one shared `token.json` covering the union of every scope any client needed. That broke: once the cached token also carried the Calendar scope, every Health API call started failing with `403 PERMISSION_DENIED` / `DISALLOWED_OAUTH_SCOPES` — confirmed by inspecting the response body, which explicitly listed the Calendar scope as disallowed. Re-testing with a token containing *only* Health scopes succeeded immediately. **Google's Health API rejects any access token that also carries scopes from another Google API**, full stop — this is enforced server-side and isn't something fixable from our end except by keeping tokens single-purpose. `google_health_client.py` uses `token_health.json`; `google_calendar_client.py` uses `token_calendar.json`. If a third Google API client is added here, it needs its own third token file too — don't be tempted to consolidate them again.

**Auth flow is non-standard because of a fixed redirect URI.** The Google Health API requires a "Web" type OAuth client (not "Desktop") with `https://www.google.com` registered as the authorized redirect URI — Google's own docs mandate this, and since the same registered client is reused for Calendar too, it inherits this flow rather than a normal loopback one. Since we don't control `google.com`, there's no way to auto-capture the auth code the way a loopback desktop flow does, so the first-ever auth per client is unavoidably interactive: `get_credentials(scopes, token_file)` builds the authorization URL and calls `webbrowser.open()` on it directly, then waits for the user to paste back the resulting `google.com/?code=...` URL (or just the code). `_extract_code()` handles both forms.

**Auth opens the browser directly rather than printing a URL for the user to copy** — this was a deliberate fix after live testing. Printing the URL and relaying it through chat text caused Google to reject the request with `Error 400: invalid_scope`, because the long percent-encoded URL got truncated somewhere in the copy/relay path (verified: Google's error page showed only `https://www.googleapis.com` as the "invalid" scope, i.e. the path after it had been cut off). Calling `webbrowser.open(auth_url)` on the exact Python string sidesteps that entirely; the printed URL is now only a fallback if no browser could be opened.

After the interactive step, the client's token file caches the token and `ensure_fresh()` / `get_credentials()` silently refresh it on every subsequent run via `creds.refresh(Request())` — confirmed live for both clients: a second run against a cached token required no interaction at all.

**`get_credentials(scopes, token_file)` takes the scopes the caller needs, not a fixed list**, and unions them with whatever that specific token file already has before deciding whether to reuse it: if the cached token already covers the requested scopes it's reused (refreshing first if expired); otherwise a fresh interactive auth is triggered for the *union* of old and new scopes *within that file* — so if Health ever needs an additional scope later, re-authenticating for it won't drop the scopes Health already had. This union no longer happens **across** clients/files, which is exactly the point.

**Bug found and fixed here, worth knowing if `get_credentials` ever needs touching again:** `Credentials.from_authorized_user_file(path, scopes=...)` does not validate its `scopes` argument against the file — it silently *overwrites* `creds.scopes` with whatever you pass in, discarding the token's actually-granted scopes. The original code passed `list(required)` there, which made the "does the cached token already cover what's needed" check always trivially true (since it was just comparing `required` against itself), and also corrupted what got sent on refresh, which is what triggered the `invalid_scope` refresh failures above. Fixed by never passing `scopes` to `from_authorized_user_file()` — let it load the file's real stored scopes instead.

**Caveat inherited from Google's docs:** if the OAuth consent screen in Google Cloud Console is still in "Testing" publishing status, Google expires refresh tokens after 7 days regardless of code correctness, forcing the interactive step again — independently per client now, since each has its own token file. This is a Cloud Console project setting, not something fixable in code — check the consent screen's publishing status if re-auth is happening unexpectedly often. Testing-mode consent screens also only grant scopes that were explicitly added to the screen's configured scope list in Cloud Console — if a newly added client's scope isn't there yet, add it before expecting `get_credentials()` to succeed.

## Architecture: `google_health_client.py`

This is a client for the **Google Health API** (`health.googleapis.com`, v4) — Google's OAuth2-based successor to the Fitbit Web API. It is *not* Google Fit (`fitness.googleapis.com`), which Google shut down on 2025-06-30, and it is *not* the Fitbit Web API either (a separate auth system Google explicitly migrated away from). Do not confuse any of these or reuse Fit-style integration patterns (e.g. `InstalledAppFlow.run_local_server`, the `googleapiclient.discovery.build()` pattern) — this module talks to the REST API directly via `requests` instead, since Health isn't a standard discovery-based API the way Calendar is.

**Data type naming has two different cases depending on context** — this is easy to get wrong and isn't obvious from the API surface:
- In URL paths (`/v4/users/me/dataTypes/{type}/dataPoints`), type names are kebab-case: `sleep`, `heart-rate`, `steps`.
- In filter expressions, the same types are referenced snake_case: `sleep`, `heart_rate`, `steps`.

**Filter expressions follow AIP-160** and the field path differs by data type's underlying record shape (documented per-type in `developers.google.com/health/reference`, not inferable from one example):
- `steps` (Interval record): `steps.interval.start_time`
- `sleep` (Session record): `sleep.interval.civil_end_time`
- `heart-rate` (Sample record): `heart_rate.sample_time.physical_time`

Each `fetch_*` helper (`fetch_sleep`, `fetch_heart_rate`, `fetch_activity`) builds the correct filter for its data type; `fetch_all(start_date, end_date)` is the single entry point that obtains credentials once and calls all three. `list_data_points()` is the shared paginated GET (follows `nextPageToken` until exhausted) that every `fetch_*` helper delegates to — new data types should be added as another thin wrapper around it rather than duplicating the pagination/auth logic.

Required OAuth scopes (readonly) are declared in `SCOPES` — sleep, heart rate, and activity each map to a distinct `googlehealth.*.readonly` scope; adding a new data type generally means adding its corresponding scope here too.

**Heart rate data is huge — confirmed live: ~35,000 samples for a single day** of passive continuous monitoring (e.g. a Fitbit). At the API's default page size (1,440/page) that's ~24 sequential paginated requests; `fetch_heart_rate` explicitly requests the API's max page size (10,000) instead, cutting that to ~4. If a new call site needs heart rate data and bypasses `fetch_heart_rate`, don't forget this — the default page size makes it noticeably slower for no benefit.

**Real response shapes** (confirmed live, not just inferred from docs):
- `sleep` dataPoints already include a precomputed `sleep.summary.minutesAsleep` (and `minutesAwake`, per-stage minutes) — no need to sum individual `stages` entries yourself. `summarize_sleep_hours()` uses this directly.
- `heart-rate` dataPoints are one bpm reading each: `heartRate.beatsPerMinute` (a string). `summarize_resting_hr()` takes the day's minimum as a proxy — the API has no distinct "resting heart rate" data type, only continuous samples, so this is an approximation, not a clinical value.
- `steps` dataPoints are ~1-minute interval buckets with `steps.count` (a string). `summarize_steps()` sums these for a daily total.

## Architecture: `google_calendar_client.py`

Uses the standard Google Calendar API v3 via `googleapiclient.discovery.build()` (the officially documented pattern for this API, unlike the Health client) — same shared auth logic from `google_auth.py` but its own `token_calendar.json` (see the per-client-token note above). Auth-tested live: first run completed real browser consent, second run refreshed silently with no interaction.

**Fetches from every calendar the user owns or can write to, not just "primary."** This is deliberate: classification uses both the event's own text *and* the name of the calendar it's on, and a single calendar's name is constant, so it can't be a useful signal on its own. `list_calendars()` filters `calendarList` to `accessRole` of `owner`/`writer` specifically to exclude calendars the user merely subscribes to (e.g. public holiday calendars), which would otherwise pollute the split with noise that isn't actually theirs.

**Classification is a keyword match against `WORKOUT_KEYWORDS`**, checked against the calendar's name plus the event's summary and description combined (`_is_workout()` is the single source of truth). Anything that doesn't match is bucketed as a work meeting — there's no third "unclassified" bucket, by design. The list currently mixes English terms (workout, gym, run, training, yoga, etc.) with Swedish ones (`träning`, `löpning`, `cykling`, `simning`, `pt-pass`), added after a live test against the user's real calendar surfaced an event titled "tränig alt 2 fas 1" being misclassified as a work meeting because the original list was English-only.

**The in-code comments next to the Swedish entries overstate what they actually match — trust the code, not the comment.** They describe stem-style matching (e.g. claiming `träning` also catches `tränar` and the typo `tränig`), but the entries are exact substrings, and `träning` is not a substring of `tränar` or `tränig`. As currently written, a title containing exactly `tränig` (the case that motivated adding Swedish support in the first place) would **not** match `träning` — only an exact `träning`/`löpning`/`cykling`/`simning` substring will. If more Swedish variants start slipping through misclassified, shortening the entries to stems (`trän`, `löp`, `cykl`) would restore the broader matching the comments describe.

**`summarize_calendar_load_hours(events)` clamps each event's duration to tomorrow's own 24-hour window before summing.** This isn't defensive-for-no-reason: live testing surfaced a real calendar entry ("tränig alt 2 fas 1" — apparently a named training phase, not a single session) spanning 2026-07-20 to 2026-08-23. Without clamping, an event like that landing in the work-meetings bucket would count its *entire multi-week span* as one day's load. `_tomorrow_bounds()` is the shared source of truth for that 24-hour window (also used by `fetch_tomorrows_events` itself); all-day events (a `date` with no `dateTime`) are still skipped entirely, not clamped, since they carry no real time-of-day information to clamp.

## Architecture: `daily_records.py`

A single `daily_records` table, one row per day, written to by every future job (health, calendar, Strava, the Claude analysis step) — each job only ever knows about its own columns.

**`date` is the primary key, not a surrogate `id`.** The table is meant to have exactly one row per day; making `date` the key is what makes `upsert_daily_record()` trivially idempotent (`session.get(DailyRecord, date)` either finds today's row or it doesn't) instead of needing a separate uniqueness check.

**`upsert_daily_record(session, date, **fields)` only sets the fields it's given**, leaving every other column on the row untouched. This is the whole point of the design: the health-fetch job can call it with just `sleep_hours`/`hrv`/`resting_hr`, the calendar job with just `calendar_load`, and the eventual Claude analysis step with just `recommendation`, days apart, without any of them needing to know what the others wrote or clobbering each other's data. Verified live: three separate calls for the same date, each setting different columns, correctly collapsed into one row rather than three.

**Only dialect-generic SQLAlchemy types are used** (`Date`, `Float`, `Integer`, `Text` — no SQLite- or Postgres-specific types), and the engine is built from a `DATABASE_URL` environment variable (defaulting to a local `sqlite:///theapp.db`) rather than a hardcoded connection string. Moving to Postgres in deployment is meant to be just setting that env var — no code changes — but note a Postgres driver (e.g. `psycopg2-binary`) isn't installed yet since nothing uses Postgres yet; it'll need adding at that point.

## Architecture: `sync_daily.py`

The first real wiring between the API clients and storage: pulls yesterday's Google Health data and tomorrow's Calendar, and upserts both into `daily_records`. Run and verified live end-to-end, including idempotency: running it twice in a row left exactly the same two rows (one for yesterday, one for tomorrow), not four.

**Yesterday and tomorrow deliberately write to two different rows, not one.** Yesterday's health data describes what already happened (recovery inputs for a readiness call); tomorrow's calendar describes what's coming up (load inputs for that same call). `sync_yesterdays_health()` and `sync_tomorrows_calendar()` are independent and could be run on different schedules if that ever becomes useful.

**Column-to-source mapping is an intentional placeholder in two places, not an oversight:**
- `training_load` is populated from total daily step count (`summarize_steps`) — there's no real training-load metric available yet (that's what the Strava integration in the Roadmap is for), so steps stand in for now. If Strava lands first, redirect this column there rather than trying to combine both sources.
- `hrv` and `subjective_wellness` are never set by this script and stay `None` — neither the Health API scopes this app requests nor the Calendar API provide either one. `subjective_wellness` in particular looks like it's meant to be a manual/self-reported input, not something any API here will ever populate automatically.

## Roadmap (not yet built)

- **Strava integration** — deliberately *not* a direct REST client. Strava's developer terms restrict feeding their API data into AI applications, so the plan is to attach Claude's own Strava MCP connector (`https://mcp.strava.com/mcp`) as a tool on the Claude API call, using a stored Strava OAuth token — not to write a Strava REST integration.
- **Analysis** — a function calling the Claude API (`anthropic` package) with the last 14 days of daily records plus tomorrow's calendar, with the Strava MCP server and web search attached as tools, producing a readiness score and recommendation written back into that day's row.
- **Deployment** — Railway, using its Postgres add-on and a daily ~6am cron trigger; secrets as Railway environment variables, never committed.
- **Delivery** — surface the result somewhere immediately visible on iPhone (email or a Google Sheets row) before considering a dedicated dashboard.
