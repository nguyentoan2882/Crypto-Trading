"""Canonical comparison helpers for local/cloud rule parity evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable


DEFAULT_IGNORED_FIELDS = frozenset({"detectedAt", "scannedAt"})


def normalize(value: object, ignored_fields: Iterable[str] = DEFAULT_IGNORED_FIELDS) -> object:
    ignored = frozenset(ignored_fields)
    if isinstance(value, dict):
        return {
            key: normalize(item, ignored)
            for key, item in sorted(value.items())
            if key not in ignored
        }
    if isinstance(value, list):
        return [normalize(item, ignored) for item in value]
    if isinstance(value, tuple):
        return [normalize(item, ignored) for item in value]
    return value


def canonical_json(value: object, ignored_fields: Iterable[str] = DEFAULT_IGNORED_FIELDS) -> str:
    return json.dumps(normalize(value, ignored_fields), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def comparison_hash(value: object, ignored_fields: Iterable[str] = DEFAULT_IGNORED_FIELDS) -> str:
    return hashlib.sha256(canonical_json(value, ignored_fields).encode("utf-8")).hexdigest()


def exact_match(left: object, right: object, ignored_fields: Iterable[str] = DEFAULT_IGNORED_FIELDS) -> bool:
    return canonical_json(left, ignored_fields) == canonical_json(right, ignored_fields)
