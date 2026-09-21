"""Side-effect contracts used by cloud and local orchestration adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable


JsonObject = dict[str, object]


@runtime_checkable
class MarketDataPort(Protocol):
    """Provides closed market candles; implementations own HTTP/cache behavior."""

    def daily_candles(self, symbol: str) -> Sequence[Mapping[str, object]]:
        ...


@runtime_checkable
class RuleRepositoryPort(Protocol):
    """Persists orchestration results without leaking storage into the engine."""

    def existing_signal_ids(self) -> set[str]:
        ...

    def accepted_monitor_subjects(self) -> Sequence[Mapping[str, object]]:
        ...

    def persist_scan_result(self, result: Mapping[str, object], *, started_at: str) -> None:
        ...

    def persist_followup_recommendations(self, items: Sequence[Mapping[str, object]]) -> Sequence[Mapping[str, object]]:
        ...


@runtime_checkable
class NotifierPort(Protocol):
    """Queues and flushes notifications outside the pure rule boundary."""

    def enqueue(self, *, delivery_key: str, message: str, metadata: Mapping[str, object]) -> None:
        ...

    def flush(self) -> int:
        ...
