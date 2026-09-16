"""One-shot public endpoint diagnostics; no credentials or watcher state."""

import json

import httpx


urls = (
    "https://codex-reset.com/api/feed",
    "https://twiscan.com/en/x/thsottiaux",
    "https://codex-resets.com/api/v1/resets?limit=100",
    "https://codex-resets.com/api/v1/status",
    "https://codex-reset.com/feed.xml",
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

with httpx.Client(timeout=20, follow_redirects=True) as client:
    for user_agent in ("curl/8.5.0", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151 Safari/537.36"):
        for url in (urls[0], urls[2]):
            response = client.get(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
            print(json.dumps({"variant": user_agent, "url": url, "status": response.status_code, "challenge": response.headers.get("cf-mitigated")}))

from curl_cffi import requests
for url in urls:
    try:
        response = requests.get(url, impersonate="chrome", timeout=20)
        details = {"transport": "curl_cffi", "url": url, "status": response.status_code, "challenge": response.headers.get("cf-mitigated")}
        if response.status_code == 200 and "application/json" in response.headers.get("content-type", ""):
            data = response.json()
            details["items"] = len(data.get("data", data.get("tweets", [])))
            details["newest_post_at"] = data.get("newest_post_at")
        print(json.dumps(details), flush=True)
    except Exception as error:
        print(json.dumps({"transport": "curl_cffi", "url": url, "error_type": type(error).__name__}), flush=True)
