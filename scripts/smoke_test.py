"""Check the running Compose stack using only the Python standard library."""

import json
import os
import re
from email.message import Message
from urllib.error import HTTPError
from urllib.request import urlopen


def request(url: str, expected_status: int = 200) -> tuple[bytes, Message]:
    try:
        response = urlopen(url, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        assert response.status == expected_status, (url, response.status)
        return response.read(), response.headers


def main() -> None:
    backend = f"http://127.0.0.1:{os.getenv('BACKEND_PORT', '8000')}"
    frontend = f"http://127.0.0.1:{os.getenv('FRONTEND_PORT', '8080')}"

    body, _ = request(f"{backend}/health")
    assert json.loads(body) == {"status": "ok"}
    _, headers = request(f"{backend}/auth/me", 401)
    assert headers.get("WWW-Authenticate") == "Bearer"
    request(f"{backend}/docs")
    body, _ = request(f"{backend}/openapi.json")
    assert "/auth/me" in json.loads(body)["paths"]

    index, headers = request(f"{frontend}/index.html")
    assert 'id="root"' in index.decode()
    assert headers.get("Cache-Control") == "no-cache"
    body, _ = request(f"{frontend}/a/client/route")
    assert body == index, "SPA navigation should serve index.html"
    asset = re.search(r'src="(/assets/[^"]+\.js)"', index.decode())
    assert asset, "Expected a built Vite JavaScript asset"
    _, headers = request(f"{frontend}{asset.group(1)}")
    assert "immutable" in headers.get("Cache-Control", "")
    request(f"{frontend}/assets/missing.js", 404)
    print("Container smoke checks passed.")


if __name__ == "__main__":
    main()
