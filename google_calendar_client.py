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
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from google_auth import get_credentials

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

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


def _tomorrow_range() -> tuple[str, str]:
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    time_min = dt.datetime.combine(tomorrow, dt.time.min).astimezone().isoformat()
    time_max = dt.datetime.combine(tomorrow + dt.timedelta(days=1), dt.time.min).astimezone().isoformat()
    return time_min, time_max


def fetch_tomorrows_events(creds: Credentials | None = None) -> dict[str, list[dict[str, Any]]]:
    creds = creds or get_credentials(SCOPES)
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


if __name__ == "__main__":
    data = fetch_tomorrows_events()
    for key, events in data.items():
        print(f"{key}: {len(events)} event(s)")
        for event in events:
            print(f"  - {event.get('summary', '(no title)')}")
