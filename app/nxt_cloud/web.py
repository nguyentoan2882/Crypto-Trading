from __future__ import annotations

import html
import json
import os
from http import HTTPStatus
from typing import Callable
from urllib.parse import parse_qs

from app.nxt_cloud.auth import AuthError, SupabaseJwtVerifier, TokenVerifier, authenticate, enforce_csrf, enforce_origin
from app.nxt_cloud.config import CloudConfig
from app.nxt_cloud.contracts import CloudRepository
from app.nxt_cloud.postgres import PostgresRepository
from app.nxt_cloud.quantity import render_quantity_calculator, signal_button


MAX_BODY_BYTES = 65_536
SECURITY_HEADERS = [
    ("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Cache-Control", "no-store"),
]


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def _respond(start_response: Callable, status: HTTPStatus, payload: object, content_type: str = "application/json; charset=utf-8") -> list[bytes]:
    body = payload.encode("utf-8") if isinstance(payload, str) else _json_bytes(payload)
    headers = [("Content-Type", content_type), ("Content-Length", str(len(body))), *SECURITY_HEADERS]
    start_response(f"{status.value} {status.phrase}", headers)
    return [body]


def _read_json(environ: dict) -> dict:
    try:
        length = int(environ.get("CONTENT_LENGTH", "0") or 0)
    except ValueError as exc:
        raise ValueError("invalid Content-Length") from exc
    if length <= 0 or length > MAX_BODY_BYTES:
        raise ValueError("request body must be between 1 and 65536 bytes")
    raw = environ["wsgi.input"].read(length)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


def _pagination(environ: dict) -> tuple[int, int]:
    query = parse_qs(environ.get("QUERY_STRING", ""))
    limit = min(max(int(query.get("limit", ["50"])[0]), 1), 100)
    offset = max(int(query.get("offset", ["0"])[0]), 0)
    return limit, offset


def _dashboard_html(state: dict, environment: str) -> str:
    rows = []
    for item in list(state.get("signals", []))[:50]:
        payload = item.get("payload", item)
        signal_id = str(item.get("signal_id") or payload.get("id") or "")
        entry = float(payload.get("entryPrice", 0))
        stop = float(payload.get("initialStop", 0))
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(payload.get('symbol', '')))}</td>"
            f"<td>{html.escape(str(payload.get('side', '')))}</td>"
            f"<td>{entry}</td><td>{stop}</td>"
            f"<td>{signal_button(signal_id, entry, stop)}</td>"
            "</tr>"
        )
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>NXT Cloud Shadow</title><style>body{{font-family:Arial,sans-serif;max-width:1100px;margin:30px auto;padding:0 20px;color:#17212b}}.banner{{background:#fff3cd;border:1px solid #e5bd57;padding:12px}}table{{width:100%;border-collapse:collapse;margin-top:20px}}td,th{{padding:9px;border-bottom:1px solid #ddd;text-align:left}}dialog{{max-width:620px;border:0;border-radius:8px;padding:20px}}label{{display:block;margin:10px 0}}input{{display:block;width:100%;padding:8px}}button{{padding:8px 12px}}</style></head><body><div class="banner"><b>[NXT-CLOUD][{html.escape(environment)}]</b> Testing only — local NXT remains official. Recommendation-only; no order execution.</div><h1>NXT Cloud Shadow</h1><table><thead><tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Stop</th><th>Quantity</th></tr></thead><tbody>{''.join(rows)}</tbody></table>{render_quantity_calculator()}</body></html>"""


class CloudWebApp:
    def __init__(self, config: CloudConfig, repository: CloudRepository, verifier: TokenVerifier) -> None:
        self.config = config
        self.repository = repository
        self.verifier = verifier

    def __call__(self, environ: dict, start_response: Callable) -> list[bytes]:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "/")
        if method == "GET" and path == "/healthz":
            return _respond(start_response, HTTPStatus.OK, {"alive": True, "environment": "SHADOW"})
        if method == "GET" and path == "/readyz":
            if self.config.health_token and environ.get("HTTP_X_NXT_HEALTH_TOKEN", "") != self.config.health_token:
                return _respond(start_response, HTTPStatus.UNAUTHORIZED, {"ready": False})
            ready = bool(self.repository.ping() and self.repository.schema_current())
            return _respond(start_response, HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE, {"ready": ready})

        try:
            principal = authenticate(environ, self.verifier, self.config)
            if method not in {"GET", "HEAD", "OPTIONS"}:
                if principal.auth_mode == "cookie" and not environ.get("HTTP_ORIGIN", ""):
                    raise AuthError("origin is required for cookie-authenticated writes")
                enforce_origin(environ, self.config)
                enforce_csrf(environ, principal)
            return self._route(method, path, environ, principal.user_id, start_response)
        except AuthError as exc:
            return _respond(start_response, HTTPStatus.UNAUTHORIZED, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            return _respond(start_response, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except KeyError as exc:
            return _respond(start_response, HTTPStatus.BAD_REQUEST, {"error": f"missing field: {exc.args[0]}"})
        except Exception:
            return _respond(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal server error"})

    def _route(self, method: str, path: str, environ: dict, owner_id: str, start_response: Callable) -> list[bytes]:
        if method == "GET" and path == "/":
            page = _dashboard_html(dict(self.repository.dashboard_state(owner_id)), self.config.environment)
            return _respond(start_response, HTTPStatus.OK, page, "text/html; charset=utf-8")
        if method == "GET" and path == "/api/state":
            return _respond(start_response, HTTPStatus.OK, self.repository.dashboard_state(owner_id))
        list_routes = {"/api/signals": "signals", "/api/scans": "scans", "/api/followups": "followups"}
        if method == "GET" and path in list_routes:
            limit, offset = _pagination(environ)
            return _respond(start_response, HTTPStatus.OK, {"items": self.repository.list_records(list_routes[path], owner_id, limit, offset), "limit": limit, "offset": offset})
        if method == "POST" and path in {"/api/decisions", "/api/positions"}:
            key = environ.get("HTTP_IDEMPOTENCY_KEY", "").strip()
            if not key or len(key) > 160:
                raise ValueError("a valid Idempotency-Key header is required")
            payload = _read_json(environ)
            result = self.repository.record_decision(owner_id, payload, key) if path.endswith("decisions") else self.repository.track_position(owner_id, payload, key)
            return _respond(start_response, HTTPStatus.OK, result)
        prefix, suffix = "/api/followups/", "/outcome"
        if method == "POST" and path.startswith(prefix) and path.endswith(suffix):
            recommendation_id = path[len(prefix) : -len(suffix)]
            if not recommendation_id or "/" in recommendation_id:
                raise ValueError("invalid recommendation id")
            key = environ.get("HTTP_IDEMPOTENCY_KEY", "").strip()
            if not key or len(key) > 160:
                raise ValueError("a valid Idempotency-Key header is required")
            result = self.repository.record_followup_outcome(owner_id, recommendation_id, _read_json(environ), key)
            return _respond(start_response, HTTPStatus.OK, result)
        return _respond(start_response, HTTPStatus.NOT_FOUND, {"error": "not found"})


def create_app(config: CloudConfig | None = None, repository: CloudRepository | None = None, verifier: TokenVerifier | None = None) -> CloudWebApp:
    cfg = config or CloudConfig.from_env()
    repo = repository or PostgresRepository(cfg.database_url)
    token_verifier = verifier or SupabaseJwtVerifier(cfg.jwt_issuer, cfg.jwt_audience, cfg.jwt_jwks_url)
    return CloudWebApp(cfg, repo, token_verifier)


def gunicorn_options(config: CloudConfig) -> dict[str, object]:
    return {
        "bind": f"0.0.0.0:{config.port}",
        "workers": int(os.environ.get("WEB_CONCURRENCY", "1")),
        "threads": int(os.environ.get("WEB_THREADS", "4")),
        "timeout": 30,
        "graceful_timeout": 20,
        "accesslog": "-",
        "errorlog": "-",
    }
