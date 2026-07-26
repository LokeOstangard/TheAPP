"""Daily sync: pulls yesterday's Google Health data and tomorrow's Calendar,
and upserts both into the daily_records table.

Yesterday and tomorrow deliberately land in different rows: yesterday's
health data is what actually happened (an input to a readiness analysis),
tomorrow's calendar is what's coming up (a separate input to that same
analysis). Safe to re-run any number of times for either day --
upsert_daily_record() only overwrites the columns this script sets, so
re-running just recomputes the same values instead of creating duplicates.

training_load is populated from total daily step count, as a placeholder
until Strava-based training load exists (see the Roadmap in CLAUDE.md) --
swap the source in sync_yesterdays_health() below if a better one arrives
first. hrv and subjective_wellness are left unset here: neither the Health
API scopes this app requests nor the Calendar API provide that data.
"""

from __future__ import annotations

import datetime as dt

from daily_records import SessionLocal, init_db, upsert_daily_record
from google_calendar_client import fetch_tomorrows_events, summarize_calendar_load_hours
from google_health_client import (
    fetch_all,
    summarize_resting_hr,
    summarize_sleep_hours,
    summarize_steps,
)


def sync_yesterdays_health(session) -> None:
    yesterday = dt.date.today() - dt.timedelta(days=1)
    data = fetch_all(yesterday, yesterday)
    upsert_daily_record(
        session,
        yesterday,
        sleep_hours=summarize_sleep_hours(data["sleep"]),
        resting_hr=summarize_resting_hr(data["heart_rate"]),
        training_load=summarize_steps(data["activity"]),
    )


def sync_tomorrows_calendar(session) -> None:
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    events = fetch_tomorrows_events()
    upsert_daily_record(
        session,
        tomorrow,
        calendar_load=summarize_calendar_load_hours(events["work_meetings"]),
    )


def main() -> None:
    init_db()
    with SessionLocal() as session:
        sync_yesterdays_health(session)
        sync_tomorrows_calendar(session)
    print("Synced yesterday's health data and tomorrow's calendar.")


if __name__ == "__main__":
    main()
