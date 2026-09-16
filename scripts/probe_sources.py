"""One-shot public endpoint diagnostics; no credentials or watcher state."""

import json

import httpx


urls = (
    "https://codex-reset.com/api/feed",
    "https://twiscan.com/en/x/thsottiaux",
    "https://codex-resets.com/api/v1/resets?limit=100",
    "https://codex-resets.com/api/v1/status",
)

with httpx.Client(timeout=20, follow_redirects=True) as client:
    for url in urls:
        try:
            response = client.get(url, headers={"User-Agent": "help-me-tibooo/0.1", "Accept": "application/json,text/html"})
            details = {
                "url": url,
                "status": response.status_code,
                "headers": {
                    name: response.headers.get(name)
                    for name in ("server", "content-type", "cf-mitigated", "cf-ray", "retry-after", "via")
                },
            }
            if response.status_code == 200 and "application/json" in response.headers.get("content-type", ""):
                data = response.json()
                details["keys"] = sorted(data) if isinstance(data, dict) else []
                details["items"] = len(data.get("data", data.get("tweets", []))) if isinstance(data, dict) else 0
            print(json.dumps(details), flush=True)
        except httpx.HTTPError as error:
            print(json.dumps({"url": url, "error_type": type(error).__name__}), flush=True)
