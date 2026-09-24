from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.nxt_cloud.config import CloudConfig
from app.nxt_cloud.contracts import CloudRepository, MarketData, NotificationOutbox
from app.nxt_core import rules
from app.nxt_core.telegram_messages import build_entry_message, build_followup_message_batches


ICT = ZoneInfo("Asia/Ho_Chi_Minh")


class DataGateError(RuntimeError):
    pass


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_candle_sets(candle_sets: Mapping[str, list[dict]], symbols: tuple[str, ...], expected_date: str) -> tuple[str, list[dict]]:
    if set(candle_sets) != set(symbols):
        missing = sorted(set(symbols) - set(candle_sets))
        raise DataGateError(f"missing symbols: {','.join(missing)}")
    manifests = []
    latest_dates = set()
    for symbol in symbols:
        rows = candle_sets[symbol]
        closed = [row for row in rows if row.get("closed")]
        if len(closed) < 220:
            raise DataGateError(f"insufficient closed-candle warmup for {symbol}: {len(closed)}")
        latest = str(closed[-1]["localDate"])
        if latest != expected_date:
            raise DataGateError(f"stale or future candle for {symbol}: expected {expected_date}, got {latest}")
        times = [int(row["time"]) for row in rows]
        if times != sorted(times) or len(times) != len(set(times)):
            raise DataGateError(f"unsorted or duplicate candles for {symbol}")
        for row in closed:
            open_price, high, low, close = (float(row[key]) for key in ("open", "high", "low", "close"))
            if high < max(open_price, close) or low > min(open_price, close) or float(row.get("volume", 0)) < 0:
                raise DataGateError(f"invalid OHLCV range for {symbol}")
        recent_dates = [datetime.fromisoformat(str(row["localDate"])).date() for row in closed[-220:]]
        if any(right - left != timedelta(days=1) for left, right in zip(recent_dates, recent_dates[1:])):
            raise DataGateError(f"daily candle gap for {symbol}")
        latest_dates.add(latest)
        manifests.append({"symbol": symbol, "latestClosedDate": latest, "rowCount": len(rows), "dataHash": _canonical_hash(rows), "status": "VALID"})
    if len(latest_dates) != 1:
        raise DataGateError("latest closed candle dates do not match")
    return next(iter(latest_dates)), manifests


class CloudScanner:
    def __init__(self, config: CloudConfig, market: MarketData, repository: CloudRepository, outbox: NotificationOutbox, now_fn=None) -> None:
        self.config = config
        self.market = market
        self.repository = repository
        self.outbox = outbox
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def run_once(self) -> dict:
        started = self.now_fn()
        expected_date = (started.date() - timedelta(days=1)).isoformat()
        candle_sets = {symbol: self.market.daily_candles(symbol) for symbol in self.config.symbols}
        candle_date, manifests = validate_candle_sets(candle_sets, self.config.symbols, expected_date)
        lock_key = f"nxt:{self.config.environment}:{candle_date}:{self.config.rule_version}"
        force_suffix = f":force:{self.config.force_run_id}" if self.config.force_run_id else ""
        scan_source = f"BINANCE_USDM_PUBLIC_1D{force_suffix.upper()}"
        with self.repository.scan_lock(lock_key) as acquired:
            if not acquired:
                return {"status": "SKIPPED_LOCKED", "candleDate": candle_date}
            if not self.config.force_run_id and self.repository.completed_scan_exists(self.config.environment, candle_date, self.config.rule_version):
                return {"status": "SKIPPED_COMPLETED", "candleDate": candle_date}
            detected_at = started.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            regime = rules.btc_regime_by_date(candle_sets["BTCUSDT"])
            existing = self.repository.existing_signal_ids(self.config.environment)
            signals = []
            for symbol in self.config.symbols:
                signal = rules.latest_signal_for_symbol(symbol, candle_sets[symbol], regime, detected_at=detected_at)
                if signal and signal["id"] not in existing:
                    signals.append(signal)
                    existing.add(signal["id"])
            followups = []
            for subject in self.repository.accepted_monitor_subjects(self.config.environment):
                followups.append(
                    rules.evaluate_accepted_signal_followup(
                        dict(subject),
                        candle_sets.get(str(subject["symbol"]), []),
                        evaluation_date=started.date().isoformat(),
                    )
                )
            finished = self.now_fn().replace(microsecond=0).isoformat().replace("+00:00", "Z")
            input_hash = _canonical_hash(manifests)
            run_id = str(uuid.uuid4())
            bundle = {
                "run": {
                    "runId": run_id,
                    "environment": self.config.environment,
                    "ownerUserId": self.config.owner_user_ids[0] if self.config.owner_user_ids else None,
                    "candleDate": candle_date,
                    "status": "COMPLETED",
                    "source": scan_source,
                    "inputHash": input_hash,
                    "ruleVersion": self.config.rule_version,
                    "startedAt": detected_at,
                    "finishedAt": finished,
                    "errors": [],
                },
                "symbols": manifests,
                "signals": signals,
            }
            self.repository.persist_scan_bundle(bundle)
            self.repository.persist_followup_recommendations(self.config.environment, followups)
            generated_at = started.astimezone(ICT)
            if signals:
                ids = sorted(str(item["id"]) for item in signals)
                self.outbox.enqueue(
                    f"cloud-shadow:signals:{candle_date}:{_canonical_hash(ids)[:16]}{force_suffix}",
                    build_entry_message(signals, generated_at),
                    {"runId": run_id, "signalIds": ids, "forceRunId": self.config.force_run_id or None},
                )
            # Telegram is a daily status report, not the Action Center. Match
            # local NXT by reporting NO_ACTION for monitored subjects while
            # suppressing only evaluations that could not use fresh data.
            reportable = [item for item in followups if item["action"] != "DATA_STALE"]
            if reportable:
                for message, batch_ids in build_followup_message_batches(reportable, generated_at=generated_at):
                    ids = sorted(batch_ids)
                    self.outbox.enqueue(
                        f"cloud-shadow:followups:{candle_date}:{_canonical_hash(ids)[:16]}{force_suffix}",
                        message,
                        {"runId": run_id, "recommendationIds": ids, "forceRunId": self.config.force_run_id or None},
                    )
            delivered = self.outbox.flush()
            return {"status": "COMPLETED", "runId": run_id, "candleDate": candle_date, "newSignals": len(signals), "followUps": len(followups), "delivered": delivered, "inputHash": input_hash, "forceRunId": self.config.force_run_id or None}
