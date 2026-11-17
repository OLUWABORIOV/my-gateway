import datetime as dt
import json
import random

import httpx
import pytest

from app.bank import HttpBankClient, _parse_ts
from app.errors import BankDeclined, BankUnavailable

AUTH_OK = {
    "authorization_id": "auth_1",
    "amount": 5000,
    "currency": "USD",
    "expires_at": "2026-11-24T10:00:00Z",
    "created_at": "2026-11-17T10:00:00Z",
}

AUTH_ARGS = dict(
    card_number="4111111111111111",
    cvv="123",
    expiry_month=12,
    expiry_year=2030,
    amount_cents=5000,
    idempotency_key="pay_1:authorize",
)


def ok(body, status=200):
    return lambda: httpx.Response(status, json=body)


def fail(status, **kw):
    return lambda: httpx.Response(status, **kw)


def timeout():
    raise httpx.ConnectTimeout("timed out")


class FakeBank:
    """Plays back scripted responses; the last one repeats forever."""

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        return step()


def make_client(bank, **kw):
    sleeps = []
    http = httpx.Client(
        base_url="http://bank.test",
        transport=httpx.MockTransport(bank),
    )
    client = HttpBankClient(
        "http://bank.test",
        client=http,
        sleep=sleeps.append,
        rng=random.Random(1),
        **kw,
    )
    return client, sleeps


# ---------- happy paths ----------

def test_authorize_success_parses_response_and_sends_request():
    bank = FakeBank(ok(AUTH_OK, 201))
    client, sleeps = make_client(bank)

    auth = client.authorize(**AUTH_ARGS)

    assert auth.authorization_id == "auth_1"
    assert auth.amount_cents == 5000
    assert auth.currency == "USD"
    assert auth.expires_at == dt.datetime(2026, 11, 24, 10, 0, tzinfo=dt.timezone.utc)

    assert len(bank.requests) == 1
    req = bank.requests[0]
    assert req.url.path == "/api/v1/authorizations"
    assert req.headers["Idempotency-Key"] == "pay_1:authorize"
    sent = json.loads(req.content)
    assert sent["amount"] == 5000
    assert sent["card_number"] == "4111111111111111"
    assert sleeps == []


def test_capture_success():
    bank = FakeBank(ok({
        "capture_id": "cap_1", "authorization_id": "auth_1", "amount": 3000,
        "currency": "USD", "captured_at": "2026-11-17T11:00:00Z",
    }))
    client, _ = make_client(bank)

    cap = client.capture(authorization_id="auth_1", amount_cents=3000,
                         idempotency_key="pay_1:capture")

    assert cap.capture_id == "cap_1"
    assert cap.amount_cents == 3000
    assert bank.requests[0].url.path == "/api/v1/captures"


def test_void_success():
    bank = FakeBank(ok({
        "void_id": "void_1", "authorization_id": "auth_1",
        "voided_at": "2026-11-17T11:00:00Z",
    }))
    client, _ = make_client(bank)

    void = client.void(authorization_id="auth_1", idempotency_key="pay_1:void")

    assert void.void_id == "void_1"
    assert bank.requests[0].url.path == "/api/v1/voids"


def test_refund_success():
    bank = FakeBank(ok({
        "refund_id": "ref_1", "capture_id": "cap_1", "amount": 1000,
        "currency": "USD", "refunded_at": "2026-11-17T12:00:00Z",
    }))
    client, _ = make_client(bank)

    refund = client.refund(capture_id="cap_1", amount_cents=1000,
                           idempotency_key="pay_1:refund")

    assert refund.refund_id == "ref_1"
    assert bank.requests[0].url.path == "/api/v1/refunds"


# ---------- declines: no retry ----------

def test_decline_raises_and_is_not_retried():
    bank = FakeBank(fail(402, json={"error": "insufficient_funds",
                                    "message": "not enough funds"}))
    client, sleeps = make_client(bank)

    with pytest.raises(BankDeclined):
        client.authorize(**AUTH_ARGS)

    assert len(bank.requests) == 1
    assert sleeps == []


# ---------- retries ----------

def test_retries_5xx_then_succeeds_with_same_idempotency_key():
    bank = FakeBank(fail(500, json={"error": "boom"}), ok(AUTH_OK))
    client, sleeps = make_client(bank)

    auth = client.authorize(**AUTH_ARGS)

    assert auth.authorization_id == "auth_1"
    assert len(bank.requests) == 2
    keys = {r.headers["Idempotency-Key"] for r in bank.requests}
    assert keys == {"pay_1:authorize"}
    assert len(sleeps) == 1


def test_timeout_then_success():
    bank = FakeBank(timeout, ok(AUTH_OK))
    client, sleeps = make_client(bank)

    auth = client.authorize(**AUTH_ARGS)

    assert auth.authorization_id == "auth_1"
    assert len(bank.requests) == 2
    assert len(sleeps) == 1


def test_gives_up_after_max_attempts():
    bank = FakeBank(fail(503, json={"error": "down"}))
    client, sleeps = make_client(bank, max_attempts=3)

    with pytest.raises(BankUnavailable):
        client.authorize(**AUTH_ARGS)

    assert len(bank.requests) == 3
    assert len(sleeps) == 2  # no sleep after the final attempt


def test_backoff_stays_within_bounds():
    bank = FakeBank(fail(500, json={}), ok(AUTH_OK))
    client, sleeps = make_client(bank, backoff_base=0.2, backoff_cap=3.0)

    client.authorize(**AUTH_ARGS)

    assert 0.05 <= sleeps[0] <= 0.2


def test_429_honours_retry_after():
    bank = FakeBank(
        fail(429, headers={"Retry-After": "1"}, json={"error": "rate_limited"}),
        ok(AUTH_OK),
    )
    client, sleeps = make_client(bank)

    client.authorize(**AUTH_ARGS)

    assert sleeps == [1.0]


def test_retry_after_is_capped():
    bank = FakeBank(
        fail(429, headers={"Retry-After": "99"}, json={"error": "rate_limited"}),
        ok(AUTH_OK),
    )
    client, sleeps = make_client(bank, backoff_cap=3.0)

    client.authorize(**AUTH_ARGS)

    assert sleeps == [3.0]


def test_non_json_success_body_is_treated_as_transient():
    bank = FakeBank(fail(200, content=b"<html>oops</html>"))
    client, _ = make_client(bank, max_attempts=2)

    with pytest.raises(BankUnavailable):
        client.authorize(**AUTH_ARGS)

    assert len(bank.requests) == 2


# ---------- attempt recording ----------

def test_on_attempt_records_each_try():
    bank = FakeBank(fail(500, json={"error": "boom"}), ok(AUTH_OK))
    client, _ = make_client(bank)
    attempts = []

    client.authorize(**AUTH_ARGS, on_attempt=attempts.append)

    assert [a.outcome for a in attempts] == ["transient", "ok"]
    assert [a.status_code for a in attempts] == [500, 200]
    assert [a.attempt for a in attempts] == [1, 2]


def test_on_attempt_records_timeout_as_error():
    bank = FakeBank(timeout, ok(AUTH_OK))
    client, _ = make_client(bank)
    attempts = []

    client.authorize(**AUTH_ARGS, on_attempt=attempts.append)

    assert attempts[0].outcome == "error"
    assert attempts[0].status_code is None


# ---------- health and timestamp parsing ----------

def test_health_true_on_200():
    bank = FakeBank(fail(200, json={"status": "ok"}))
    client, _ = make_client(bank)
    assert client.health() is True


def test_health_false_on_error():
    bank = FakeBank(timeout)
    client, _ = make_client(bank)
    assert client.health() is False


def test_parse_ts_handles_z_suffix():
    assert _parse_ts("2026-11-17T10:00:00Z") == dt.datetime(
        2026, 11, 17, 10, 0, tzinfo=dt.timezone.utc)


def test_parse_ts_trims_long_fractions():
    parsed = _parse_ts("2026-11-17T10:00:00.123456789Z")
    assert parsed.microsecond == 123456


def test_parse_ts_assumes_utc_when_naive():
    assert _parse_ts("2026-11-17T10:00:00").tzinfo is not None