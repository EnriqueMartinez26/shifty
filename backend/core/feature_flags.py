from __future__ import annotations

from typing import Any


DEFAULT_STORE_FEATURE_FLAGS: dict[str, bool] = {
    "payments": False,
    "ledger": False,
    "advanced_reports": False,
    "new_calendar": False,
    "otp_booking": False,
}


def normalize_store_feature_flags(raw_flags: dict[str, Any] | None) -> dict[str, bool]:
    normalized = dict(DEFAULT_STORE_FEATURE_FLAGS)
    if not raw_flags:
        return normalized
    for key, value in raw_flags.items():
        if key in DEFAULT_STORE_FEATURE_FLAGS:
            normalized[key] = bool(value)
    return normalized


def merge_store_feature_flags(
    current_flags: dict[str, Any] | None,
    updates: dict[str, bool | None],
) -> dict[str, bool]:
    merged = normalize_store_feature_flags(current_flags)
    for key, value in updates.items():
        if key in DEFAULT_STORE_FEATURE_FLAGS and value is not None:
            merged[key] = bool(value)
    return merged


def is_store_feature_enabled(raw_flags: dict[str, Any] | None, feature_key: str) -> bool:
    return normalize_store_feature_flags(raw_flags).get(feature_key, False)
