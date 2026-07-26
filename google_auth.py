"""Shared Google OAuth2 credential handling for this app's Google API clients.

The registered OAuth client is a "Web" type with https://www.google.com as its
only authorized redirect URI (required by the Google Health API).

**Every client needs its own token file, not one shared one.** Confirmed live:
the Health API rejects requests with 403 DISALLOWED_OAUTH_SCOPES if the access
token used also carries scopes from any other Google API (e.g. Calendar) --
Google's server-side check, not something under our control. So each client
passes its own `token_file` to get_credentials(); scopes are only ever unioned
within that one file's history, never across clients. Two clients wanting the
same file would still need disjoint scopes, or the same problem recurs.
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


def _extract_code(pasted: str) -> str:
    pasted = pasted.strip()
    if pasted.startswith("http"):
        query = parse_qs(urlparse(pasted).query)
        if "code" not in query:
            raise ValueError("No 'code' parameter found in the pasted URL.")
        return query["code"][0]
    return pasted


def _save_credentials(creds: Credentials, token_file: Path) -> None:
    token_file.write_text(creds.to_json())


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


def get_credentials(scopes: Iterable[str], token_file: Path) -> Credentials:
    required = set(scopes)
    creds: Credentials | None = None
    existing_scopes: set[str] = set()

    if token_file.exists():
        # Deliberately omit the `scopes` argument here: passing one overwrites
        # creds.scopes with whatever we pass instead of the token's actually
        # granted scopes, which broke the coverage check below and caused
        # Google to reject refreshes with invalid_scope.
        creds = Credentials.from_authorized_user_file(str(token_file))
        existing_scopes = set(creds.scopes or [])

    if creds and existing_scopes >= required:
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_credentials(creds, token_file)
            return creds

    creds = _run_interactive_auth(sorted(existing_scopes | required))
    _save_credentials(creds, token_file)
    return creds


def ensure_fresh(creds: Credentials, token_file: Path) -> Credentials:
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_credentials(creds, token_file)
    return creds
