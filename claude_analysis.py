"""Calls the Claude API to generate a training-readiness recommendation and
saves it into today's daily_records row.

Context sent to Claude:
- The last 14 complete days of daily_records (ending yesterday, not today).
  Today's own row never has health data yet at the point this function runs:
  sync_daily.py only ever backfills *yesterday's* health metrics, so today's
  sleep/HRV/resting-HR/training-load won't land until tomorrow's sync run.
  Ending the history window at yesterday avoids sending Claude a trailing row
  of mostly-None values.
- Tomorrow's calendar_load, which (by the same pipeline timing) was already
  written into tomorrow's row by today's sync_daily.py run.
- Recent Strava activity, pulled directly by Claude via the Strava MCP
  connector -- this app never calls Strava's REST API itself. Per Strava's
  developer terms restricting feeding their API data into AI applications
  (see CLAUDE.md Roadmap), routing through Claude's own MCP tool use is the
  compliant path, not a REST integration we'd write here.
- Whatever current sports-science evidence Claude decides is relevant, via
  the web search tool -- this isn't meant to be answered from static prior
  knowledge alone.

The recommendation column is a single Text field with no separate
readiness-score column, so the score is embedded as the first line of the
saved text rather than requiring a schema change for one integer.

Requires a Strava MCP authorization token (see
https://platform.claude.com/docs/en/agents-and-tools/mcp-connector for the
OAuth flow to obtain one -- not implemented here, since building that flow is
a separate, not-yet-built roadmap item). Read from the STRAVA_MCP_TOKEN
environment variable by default.
"""

from __future__ import annotations

import datetime as dt
import os

import anthropic
from sqlalchemy import and_
from sqlalchemy.orm import Session

from daily_records import DailyRecord, upsert_daily_record

MODEL = "claude-opus-5"
MCP_BETA = "mcp-client-2025-11-20"

STRAVA_MCP_URL = "https://mcp.strava.com/mcp"
STRAVA_MCP_SERVER_NAME = "strava"
STRAVA_TOKEN_ENV_VAR = "STRAVA_MCP_TOKEN"

HISTORY_DAYS = 14

SYSTEM_PROMPT = """You are a sports-science-informed training advisor assessing one athlete's readiness for tomorrow.

You have three inputs: a 14-day history of daily sleep, resting heart rate, training load, calendar load, and subjective wellness; tomorrow's scheduled work/meeting load; and direct access to this athlete's recent Strava activity via a tool. Pull their recent Strava activity before forming a judgment -- the 14-day table alone does not include actual workout data.

Cross-reference your reasoning against current sports-science evidence using web search where it would sharpen the recommendation (e.g. recovery norms, overtraining indicators, interference effects) rather than relying only on prior knowledge for anything that might have evolved.

Respond in exactly this format, with nothing before or after:

Readiness: <integer 1-10>/10
<one paragraph, specific and actionable recommendation for tomorrow -- not generic advice>
"""


def _format_history(records: list[DailyRecord]) -> str:
    header = "date,sleep_hours,hrv,resting_hr,training_load,calendar_load,subjective_wellness"
    rows = [
        f"{r.date},{r.sleep_hours},{r.hrv},{r.resting_hr},{r.training_load},{r.calendar_load},{r.subjective_wellness}"
        for r in records
    ]
    return "\n".join([header, *rows])


def _build_user_message(session: Session, today: dt.date) -> str:
    history_start = today - dt.timedelta(days=HISTORY_DAYS)
    history_end = today - dt.timedelta(days=1)
    tomorrow = today + dt.timedelta(days=1)

    history = (
        session.query(DailyRecord)
        .filter(and_(DailyRecord.date >= history_start, DailyRecord.date <= history_end))
        .order_by(DailyRecord.date)
        .all()
    )
    tomorrow_record = session.get(DailyRecord, tomorrow)
    tomorrow_calendar_load = tomorrow_record.calendar_load if tomorrow_record else None
    calendar_note = (
        f"{tomorrow_calendar_load} hours scheduled"
        if tomorrow_calendar_load is not None
        else "no calendar data available yet"
    )

    return (
        f"Last {HISTORY_DAYS} days of daily records ({history_start} to {history_end}), CSV:\n"
        f"{_format_history(history)}\n\n"
        f"Tomorrow ({tomorrow}): {calendar_note}.\n\n"
        "Pull my recent Strava activity now, then assess my training readiness for tomorrow."
    )


def _mcp_config(strava_token: str) -> tuple[list[dict], list[dict]]:
    mcp_servers = [
        {
            "type": "url",
            "url": STRAVA_MCP_URL,
            "name": STRAVA_MCP_SERVER_NAME,
            "authorization_token": strava_token,
        }
    ]
    tools = [
        {"type": "mcp_toolset", "mcp_server_name": STRAVA_MCP_SERVER_NAME},
        {"type": "web_search_20260318", "name": "web_search"},
    ]
    return mcp_servers, tools


def generate_readiness_recommendation(session: Session, strava_token: str | None = None) -> str:
    strava_token = strava_token or os.environ.get(STRAVA_TOKEN_ENV_VAR)
    if not strava_token:
        raise RuntimeError(
            f"No Strava MCP token provided and {STRAVA_TOKEN_ENV_VAR} is not set."
        )

    today = dt.date.today()
    user_message = _build_user_message(session, today)
    mcp_servers, tools = _mcp_config(strava_token)
    client = anthropic.Anthropic()

    messages = [{"role": "user", "content": user_message}]
    while True:
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=16000,
            betas=[MCP_BETA],
            system=SYSTEM_PROMPT,
            output_config={"effort": "high"},
            mcp_servers=mcp_servers,
            tools=tools,
            messages=messages,
        ) as stream:
            response = stream.get_final_message()

        if response.stop_reason != "pause_turn":
            break
        # Resend exactly [original user message, latest paused assistant turn] --
        # not an accumulating history of every pause cycle (the server resumes
        # the paused server-tool loop from this pair, not from a longer replay).
        messages = [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": response.content},
        ]

    if response.stop_reason == "refusal":
        recommendation_text = (
            "Claude declined to produce a recommendation for this request "
            f"(category: {getattr(response.stop_details, 'category', None)})."
        )
    else:
        recommendation_text = next(
            (block.text for block in response.content if block.type == "text"), ""
        )

    upsert_daily_record(session, today, recommendation=recommendation_text)
    return recommendation_text


if __name__ == "__main__":
    from daily_records import SessionLocal, init_db

    init_db()
    with SessionLocal() as db_session:
        print(generate_readiness_recommendation(db_session))
