"""Google Calendar client that fetches tomorrow's events and splits them into
workouts vs. work meetings.

Classification is keyword-based: an event is a "workout" if WORKOUT_KEYWORDS
matches its calendar's name or its own title/description, otherwise it's
treated as a work meeting. WORKOUT_KEYWORDS is a starting guess -- edit it to
match your actual calendar naming and event titles.

Events are pulled from every calendar you own or can write to (not just the
primary one), since a calendar's name is one of the two classification
signals -- a single calendar can't tell workouts from meetings by name alone.
Calendars you only subscribe to (e.g. public holiday calendars) are skipped.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from google_auth import get_credentials

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# Must not be shared with any other Google API's token -- see google_auth.py
# (confirmed live: Google Health rejects tokens carrying non-Health scopes).
TOKEN_FILE = Path(__file__).parent / "token_calendar.json"

WORKOUT_KEYWORDS = [
    "workout",
    "gym",
    "run",
    "ride",
    "bike",
    "swim",
    "training",
    "lift",
    "yoga",
    "spin",
    "crossfit",
    "hiit",
    "cardio",
    "climb",
    # svenska
    "träning",  # matches träning, tränar, tränig (typo for träning), styrketräning, etc.
    "löpning",  # matches löpning, löppass, löptur
    "cykling",  # matches cykling, cyklar
    "simning",
    "pt-pass",
]

WRITABLE_ACCESS_ROLES = {"owner", "writer"}


def build_service(creds: Credentials):
    return build("calendar", "v3", credentials=creds)


def list_calendars(service) -> list[dict[str, Any]]:
    calendars: list[dict[str, Any]] = []
    page_token = None
    while True:
        response = service.calendarList().list(pageToken=page_token).execute()
        calendars.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return [c for c in calendars if c.get("accessRole") in WRITABLE_ACCESS_ROLES]


def list_events(service, calendar_id: str, time_min: str, time_max: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    page_token = None
    while True:
        response = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                pageToken=page_token,
            )
            .execute()
        )
        events.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return events


def _is_workout(calendar_name: str, event: dict[str, Any]) -> bool:
    text = " ".join([calendar_name, event.get("summary", ""), event.get("description", "")]).lower()
    return any(keyword in text for keyword in WORKOUT_KEYWORDS)


def _tomorrow_bounds() -> tuple[dt.datetime, dt.datetime]:
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    start = dt.datetime.combine(tomorrow, dt.time.min).astimezone()
    end = dt.datetime.combine(tomorrow + dt.timedelta(days=1), dt.time.min).astimezone()
    return start, end


def _tomorrow_range() -> tuple[str, str]:
    start, end = _tomorrow_bounds()
    return start.isoformat(), end.isoformat()


def fetch_tomorrows_events(creds: Credentials | None = None) -> dict[str, list[dict[str, Any]]]:
    creds = creds or get_credentials(SCOPES, TOKEN_FILE)
    service = build_service(creds)
    time_min, time_max = _tomorrow_range()

    workouts: list[dict[str, Any]] = []
    work_meetings: list[dict[str, Any]] = []
    for calendar in list_calendars(service):
        calendar_name = calendar.get("summary", "")
        for event in list_events(service, calendar["id"], time_min, time_max):
            bucket = workouts if _is_workout(calendar_name, event) else work_meetings
            bucket.append(event)

    return {"workouts": workouts, "work_meetings": work_meetings}


def summarize_calendar_load_hours(events: list[dict[str, Any]]) -> float | None:
    """Total scheduled hours tomorrow across events with real start/end times.

    Clamped to tomorrow's own day boundaries -- some calendar entries span
    multi-week periods (e.g. a named training phase, confirmed live on this
    user's calendar: an event ran 2026-07-20 to 2026-08-23), and counting a
    whole multi-week event's raw duration would wildly overstate a single
    day's load. All-day events (a 'date' with no 'dateTime') are skipped
    entirely -- they aren't real blocked time.
    """
    day_start, day_end = _tomorrow_bounds()
    total_seconds = 0.0
    counted = 0
    for event in events:
        start = event.get("start", {}).get("dateTime")
        end = event.get("end", {}).get("dateTime")
        if not start or not end:
            continue
        overlap_start = max(dt.datetime.fromisoformat(start), day_start)
        overlap_end = min(dt.datetime.fromisoformat(end), day_end)
        if overlap_end <= overlap_start:
            continue
        total_seconds += (overlap_end - overlap_start).total_seconds()
        counted += 1
    return total_seconds / 3600 if counted else None


if __name__ == "__main__":
    data = fetch_tomorrows_events()
    for key, events in data.items():
        print(f"{key}: {len(events)} event(s)")
        for event in events:
            print(f"  - {event.get('summary', '(no title)')}")
