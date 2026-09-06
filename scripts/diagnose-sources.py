"""Temporary bounded source probe: no credentials or raw response output."""
import json
import os
import subprocess

import httpx

from help_me_tibooo.sources import RESET_FEED_URL, TWISCAN_TIMELINE_URL


def main():
    print("[DEBUG-source-access]", json.dumps({
        "proxy_configured": any(os.environ.get(k) for k in (
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
        )),
    }))
    for name, url in (("reset", RESET_FEED_URL), ("twiscan", TWISCAN_TIMELINE_URL)):
        try:
            with httpx.Client() as client:
                with client.stream("GET", url, headers={"User-Agent": "help-me-tibooo/0.1"}, timeout=15) as r:
                    print("[DEBUG-source-access]", json.dumps({
                        "source": name, "client": "httpx", "status": r.status_code,
                        "cloudflare": r.headers.get("server", "").lower() == "cloudflare",
                        "challenge": r.headers.get("cf-mitigated") == "challenge",
                        "html": "text/html" in r.headers.get("content-type", ""),
                        "retry_after_present": "retry-after" in r.headers,
                        "via_present": "via" in r.headers,
                    }))
        except httpx.HTTPError:
            print("[DEBUG-source-access]", name, "httpx transport error")
        result = subprocess.run([
            "curl", "--silent", "--max-time", "15", "--output", "/dev/null",
            "--user-agent", "help-me-tibooo/0.1", "--write-out", "%{http_code}", url,
        ], capture_output=True, text=True)
        status = result.stdout if result.stdout.isascii() and result.stdout.isdigit() else "unknown"
        print("[DEBUG-source-access]", json.dumps({"source": name, "client": "curl", "status": status}))


if __name__ == "__main__":
    main()
