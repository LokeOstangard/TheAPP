"""Shared Google OAuth2 credential handling for this app's Google API clients.

The registered OAuth client is a "Web" type with https://www.google.com as its
only authorized redirect URI (required by the Google Health API -- see
google_health_client.py). Every client in this app reuses that same client and
a single cached token.json, so there is only ever one interactive consent flow,
covering the union of every scope any client here has ever needed. The first
call to get_credentials() with a new scope re-triggers the interactive step to
extend the token to cover it, without discarding previously granted scopes.
"""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

REDIRECT_URI = "https://www.google.com"

CLIENT_SECRET_FILE = (
    Path(__file__).parent
    / "client_secret_487026754615-478o1i9l4rvigm0otjrfvjqbq096cc40.apps.googleusercontent.com.json"
)
TOKEN_FILE = Path(__file__).parent / "token.json"


def _extract_code(pasted: str) -> str:
    pasted = pasted.strip()
    if pasted.startswith("http"):
        query = parse_qs(urlparse(pasted).query)
        if "code" not in query:
            raise ValueError("No 'code' parameter found in the pasted URL.")
        return query["code"][0]
    return pasted


def _save_credentials(creds: Credentials) -> None:
    TOKEN_FILE.write_text(creds.to_json())


def _run_interactive_auth(scopes: list[str]) -> Credentials:
    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRET_FILE), scopes=scopes, redirect_uri=REDIRECT_URI
    )
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    opened = webbrowser.open(auth_url)
    print("Sign in and approve access in the browser tab that just opened.")
    if not opened:
        print("Couldn't open a browser automatically -- open this URL manually instead:\n")
        print(auth_url)
    print()
    pasted = input(
        "After approving, you'll land on google.com with a 'code' parameter "
        "in the address bar. Paste the full URL (or just the code) here: "
    )
    flow.fetch_token(code=_extract_code(pasted))
    return flow.credentials


def get_credentials(scopes: Iterable[str]) -> Credentials:
    required = set(scopes)
    creds: Credentials | None = None
    existing_scopes: set[str] = set()

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), list(required))
        existing_scopes = set(creds.scopes or [])

    if creds and existing_scopes >= required:
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_credentials(creds)
            return creds

    creds = _run_interactive_auth(sorted(existing_scopes | required))
    _save_credentials(creds)
    return creds


def ensure_fresh(creds: Credentials) -> Credentials:
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_credentials(creds)
    return creds
