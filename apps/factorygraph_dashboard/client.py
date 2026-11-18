"""Server-side authenticated API client. No research-file or database access."""

import os
from pathlib import Path
from urllib.parse import urlparse

import httpx


class APIError(Exception):
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload
        super().__init__(f"API request unavailable ({status})")


def request(method, path, **kwargs):
    base = os.environ.get("FG7_API_URL", "http://127.0.0.1:18080")
    parsed = urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "api"}:
        raise ValueError("Only the configured local API is supported")
    token_path = os.environ.get("FG7_DASHBOARD_TOKEN_FILE")
    if not token_path:
        raise ValueError("Server-side API credential is not configured")
    try:
        token = Path(token_path).read_text(encoding="utf-8").strip()
    except OSError:
        raise APIError(503, {"error": "server_credential_unavailable"}) from None
    try:
        response = httpx.request(
            method,
            base + "/api/v1" + path,
            headers={"Authorization": "Bearer " + token},
            timeout=125,
            follow_redirects=False,
            **kwargs,
        )
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        raise APIError(503, {"error": "api_unreachable"}) from None
    if response.status_code != 200:
        raise APIError(response.status_code, payload)
    return payload
