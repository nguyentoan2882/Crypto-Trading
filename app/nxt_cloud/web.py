from __future__ import annotations

import html
import json
import os
import secrets
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


def _respond(
    start_response: Callable,
    status: HTTPStatus,
    payload: object,
    content_type: str = "application/json; charset=utf-8",
    extra_headers: list[tuple[str, str]] | None = None,
    content_security_policy: str | None = None,
) -> list[bytes]:
    body = payload.encode("utf-8") if isinstance(payload, str) else _json_bytes(payload)
    security_headers = [
        (name, content_security_policy if name == "Content-Security-Policy" and content_security_policy else value)
        for name, value in SECURITY_HEADERS
    ]
    headers = [("Content-Type", content_type), ("Content-Length", str(len(body))), *security_headers, *(extra_headers or [])]
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


def _login_html(config: CloudConfig) -> str:
    supabase_url = json.dumps(config.supabase_url).replace("</", "<\\/")
    publishable_key = json.dumps(config.supabase_publishable_key).replace("</", "<\\/")
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>NXT Cloud Shadow — Đăng nhập</title><style>body{{font:16px system-ui;max-width:560px;margin:48px auto;padding:0 20px;color:#17212b}}.card{{border:1px solid #dce2e8;border-radius:10px;padding:24px}}.banner{{background:#fff3cd;border:1px solid #e5bd57;padding:12px;margin-bottom:20px}}label{{display:block;margin:14px 0 5px}}input,button{{font:inherit;padding:10px;width:100%;box-sizing:border-box}}button{{margin-top:18px;background:#087f75;color:#fff;border:0;border-radius:6px;font-weight:700;cursor:pointer}}button:disabled{{opacity:.55}}#totp-step{{display:none}}#status{{white-space:pre-wrap;background:#f5f7f8;padding:12px;border-radius:6px;margin-top:16px}}small{{color:#637083}}</style></head><body><div class="banner"><b>[NXT-CLOUD][SHADOW]</b> Testing only — local NXT remains official.</div><main class="card"><h1>Đăng nhập NXT</h1><p>Chỉ tài khoản owner đã được mời và xác minh TOTP MFA mới được truy cập.</p><section id="password-step"><label>Email owner</label><input id="email" type="email" autocomplete="username" required><label>Mật khẩu Supabase Auth</label><input id="password" type="password" autocomplete="current-password" required><button id="sign-in">Tiếp tục</button></section><section id="totp-step"><label>Mã TOTP 6 số</label><input id="totp" inputmode="numeric" autocomplete="one-time-code" maxlength="8" required><button id="verify">Xác minh MFA</button></section><div id="status">Chưa đăng nhập.</div><p><small>Mật khẩu và mã TOTP được trình duyệt gửi trực tiếp tới Supabase. Cloud Run chỉ nhận access token đã đạt aal2 để tạo cookie HttpOnly ngắn hạn.</small></p></main><script>(()=>{{const base={supabase_url},key={publishable_key},status=document.getElementById('status'),passwordStep=document.getElementById('password-step'),totpStep=document.getElementById('totp-step');let accessToken='',factorId='';const headers=token=>({{'Content-Type':'application/json','apikey':key,...(token?{{'Authorization':'Bearer '+token}}:{{}})}});async function request(path,options={{}}){{const response=await fetch(base+'/auth/v1'+path,options),data=await response.json().catch(()=>({{}}));if(!response.ok)throw new Error(data.msg||data.message||data.error_description||'HTTP '+response.status);return data}}document.getElementById('sign-in').addEventListener('click',async()=>{{const button=document.getElementById('sign-in');button.disabled=true;status.textContent='Đang xác minh mật khẩu...';try{{const email=document.getElementById('email').value.trim(),password=document.getElementById('password').value;const signed=await request('/token?grant_type=password',{{method:'POST',headers:headers(),body:JSON.stringify({{email,password}})}});document.getElementById('password').value='';accessToken=signed.access_token;const factors=(signed.user&&signed.user.factors)||[];const factor=factors.find(item=>item.factor_type==='totp'&&item.status==='verified');if(!factor)throw new Error('Tài khoản chưa có TOTP factor đã xác minh.');factorId=factor.id;passwordStep.style.display='none';totpStep.style.display='block';document.getElementById('totp').focus();status.textContent='Mật khẩu đúng. Hãy nhập mã TOTP.'}}catch(error){{accessToken='';status.textContent='Đăng nhập thất bại: '+error.message}}finally{{button.disabled=false}}}});document.getElementById('verify').addEventListener('click',async()=>{{const button=document.getElementById('verify');button.disabled=true;status.textContent='Đang xác minh MFA...';try{{const code=document.getElementById('totp').value.trim();document.getElementById('totp').value='';const challenged=await request('/factors/'+encodeURIComponent(factorId)+'/challenge',{{method:'POST',headers:headers(accessToken),body:'{{}}'}});const verified=await request('/factors/'+encodeURIComponent(factorId)+'/verify',{{method:'POST',headers:headers(accessToken),body:JSON.stringify({{challenge_id:challenged.id,code}})}});accessToken=verified.access_token;const session=await fetch('/auth/session',{{method:'POST',headers:{{'Authorization':'Bearer '+accessToken,'Content-Type':'application/json'}},body:'{{}}'}});if(!session.ok){{const detail=await session.json().catch(()=>({{}}));throw new Error(detail.error||'Cloud session HTTP '+session.status)}}accessToken='';status.textContent='MFA đạt aal2. Đang mở dashboard...';location.replace('/')}}catch(error){{status.textContent='Xác minh thất bại: '+error.message;button.disabled=false}}}})}})();</script></body></html>"""


class CloudWebApp:
    def __init__(self, config: CloudConfig, repository: CloudRepository, verifier: TokenVerifier) -> None:
        self.config = config
        self.repository = repository
        self.verifier = verifier

    def __call__(self, environ: dict, start_response: Callable) -> list[bytes]:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "/")
        if method == "GET" and path in {"/healthz", "/health"}:
            return _respond(start_response, HTTPStatus.OK, {"alive": True, "environment": "SHADOW"})
        if method == "GET" and path in {"/readyz", "/ready"}:
            if self.config.health_token and environ.get("HTTP_X_NXT_HEALTH_TOKEN", "") != self.config.health_token:
                return _respond(start_response, HTTPStatus.UNAUTHORIZED, {"ready": False})
            ready = bool(self.repository.ping() and self.repository.schema_current())
            return _respond(start_response, HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE, {"ready": ready})
        if method == "GET" and path == "/login":
            if not self.config.supabase_url or not self.config.supabase_publishable_key:
                return _respond(start_response, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "browser login is not configured"})
            login_csp = (
                "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                f"connect-src 'self' {self.config.supabase_url}; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            )
            return _respond(start_response, HTTPStatus.OK, _login_html(self.config), "text/html; charset=utf-8", content_security_policy=login_csp)

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
        if method == "POST" and path == "/auth/session":
            authorization = environ.get("HTTP_AUTHORIZATION", "")
            token = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
            if not token:
                raise AuthError("bearer token is required")
            csrf_token = secrets.token_urlsafe(32)
            cookie_headers = [
                ("Set-Cookie", f"nxt_csrf={csrf_token}; Path=/; Secure; SameSite=Strict; Max-Age=3600"),
                ("Set-Cookie", f"__Host-nxt_session={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=3600"),
            ]
            return _respond(start_response, HTTPStatus.OK, {"authenticated": True, "owner": owner_id, "aal": "aal2"}, extra_headers=cookie_headers)
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
