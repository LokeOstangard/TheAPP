"""Railway entry point: the actual daily job, start to finish.

Railway's cron trigger (see railway.json's deploy.cronSchedule) runs this
script once a day. It chains the pipeline steps that otherwise only exist
as separate __main__ blocks -- sync_daily.py's Google sync, then
claude_analysis.py's Claude call -- and finishes by emailing the resulting
recommendation, so one Railway run covers the whole day's job instead of
three separately-scheduled ones.

Must exit on completion (success or failure) with no lingering resources --
Railway's cron jobs are expected to terminate, not stay running.
"""

from __future__ import annotations

from claude_analysis import generate_readiness_recommendation
from daily_records import SessionLocal, init_db
from email_notifier import send_recommendation_email
from sync_daily import sync_tomorrows_calendar, sync_yesterdays_health


def main() -> None:
    init_db()
    with SessionLocal() as session:
        sync_yesterdays_health(session)
        sync_tomorrows_calendar(session)
        recommendation = generate_readiness_recommendation(session)

    send_recommendation_email(recommendation)
    print("Daily job complete: synced, analyzed, and emailed today's recommendation.")


if __name__ == "__main__":
    main()
