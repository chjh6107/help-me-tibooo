from collections.abc import Iterator

import httpx
from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException, Timeout


class SourceStream(httpx.SyncByteStream):
    def __init__(self, response: requests.Response) -> None:
        self.response = response

    def __iter__(self) -> Iterator[bytes]:
        try:
            yield from self.response.iter_content()
        except Timeout as error:
            raise httpx.ReadTimeout("source request timed out") from error
        except RequestException as error:
            raise httpx.ReadError("source request failed") from error

    def close(self) -> None:
        self.response.close()


class SourceTransport(httpx.BaseTransport):
    """Public source GETs using the browser connection profile verified in Actions."""

    def __init__(self) -> None:
        self.session = requests.Session(impersonate="chrome")

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            raise httpx.UnsupportedProtocol("source transport only supports GET")
        try:
            response = self.session.request(
                "GET",
                str(request.url),
                timeout=request.extensions.get("timeout", {}).get("read", 15.0),
                allow_redirects=False,
                stream=True,
            )
        except Timeout as error:
            raise httpx.ReadTimeout("source request timed out", request=request) from error
        except RequestException as error:
            raise httpx.ConnectError("source request failed", request=request) from error

        # curl has already decoded compressed bytes before yielding them.
        headers = {key: value for key, value in response.headers.items() if key.lower() != "content-encoding"}
        return httpx.Response(response.status_code, headers=headers, stream=SourceStream(response))

    def close(self) -> None:
        self.session.close()
