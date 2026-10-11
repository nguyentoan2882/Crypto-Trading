from __future__ import annotations

import html
import json
import os
import secrets
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Callable
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from app.nxt_cloud.auth import AuthError, Principal, SupabaseJwtVerifier, TokenVerifier, authenticate, enforce_csrf, enforce_origin
from app.nxt_cloud.config import CloudConfig
from app.nxt_cloud.contracts import CloudRepository
from app.nxt_cloud.postgres import PostgresRepository
from app.nxt_cloud.quantity import render_quantity_calculator, signal_button


MAX_BODY_BYTES = 65_536
ICT = ZoneInfo("Asia/Ho_Chi_Minh")
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


def _format_ict(value: object) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, datetime):
        timestamp = value
    else:
        text = str(value)
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            return text
        try:
            timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(ICT).strftime("%Y-%m-%d %H:%M ICT")


def _dashboard_html(state: dict, environment: str) -> str:
    followups = list(state.get("followupRecommendations", []))
    decisions = {
        str(item.get("signal_id", "")): str(item.get("decision", ""))
        for item in state.get("decisions", [])
        if item.get("signal_id")
    }
    terminal_signal_ids = {
        str(item.get("signal_id") or item.get("payload", {}).get("signalId") or "")
        for item in followups
        if str(item.get("action") or item.get("payload", {}).get("action") or "")
        in {"STOP_LOSS", "BE_STOP", "TAIL_EXIT_EMA50", "TAIL_EXIT_SSL", "MANUAL_CLOSE"}
        and str(item.get("status") or item.get("payload", {}).get("status") or "") == "Acknowledged"
        and str(item.get("outcome") or item.get("payload", {}).get("outcome") or "") in {"Applied", "Already Closed"}
    }
    manually_closed_signal_ids = {
        str(item.get("signal_id") or item.get("payload", {}).get("signalId") or "")
        for item in followups
        if str(item.get("action") or item.get("payload", {}).get("action") or "") == "MANUAL_CLOSE"
        and str(item.get("status") or item.get("payload", {}).get("status") or "") == "Acknowledged"
        and str(item.get("outcome") or item.get("payload", {}).get("outcome") or "") == "Already Closed"
    }
    pending_signal_actions = []
    rows = []
    for item in list(state.get("signals", []))[:50]:
        payload = item.get("payload", item)
        signal_id = str(item.get("signal_id") or payload.get("id") or "")
        entry = float(payload.get("entryPrice", 0))
        stop = float(payload.get("initialStop", 0))
        signal_date = _format_ict(payload.get("signalDate") or item.get("signal_date"))
        detected_at = _format_ict(payload.get("detectedAt") or item.get("created_at"))
        decision = decisions.get(signal_id, "Pending")
        display_decision = "Closed manually" if signal_id in manually_closed_signal_ids else decision
        if decision == "Pending":
            escaped_id = html.escape(signal_id, quote=True)
            pending_signal_actions.append(
                '<article class="action-card">'
                '<div><span class="eyebrow">NEW SIGNAL</span>'
                f"<h3>{html.escape(str(payload.get('symbol', '')))} · {html.escape(str(payload.get('side', '')))}</h3>"
                f"<p>{html.escape(str(payload.get('signalType', '')))}</p>"
                f'<p class="time-meta">Signal D1: {html.escape(signal_date)} · Phát hiện: {html.escape(detected_at)}</p></div>'
                '<div class="action-buttons">'
                f'<button class="decision primary" data-signal-id="{escaped_id}" data-decision="Accept">Accept</button>'
                f'<button class="decision" data-signal-id="{escaped_id}" data-decision="Watchlist">Watchlist</button>'
                f'<button class="decision danger" data-signal-id="{escaped_id}" data-decision="Reject">Reject</button>'
                "</div></article>"
            )
        close_button = ""
        if decision == "Accept" and signal_id not in terminal_signal_ids:
            close_button = f'<button class="manual-close danger" data-signal-id="{html.escape(signal_id, quote=True)}">Đóng thủ công</button>'
        rows.append(
            "<tr>"
            f'<td data-label="Symbol">{html.escape(str(payload.get("symbol", "")))}</td>'
            f'<td data-label="Side">{html.escape(str(payload.get("side", "")))}</td>'
            f'<td data-label="Signal / phát hiện"><b>{html.escape(signal_date)}</b><br><span class="time-meta">{html.escape(detected_at)}</span></td>'
            f'<td data-label="Entry">{entry}</td><td data-label="Stop">{stop}</td>'
            f'<td data-label="Decision"><span class="status-chip {"pending" if display_decision == "Pending" else ""}">{html.escape(display_decision)}</span></td>'
            f'<td data-label="Quantity"><div class="row-actions">{signal_button(signal_id, entry, stop)}{close_button}</div></td>'
            "</tr>"
        )

    followup_cards = []
    pending_followup_count = 0
    for item in followups:
        payload = item.get("payload", item)
        status = str(item.get("status") or payload.get("status") or "Pending")
        action = str(item.get("action") or payload.get("action") or "")
        # Match the local dashboard: DATA_STALE and NO_ACTION remain available
        # in history/audit, but they are not operator actions.
        if action in {"DATA_STALE", "NO_ACTION"}:
            continue
        if status in {"Pending", "Reminder"}:
            pending_followup_count += 1
        recommendation_id = str(item.get("recommendation_id") or payload.get("recommendationId") or "")
        escaped_id = html.escape(recommendation_id, quote=True)
        candle_date = _format_ict(payload.get("candleDate") or item.get("candle_date"))
        created_at = _format_ict(item.get("created_at") or payload.get("createdAt"))
        outcome = str(item.get("outcome") or status)
        controls = ""
        if status == "Pending":
            controls = (
                '<div class="action-buttons">'
                f'<button class="followup-outcome primary" data-recommendation-id="{escaped_id}" data-outcome="Applied">Applied</button>'
                f'<button class="followup-outcome" data-recommendation-id="{escaped_id}" data-outcome="Not Applied">Not applied</button>'
                f'<button class="followup-outcome" data-recommendation-id="{escaped_id}" data-outcome="Snoozed">Snooze</button>'
                f'<button class="followup-outcome" data-recommendation-id="{escaped_id}" data-outcome="Already Closed">Closed</button>'
                '</div>'
            )
        if len(followup_cards) < 5:
            followup_cards.append(
                '<article class="action-card followup">'
                '<div><span class="eyebrow">FOLLOW-UP</span>'
                f"<h3>{html.escape(str(payload.get('symbol', '')))} · {html.escape(str(payload.get('side', '')))}</h3>"
                f"<p><b>{html.escape(str(payload.get('actionLabel') or action))}</b></p>"
                f"<p>{html.escape(str(payload.get('rationale', '')))}</p>"
                f'<p class="time-meta">Nến D1: {html.escape(candle_date)} · Tạo: {html.escape(created_at)}</p>'
                f'<p class="time-meta"><b>{html.escape(outcome)}</b></p></div>{controls}</article>'
            )

    actions = pending_signal_actions + followup_cards
    action_content = "".join(actions) if actions else '<div class="empty">Không có action đang chờ.</div>'
    action_count = len(pending_signal_actions) + pending_followup_count
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>NXT Cloud Shadow</title><style>
*,*::before,*::after{{box-sizing:border-box}}html,body{{max-width:100%;overflow-x:hidden}}body{{font-family:Arial,sans-serif;width:auto;max-width:1180px;margin:30px auto;padding:0 20px;color:#17212b;background:#f7f9fb}}.banner{{max-width:100%;background:#fff3cd;border:1px solid #e5bd57;padding:14px;overflow-wrap:anywhere}}h1{{margin:28px 0 8px}}h2{{margin:0}}.sub{{color:#637083;margin-top:6px}}.panel{{min-width:0;background:#fff;border:1px solid #dce2e8;border-radius:12px;padding:20px;margin-top:22px}}.panel-heading{{display:flex;justify-content:space-between;gap:16px;align-items:center}}.status-chip{{display:inline-block;padding:5px 9px;border-radius:999px;background:#e8f3f1;color:#176b62;font-size:13px;font-weight:700;white-space:nowrap}}.status-chip.pending{{background:#fff0cc;color:#8b5a00}}.actions{{display:grid;gap:12px;margin-top:16px;min-width:0}}.action-card{{display:flex;justify-content:space-between;gap:20px;align-items:center;min-width:0;border:1px solid #dce2e8;border-left:5px solid #e5a927;border-radius:9px;padding:15px}}.action-card>div{{min-width:0}}.action-card.followup{{border-left-color:#287e73}}.action-card h3,.action-card p{{margin:4px 0;overflow-wrap:anywhere}}.eyebrow{{font-size:12px;font-weight:800;letter-spacing:.08em;color:#637083}}.time-meta{{color:#637083;font-size:12px;font-variant-numeric:tabular-nums}}.action-buttons,.row-actions{{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end}}button{{max-width:100%;padding:9px 13px;border:1px solid #aeb9c2;border-radius:6px;background:#fff;cursor:pointer}}button.primary{{background:#287e73;color:#fff;border-color:#287e73}}button.danger{{color:#a42b2b;border-color:#d7a6a6}}button:disabled{{opacity:.55;cursor:wait}}.table-wrap{{width:100%;min-width:0;overflow-x:auto}}table{{width:100%;border-collapse:collapse;margin-top:16px}}td,th{{padding:11px 9px;border-bottom:1px solid #ddd;text-align:left;overflow-wrap:anywhere}}dialog{{width:min(620px,calc(100vw - 28px));max-width:620px;border:0;border-radius:8px;padding:20px}}label{{display:block;margin:10px 0}}input{{display:block;width:100%;padding:8px}}.empty{{padding:24px;text-align:center;color:#637083;background:#f7f9fb;border-radius:8px}}#action-status{{min-height:20px;margin-top:12px;color:#176b62}}
@media(max-width:760px){{body{{width:100%;max-width:none;margin:0;padding:12px}}h1{{font-size:30px;margin:22px 0 6px}}.banner{{padding:12px;font-size:14px;line-height:1.45}}.panel{{padding:14px;margin-top:16px;border-radius:10px}}.panel-heading{{align-items:flex-start}}.panel-heading .status-chip{{flex:0 0 auto}}.action-card{{align-items:flex-start;flex-direction:column;gap:12px;padding:13px}}.action-card>div{{width:100%}}.action-buttons{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));justify-content:stretch;width:100%}}.action-buttons button{{width:100%;min-width:0}}.table-wrap{{overflow:visible}}table,tbody,tr,td{{display:block;width:100%}}thead{{display:none}}table{{margin-top:12px}}tbody{{display:grid;gap:12px}}tr{{display:block;border:1px solid #dce2e8;border-radius:9px;padding:8px 12px;background:#fff}}td{{display:grid;grid-template-columns:minmax(105px,38%) minmax(0,1fr);gap:10px;align-items:center;padding:8px 0;border:0}}td::before{{content:attr(data-label);color:#637083;font-size:12px;font-weight:700}}td+td{{border-top:1px solid #eef1f3}}td button{{width:100%}}.empty{{padding:18px 12px}}}}
</style></head><body><div class="banner"><b>[NXT-CLOUD][{html.escape(environment)}]</b> Testing only — local NXT remains official. Recommendation-only; no order execution.</div><h1>NXT Cloud Shadow</h1><p class="sub">Trading decision desk · dữ liệu Supabase SHADOW</p><section class="panel" id="action-center"><div class="panel-heading"><div><h2>Action Center</h2><p class="sub">Xử lý tín hiệu mới và follow-up đang chờ xác nhận.</p></div><span class="status-chip pending">{action_count} pending</span></div><div class="actions">{action_content}</div><div id="action-status"></div></section><section class="panel"><div class="panel-heading"><div><h2>Tín hiệu</h2><p class="sub">Lịch sử tín hiệu và quyết định mới nhất.</p></div><span class="status-chip">{len(rows)} signals</span></div><div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Side</th><th>Signal / phát hiện</th><th>Entry</th><th>Stop</th><th>Decision</th><th>Quantity</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>{render_quantity_calculator()}<script>
(()=>{{const status=document.getElementById('action-status'),cookie=name=>document.cookie.split('; ').find(row=>row.startsWith(name+'='))?.split('=').slice(1).join('=')||'',post=async(path,body)=>{{status.textContent='Đang ghi nhận...';const response=await fetch(path,{{method:'POST',headers:{{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(cookie('nxt_csrf')),'Idempotency-Key':crypto.randomUUID()}},body:JSON.stringify(body)}}),data=await response.json().catch(()=>({{}}));if(!response.ok)throw new Error(data.error||'HTTP '+response.status);return data}},run=async(button,task)=>{{document.querySelectorAll('button').forEach(item=>item.disabled=true);try{{await task();status.textContent='Đã ghi nhận. Đang tải lại...';location.reload()}}catch(error){{status.textContent='Không thể ghi nhận: '+error.message;document.querySelectorAll('button').forEach(item=>item.disabled=false)}}}};document.querySelectorAll('.decision').forEach(button=>button.addEventListener('click',()=>run(button,()=>post('/api/decisions',{{signalId:button.dataset.signalId,decision:button.dataset.decision,note:''}}))));document.querySelectorAll('.followup-outcome').forEach(button=>button.addEventListener('click',()=>run(button,()=>post('/api/followups/'+encodeURIComponent(button.dataset.recommendationId)+'/outcome',{{outcome:button.dataset.outcome}}))));document.querySelectorAll('.manual-close').forEach(button=>button.addEventListener('click',()=>{{const rawPrice=prompt('Giá đóng (không bắt buộc):','');if(rawPrice===null)return;const value=rawPrice.trim(),closePrice=value===''?null:Number(value);if(closePrice!==null&&(!Number.isFinite(closePrice)||closePrice<=0)){{status.textContent='Giá đóng phải là số dương.';return}}const note=prompt('Lý do đóng (không bắt buộc):','');if(note===null)return;if(!confirm('Xác nhận đóng thủ công tín hiệu này? Thao tác chỉ ghi nhận trạng thái, không gửi lệnh Binance.'))return;run(button,()=>post('/api/manual-close',{{signalId:button.dataset.signalId,closePrice,note:note.trim()}}))}}))}})();
</script></body></html>"""


def _login_html(config: CloudConfig) -> str:
    supabase_url = json.dumps(config.supabase_url).replace("</", "<\\/")
    publishable_key = json.dumps(config.supabase_publishable_key).replace("</", "<\\/")
    return f"""<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>NXT Cloud Shadow — Đăng nhập</title><style>body{{font:16px system-ui;max-width:560px;margin:48px auto;padding:0 20px;color:#17212b}}.card{{border:1px solid #dce2e8;border-radius:10px;padding:24px}}.banner{{background:#fff3cd;border:1px solid #e5bd57;padding:12px;margin-bottom:20px}}label{{display:block;margin:14px 0 5px}}input,button{{font:inherit;padding:10px;width:100%;box-sizing:border-box}}button{{margin-top:18px;background:#087f75;color:#fff;border:0;border-radius:6px;font-weight:700;cursor:pointer}}button:disabled{{opacity:.55}}#status{{white-space:pre-wrap;background:#f5f7f8;padding:12px;border-radius:6px;margin-top:16px}}small{{color:#637083}}</style></head><body><div class="banner"><b>[NXT-CLOUD][SHADOW]</b> Testing only — local NXT remains official.</div><main class="card"><h1>Đăng nhập NXT</h1><p>Chỉ tài khoản owner đã được mời mới được truy cập.</p><label>Email owner</label><input id="email" type="email" autocomplete="username" required><label>Mật khẩu Supabase Auth</label><input id="password" type="password" autocomplete="current-password" required><button id="sign-in">Đăng nhập</button><div id="status">Chưa đăng nhập.</div><p><small>Mật khẩu được trình duyệt gửi trực tiếp tới Supabase. Cloud Run chỉ nhận access token đã xác thực để tạo cookie HttpOnly ngắn hạn.</small></p></main><script>(()=>{{const base={supabase_url},key={publishable_key},status=document.getElementById('status');const headers={{'Content-Type':'application/json','apikey':key}};document.getElementById('sign-in').addEventListener('click',async()=>{{const button=document.getElementById('sign-in');button.disabled=true;status.textContent='Đang xác minh mật khẩu...';try{{const email=document.getElementById('email').value.trim(),password=document.getElementById('password').value;const response=await fetch(base+'/auth/v1/token?grant_type=password',{{method:'POST',headers,body:JSON.stringify({{email,password}})}}),signed=await response.json().catch(()=>({{}}));document.getElementById('password').value='';if(!response.ok)throw new Error(signed.msg||signed.message||signed.error_description||'HTTP '+response.status);const session=await fetch('/auth/session',{{method:'POST',headers:{{'Authorization':'Bearer '+signed.access_token,'Content-Type':'application/json'}},body:'{{}}'}});if(!session.ok){{const detail=await session.json().catch(()=>({{}}));throw new Error(detail.error||'Cloud session HTTP '+session.status)}}status.textContent='Đăng nhập thành công. Đang mở dashboard...';location.replace('/')}}catch(error){{status.textContent='Đăng nhập thất bại: '+error.message;button.disabled=false}}}})}})();</script></body></html>"""


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
            return self._route(method, path, environ, principal, start_response)
        except AuthError as exc:
            return _respond(start_response, HTTPStatus.UNAUTHORIZED, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError) as exc:
            return _respond(start_response, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except KeyError as exc:
            return _respond(start_response, HTTPStatus.BAD_REQUEST, {"error": f"missing field: {exc.args[0]}"})
        except Exception:
            return _respond(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal server error"})

    def _route(self, method: str, path: str, environ: dict, principal: Principal, start_response: Callable) -> list[bytes]:
        owner_id = principal.user_id
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
            return _respond(start_response, HTTPStatus.OK, {"authenticated": True, "owner": owner_id, "aal": principal.assurance_level}, extra_headers=cookie_headers)
        if method == "GET" and path == "/":
            page = _dashboard_html(dict(self.repository.dashboard_state(owner_id)), self.config.environment)
            return _respond(start_response, HTTPStatus.OK, page, "text/html; charset=utf-8")
        if method == "GET" and path == "/api/state":
            return _respond(start_response, HTTPStatus.OK, self.repository.dashboard_state(owner_id))
        list_routes = {"/api/signals": "signals", "/api/scans": "scans", "/api/followups": "followups"}
        if method == "GET" and path in list_routes:
            limit, offset = _pagination(environ)
            return _respond(start_response, HTTPStatus.OK, {"items": self.repository.list_records(list_routes[path], owner_id, limit, offset), "limit": limit, "offset": offset})
        if method == "POST" and path in {"/api/decisions", "/api/positions", "/api/manual-close"}:
            key = environ.get("HTTP_IDEMPOTENCY_KEY", "").strip()
            if not key or len(key) > 160:
                raise ValueError("a valid Idempotency-Key header is required")
            payload = _read_json(environ)
            if path == "/api/decisions":
                result = self.repository.record_decision(owner_id, payload, key)
            elif path == "/api/positions":
                result = self.repository.track_position(owner_id, payload, key)
            else:
                result = self.repository.close_accepted_signal(owner_id, payload, key)
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
