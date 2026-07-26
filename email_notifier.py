"""Emails the daily training-readiness recommendation.

Uses plain SMTP (stdlib smtplib + email) rather than a third-party email
API -- no new dependency needed for one message a day. Credentials are
env-var-only and never written to disk, following the same pattern as
ANTHROPIC_API_KEY and STRAVA_MCP_TOKEN elsewhere in this app.

For a Gmail account (this app's default use case), set SMTP_HOST/SMTP_PORT
to smtp.gmail.com/587 and use a Google "app password" for SMTP_PASSWORD --
Gmail rejects plain SMTP auth with a normal account password.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

SMTP_HOST_ENV_VAR = "SMTP_HOST"
SMTP_PORT_ENV_VAR = "SMTP_PORT"
SMTP_USERNAME_ENV_VAR = "SMTP_USERNAME"
SMTP_PASSWORD_ENV_VAR = "SMTP_PASSWORD"
EMAIL_FROM_ENV_VAR = "EMAIL_FROM"
EMAIL_TO_ENV_VAR = "EMAIL_TO"

REQUIRED_ENV_VARS = (
    SMTP_HOST_ENV_VAR,
    SMTP_USERNAME_ENV_VAR,
    SMTP_PASSWORD_ENV_VAR,
    EMAIL_FROM_ENV_VAR,
    EMAIL_TO_ENV_VAR,
)

DEFAULT_SMTP_PORT = 587


def _subject_for(recommendation: str) -> str:
    first_line = next((line for line in recommendation.splitlines() if line.strip()), "")
    return f"Training readiness -- {first_line}" if first_line else "Training readiness recommendation"


def send_recommendation_email(recommendation: str) -> None:
    """Send `recommendation` as the body of a plaintext email.

    Raises immediately with the names of any missing env vars rather than
    failing deep inside smtplib, mirroring how generate_readiness_recommendation()
    handles a missing STRAVA_MCP_TOKEN.
    """
    missing = [var for var in REQUIRED_ENV_VARS if not os.environ.get(var)]
    if missing:
        raise RuntimeError(
            f"Cannot send recommendation email, missing env var(s): {', '.join(missing)}."
        )

    host = os.environ[SMTP_HOST_ENV_VAR]
    port = int(os.environ.get(SMTP_PORT_ENV_VAR, str(DEFAULT_SMTP_PORT)))
    username = os.environ[SMTP_USERNAME_ENV_VAR]
    password = os.environ[SMTP_PASSWORD_ENV_VAR]
    sender = os.environ[EMAIL_FROM_ENV_VAR]
    recipient = os.environ[EMAIL_TO_ENV_VAR]

    message = EmailMessage()
    message["Subject"] = _subject_for(recommendation)
    message["From"] = sender
    message["To"] = recipient
    message.set_content(recommendation)

    with smtplib.SMTP(host, port) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)


if __name__ == "__main__":
    send_recommendation_email("Readiness: 7/10\nTest email from email_notifier.py.")
    print("Test email sent.")
