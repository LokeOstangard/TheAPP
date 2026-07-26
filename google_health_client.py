"""Google Health API client for sleep, heart rate, and activity data.

Auth note: the Google Health API requires a "Web" OAuth client with
https://www.google.com registered as its authorized redirect URI (see
https://developers.google.com/health/setup) -- this is why the interactive,
paste-the-redirect-URL auth flow in google_auth.py exists instead of a normal
loopback flow. This client also uses its own exclusive token_health.json,
never shared with another Google API's token -- see google_auth.py's
docstring for why (Health rejects tokens carrying any other API's scopes).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import requests
from google.oauth2.credentials import Credentials

from google_auth import ensure_fresh, get_credentials

SCOPES = [
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
]

# Must not be shared with any other Google API's token -- see google_auth.py.
TOKEN_FILE = Path(__file__).parent / "token_health.json"

BASE_URL = "https://health.googleapis.com/v4"


def list_data_points(
    creds: Credentials,
    data_type: str,
    filter_expr: str,
    page_size: int | None = None,
) -> list[dict[str, Any]]:
    creds = ensure_fresh(creds, TOKEN_FILE)
    url = f"{BASE_URL}/users/me/dataTypes/{data_type}/dataPoints"
    params: dict[str, Any] = {"filter": filter_expr}
    if page_size:
        params["pageSize"] = page_size

    headers = {"Authorization": f"Bearer {creds.token}", "Accept": "application/json"}
    data_points: list[dict[str, Any]] = []
    while True:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        data_points.extend(payload.get("dataPoints", []))
        next_token = payload.get("nextPageToken")
        if not next_token:
            break
        params["pageToken"] = next_token

    return data_points


def fetch_sleep(creds: Credentials, start_date: dt.date, end_date: dt.date) -> list[dict[str, Any]]:
    end_exclusive = end_date + dt.timedelta(days=1)
    filter_expr = (
        f'sleep.interval.civil_end_time >= "{start_date.isoformat()}" '
        f'AND sleep.interval.civil_end_time < "{end_exclusive.isoformat()}"'
    )
    return list_data_points(creds, "sleep", filter_expr, page_size=25)


def fetch_heart_rate(creds: Credentials, start_date: dt.date, end_date: dt.date) -> list[dict[str, Any]]:
    start_iso = dt.datetime.combine(start_date, dt.time.min, tzinfo=dt.timezone.utc).isoformat()
    end_iso = dt.datetime.combine(
        end_date + dt.timedelta(days=1), dt.time.min, tzinfo=dt.timezone.utc
    ).isoformat()
    filter_expr = (
        f'heart_rate.sample_time.physical_time >= "{start_iso}" '
        f'AND heart_rate.sample_time.physical_time < "{end_iso}"'
    )
    # Passive continuous monitoring (e.g. Fitbit) can produce tens of
    # thousands of samples per day -- confirmed live: ~35k for one day.
    # Using the API's max page size (10,000) cuts that from ~24 paginated
    # requests down to ~4.
    return list_data_points(creds, "heart-rate", filter_expr, page_size=10000)


def fetch_activity(creds: Credentials, start_date: dt.date, end_date: dt.date) -> list[dict[str, Any]]:
    start_iso = dt.datetime.combine(start_date, dt.time.min, tzinfo=dt.timezone.utc).isoformat()
    end_iso = dt.datetime.combine(
        end_date + dt.timedelta(days=1), dt.time.min, tzinfo=dt.timezone.utc
    ).isoformat()
    filter_expr = (
        f'steps.interval.start_time >= "{start_iso}" '
        f'AND steps.interval.start_time < "{end_iso}"'
    )
    return list_data_points(creds, "steps", filter_expr)


def summarize_sleep_hours(sleep_points: list[dict[str, Any]]) -> float | None:
    """Total minutesAsleep across all sleep dataPoints in the range, in hours.

    Google's response already precomputes minutesAsleep per session (verified
    live), so this doesn't need to re-derive it from individual sleep stages.
    """
    minutes = [
        int(p["sleep"]["summary"]["minutesAsleep"])
        for p in sleep_points
        if "summary" in p.get("sleep", {})
    ]
    return sum(minutes) / 60 if minutes else None


def summarize_resting_hr(heart_rate_points: list[dict[str, Any]]) -> int | None:
    """Approximates resting HR as the day's minimum bpm reading.

    The Health API doesn't expose a distinct "resting heart rate" data type
    (only continuous bpm samples), so this is a proxy, not a clinical value.
    """
    bpms = [int(p["heartRate"]["beatsPerMinute"]) for p in heart_rate_points]
    return min(bpms) if bpms else None


def summarize_steps(activity_points: list[dict[str, Any]]) -> int | None:
    """Total steps across all 1-minute interval buckets in the range."""
    counts = [int(p["steps"]["count"]) for p in activity_points]
    return sum(counts) if counts else None


def fetch_all(start_date: dt.date, end_date: dt.date) -> dict[str, list[dict[str, Any]]]:
    creds = get_credentials(SCOPES, TOKEN_FILE)
    return {
        "sleep": fetch_sleep(creds, start_date, end_date),
        "heart_rate": fetch_heart_rate(creds, start_date, end_date),
        "activity": fetch_activity(creds, start_date, end_date),
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch Google Health API data for a date range.")
    parser.add_argument("start_date", type=dt.date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument("end_date", type=dt.date.fromisoformat, help="YYYY-MM-DD")
    args = parser.parse_args()

    data = fetch_all(args.start_date, args.end_date)
    for key, points in data.items():
        print(f"{key}: {len(points)} data points")
