"""A fake customer deployment for manual and end-to-end testing: an OIDC identity provider plus a CTEM gateway.

    python tests/e2e/fake_stack.py [--idp-port 9400] [--gateway-port 9401] [--access-ttl 3600]

IdP (http://127.0.0.1:9400):
  /.well-known/openid-configuration   discovery
  /authorize                          signs in "analyst@example.com" instantly and redirects back with a code
                                      (validates client_id, redirect_uri and PKCE S256 like a real IdP)
  /token                              authorization_code (checks the PKCE verifier) and refresh_token grants
  /admin/revoke-all                   POST: invalidates every token, to test re-login

Gateway (http://127.0.0.1:9401):
  /health                             200 with a valid bearer token, 401 otherwise
  /admin/stats                        what the gateway has seen (for assertions)

Tokens are opaque-ish JWTs signed by nobody; this is a test double, never expose it beyond localhost.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

CLIENT_ID = "ctem-plugin-test"
USER = {"sub": "user-1", "email": "analyst@example.com"}


class State:
    def __init__(self, access_ttl: int, issuer: str) -> None:
        self.access_ttl = access_ttl
        self.issuer = issuer
        self.lock = threading.Lock()
        self.codes: dict[str, dict] = {}
        self.access: dict[str, float] = {}  # token -> expiry
        self.refresh: set[str] = set()
        self.stats = {"logins": 0, "refreshes": 0, "health_ok": 0, "health_401": 0}

    def issue(self) -> dict:
        now = time.time()
        access = f"at-{secrets.token_urlsafe(16)}"
        refresh = f"rt-{secrets.token_urlsafe(16)}"
        self.access[access] = now + self.access_ttl
        self.refresh.add(refresh)
        claims = {**USER, "iss": self.issuer, "aud": CLIENT_ID, "iat": int(now), "exp": int(now) + 3600}
        enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
        return {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": self.access_ttl,
            "refresh_token": refresh,
            "id_token": f"{enc({'alg': 'none', 'typ': 'JWT'})}.{enc(claims)}.",
        }


def make_idp(state: State):
    class IdP(BaseHTTPRequestHandler):
        def log_message(self, *a) -> None:  # quiet
            pass

        def _json(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            if url.path == "/.well-known/openid-configuration":
                return self._json(200, {
                    "issuer": state.issuer,
                    "authorization_endpoint": f"{state.issuer}/authorize",
                    "token_endpoint": f"{state.issuer}/token",
                    "code_challenge_methods_supported": ["S256"],
                })
            if url.path == "/authorize":
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                redirect = q.get("redirect_uri", "")
                if q.get("client_id") != CLIENT_ID:
                    return self._json(400, {"error": "invalid_client", "error_description": "Unknown client_id"})
                if not redirect.startswith("http://localhost:") or not redirect.endswith("/callback"):
                    return self._json(400, {"error": "invalid_request", "error_description": "Bad redirect_uri"})
                if q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
                    return self._json(400, {"error": "invalid_request", "error_description": "PKCE S256 required"})
                code = secrets.token_urlsafe(16)
                with state.lock:
                    state.codes[code] = {"challenge": q["code_challenge"], "redirect_uri": redirect}
                self.send_response(302)
                self.send_header("Location", f"{redirect}?{urlencode({'code': code, 'state': q.get('state', '')})}")
                self.end_headers()
                return None
            return self._json(404, {"error": "not_found"})

        def do_POST(self) -> None:
            url = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
            if url.path == "/admin/revoke-all":
                with state.lock:
                    state.access.clear()
                    state.refresh.clear()
                return self._json(200, {"revoked": True})
            if url.path != "/token":
                return self._json(404, {"error": "not_found"})
            if form.get("client_id") != CLIENT_ID:
                return self._json(401, {"error": "invalid_client"})
            with state.lock:
                if form.get("grant_type") == "authorization_code":
                    entry = state.codes.pop(form.get("code", ""), None)
                    verifier = form.get("code_verifier", "")
                    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
                    if not entry or entry["challenge"] != challenge.decode():
                        return self._json(400, {"error": "invalid_grant", "error_description": "Bad code or PKCE"})
                    if entry["redirect_uri"] != form.get("redirect_uri"):
                        return self._json(400, {"error": "invalid_grant", "error_description": "redirect_uri mismatch"})
                    state.stats["logins"] += 1
                    return self._json(200, state.issue())
                if form.get("grant_type") == "refresh_token":
                    if form.get("refresh_token") not in state.refresh:
                        return self._json(400, {"error": "invalid_grant", "error_description": "Refresh token revoked"})
                    state.refresh.discard(form["refresh_token"])  # rotate
                    state.stats["refreshes"] += 1
                    return self._json(200, state.issue())
            return self._json(400, {"error": "unsupported_grant_type"})

    return IdP


def make_gateway(state: State):
    class Gateway(BaseHTTPRequestHandler):
        def log_message(self, *a) -> None:
            pass

        def _json(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/admin/stats":
                return self._json(200, state.stats)
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            with state.lock:
                valid = state.access.get(token, 0) > time.time()
                if path == "/health":
                    state.stats["health_ok" if valid else "health_401"] += 1
            if not valid:
                return self._json(401, {"error": "invalid_token"})
            if path == "/health":
                return self._json(200, {"status": "UP"})
            return self._json(404, {"error": "not_found"})

    return Gateway


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--idp-port", type=int, default=9400)
    ap.add_argument("--gateway-port", type=int, default=9401)
    ap.add_argument("--access-ttl", type=int, default=3600, help="access token lifetime in seconds")
    args = ap.parse_args()
    state = State(args.access_ttl, f"http://127.0.0.1:{args.idp_port}")
    servers = [
        ThreadingHTTPServer(("127.0.0.1", args.idp_port), make_idp(state)),
        ThreadingHTTPServer(("127.0.0.1", args.gateway_port), make_gateway(state)),
    ]
    for s in servers:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    print(f"fake IdP      {state.issuer}  (client_id {CLIENT_ID})", flush=True)
    print(f"fake gateway  http://127.0.0.1:{args.gateway_port}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
