"""
Lightweight OAuth callback server for PAXS authorization.
Starts a temporary HTTP server to capture the OAuth callback,
then exchanges the code for tokens automatically.

Usage:
    python oauth_callback_server.py [--port 3000] [--paxs-url https://dzd.paxs.ai]
"""

import http.server
import urllib.parse
import requests
import secrets
import webbrowser
import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="PAXS OAuth Authorization")
    parser.add_argument("--port", type=int, default=3000, help="Callback server port")
    parser.add_argument("--paxs-url", default="https://dzd.paxs.ai", help="PAXS API base URL (default: https://dzd.paxs.ai)")
    args = parser.parse_args()

    callback_uri = f"http://localhost:{args.port}/callback"
    state = secrets.token_urlsafe(16)

    auth_url = (
        f"{args.paxs_url}/api/oauth/provider/authorize?"
        f"redirect_uri={callback_uri}&"
        f"response_type=code&"
        f"state={state}"
    )

    print(f"\nOpen this link to authorize:\n\n  {auth_url}\n")
    webbrowser.open(auth_url)
    print("Waiting for authorization...\n")

    code = _wait_for_callback(args.port, state)
    if not code:
        print("Authorization failed.")
        sys.exit(1)

    response = requests.post(
        f"{args.paxs_url}/api/oauth/provider/token",
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_uri,
        },
    )

    if response.status_code != 200:
        print(f"Token exchange failed: {response.text}")
        sys.exit(1)

    tokens = response.json()
    print(json.dumps(tokens, indent=2))


def _wait_for_callback(port, expected_state):
    result = {"code": None}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            error = params.get("error", [None])[0]
            state = params.get("state", [None])[0]

            if error or state != expected_state:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h2>Authorization failed.</h2>")
                return

            result["code"] = params.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Authorized! You can close this tab.</h2>")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("localhost", port), Handler)
    server.handle_request()
    server.server_close()
    return result["code"]


if __name__ == "__main__":
    main()
