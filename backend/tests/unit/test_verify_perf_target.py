from __future__ import annotations

import json

import pytest
from scripts import verify_perf_target as module

STAGING_URL = "https://staging.example.test/api/"
ALLOWED_ORIGIN = "https://staging.example.test"
READY = json.dumps({"success": True, "data": {"environment": "staging"}}).encode()


def test_builds_canonical_health_url_and_origin() -> None:
    assert (
        module.normalize_origin("https://STAGING.example.test:443/") == ALLOWED_ORIGIN
    )
    assert module.build_health_url(STAGING_URL, ALLOWED_ORIGIN) == (
        f"{ALLOWED_ORIGIN}/api/ops/health/ready"
    )


def test_health_url_must_match_approved_origin() -> None:
    with pytest.raises(module.TargetCheckError, match="no coincide"):
        module.build_health_url(STAGING_URL, "https://other.example.test")


@pytest.mark.parametrize(
    "url",
    [
        "http://staging.example.test/api",
        "https://127.0.0.1/api",
        "https://[::1]/api",
        "https://[::ffff:127.0.0.1]/api",
        "https://[::ffff:0.0.0.0]/api",
        "https://[::ffff:169.254.169.254]/api",
        "https://[::ffff:224.0.0.1]/api",
        "https://0.0.0.0/api",
        "https://169.254.1.1/api",
        "https://224.0.0.1/api",
        "https://2130706433/api",
        "https://0x7f000001/api",
        "https://localhost/api",
        "https://internal.localhost/api",
        "https://user@staging.example.test/api",
        "https://staging.example.test/other",
        "https://staging.example.test/api?next=x",
    ],
)
def test_rejects_unsafe_staging_url(url: str) -> None:
    with pytest.raises(module.TargetCheckError):
        module.build_health_url(url, ALLOWED_ORIGIN)


@pytest.mark.parametrize(
    "url",
    ["https://１２７.０.０.１/api", "https://ｌｏｃａｌｈｏｓｔ/api"],
    ids=["fullwidth-loopback-ip", "fullwidth-localhost"],
)
def test_rejects_dangerous_hosts_after_idna_normalization(url: str) -> None:
    with pytest.raises(module.TargetCheckError):
        module.build_health_url(url, ALLOWED_ORIGIN)


def test_accepts_only_canonical_staging_health_envelope() -> None:
    module.validate_health_response(200, READY)


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (503, READY),
        (200, b'{"success":true,"data":{"environment":"production"}}'),
        (200, b'{"success":false,"data":{"environment":"staging"}}'),
        (200, b"not-json"),
        (200, b"x" * (64 * 1024 + 1)),
    ],
    ids=["status", "environment", "success", "json", "size"],
)
def test_rejects_invalid_health_envelope(status: int, body: bytes) -> None:
    with pytest.raises(module.TargetCheckError):
        module.validate_health_response(status, body)
