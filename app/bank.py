from __future__ import annotations

import datetime as dt
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .errors import BankDeclined, BankUnavailable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Attempt:
    attempt: int
    status_code: int | None
    outcome: str
    error_code: str | None
    duration_ms: int


@dataclass(frozen=True)
class BankAuthorization:
    authorization_id: str
    amount_cents: int
    currency: str
    expires_at: dt.datetime
    created_at: dt.datetime


@dataclass(frozen=True)
class BankCapture:
    capture_id: str
    authorization_id: str
    amount_cents: int
    currency: str
    captured_at: dt.datetime


@dataclass(frozen=True)
class BankVoid:
    void_id: str
    authorization_id: str
    voided_at: dt.datetime


@dataclass(frozen=True)
class BankRefund:
    refund_id: str
    capture_id: str
    amount_cents: int
    currency: str
    refunded_at: dt.datetime


AttemptRecorder = Callable[[Attempt], None]


class BankClient(Protocol):
    def authorize(self, *, card_number, cvv, expiry_month, expiry_year,
                  amount_cents, idempotency_key, on_attempt=None): ...
    def capture(self, *, authorization_id, amount_cents,
                idempotency_key, on_attempt=None): ...
    def void(self, *, authorization_id, idempotency_key,
             on_attempt=None): ...
    def refund(self, *, capture_id, amount_cents,
               idempotency_key, on_attempt=None): ...
def _parse_ts(value: str) -> dt.datetime:
    text = value.replace("Z", "+00:00")
    if "." in text:
        head, tail = text.split(".", 1)
        fraction, _, offset = tail.partition("+")
        fraction = (fraction + "000000")[:6]
        text = f"{head}.{fraction}+{offset}" if offset else f"{head}.{fraction}+00:00"
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed
class HttpBankClient:
    def __init__(self, base_url, *, connect_timeout=2.0, read_timeout=5.0,
                 max_attempts=4, backoff_base=0.2, backoff_cap=3.0,
                 client=None, sleep=time.sleep, rng=None):
        self._base_url = base_url.rstrip("/")
        self._max_attempts = max(1, max_attempts)
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(
                connect=connect_timeout,
                read=read_timeout,
                write=read_timeout,
                pool=connect_timeout,
            ),
            headers={"Accept": "application/json"},
        )

    def close(self):
        if self._owns_client:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def health(self):
        try:
            return self._client.get("/health", timeout=2.0).status_code == 200
        except httpx.HTTPError:
            return False

    def authorize(self, *, card_number, cvv, expiry_month, expiry_year,
                  amount_cents, idempotency_key, on_attempt=None):
        body = self._post(
            operation="authorize",
            path="/api/v1/authorizations",
            payload={
                "card_number": card_number,
                "cvv": cvv,
                "expiry_month": expiry_month,
                "expiry_year": expiry_year,
                "amount": amount_cents,
            },
            idempotency_key=idempotency_key,
            on_attempt=on_attempt,
        )
        return BankAuthorization(
            authorization_id=body["authorization_id"],
            amount_cents=int(body["amount"]),
            currency=body.get("currency", "USD"),
            expires_at=_parse_ts(body["expires_at"]),
            created_at=_parse_ts(body["created_at"]),
        )
    def capture(self, *, authorization_id, amount_cents,
                idempotency_key, on_attempt=None):
        body = self._post(
            operation="capture",
            path="/api/v1/captures",
            payload={"authorization_id": authorization_id, "amount": amount_cents},
            idempotency_key=idempotency_key,
            on_attempt=on_attempt,
        )
        return BankCapture(
            capture_id=body["capture_id"],
            authorization_id=body["authorization_id"],
            amount_cents=int(body["amount"]),
            currency=body.get("currency", "USD"),
            captured_at=_parse_ts(body["captured_at"]),
        )
   

    def void(self, *, authorization_id, idempotency_key, on_attempt=None):
        body = self._post(
            operation="void",
            path="/api/v1/voids",
            payload={"authorization_id": authorization_id},
            idempotency_key=idempotency_key,
            on_attempt=on_attempt,
        )
        return BankVoid(
            void_id=body["void_id"],
            authorization_id=body["authorization_id"],
            voided_at=_parse_ts(body["voided_at"]),
        )

    def refund(self, *, capture_id, amount_cents,
               idempotency_key, on_attempt=None):
        body = self._post(
            operation="refund",
            path="/api/v1/refunds",
            payload={"capture_id": capture_id, "amount": amount_cents},
            idempotency_key=idempotency_key,
            on_attempt=on_attempt,
        )
        return BankRefund(
            refund_id=body["refund_id"],
            capture_id=body["capture_id"],
            amount_cents=int(body["amount"]),
            currency=body.get("currency", "USD"),
            refunded_at=_parse_ts(body["refunded_at"]),
        )
    def _post(self, *, operation, path, payload, idempotency_key, on_attempt):
        last_error = "no attempt made"
        for attempt_no in range(1, self._max_attempts + 1):
            started = time.monotonic()
            retry_after = None
            try:
                response = self._client.post(
                    path, json=payload,
                    headers={"Idempotency-Key": idempotency_key},
                )
            except httpx.HTTPError as exc:
                elapsed = int((time.monotonic() - started) * 1000)
                last_error = f"{type(exc).__name__}: {exc}"
                self._record(on_attempt, attempt_no, None, "error", None, elapsed)
                if attempt_no < self._max_attempts:
                    self._sleep(self._backoff(attempt_no))
                continue

            elapsed = int((time.monotonic() - started) * 1000)
            status = response.status_code
            body = _safe_json(response)

            if 200 <= status < 300:
                if body is None:
                    last_error = "bank returned a non-JSON success body"
                    self._record(on_attempt, attempt_no, status, "transient", None, elapsed)
                    if attempt_no < self._max_attempts:
                        self._sleep(self._backoff(attempt_no))
                    continue
                self._record(on_attempt, attempt_no, status, "ok", None, elapsed)
                return body

            code = (body or {}).get("error")
            message = (body or {}).get("message") or f"bank returned HTTP {status}"

            if status >= 500 or status == 429:
                last_error = f"HTTP {status} {code or ''}".strip()
                retry_after = _retry_after_seconds(response)
                self._record(on_attempt, attempt_no, status, "transient", code, elapsed)
                if attempt_no < self._max_attempts:
                    self._sleep(self._backoff(attempt_no, retry_after))
                continue

            self._record(on_attempt, attempt_no, status, "rejected", code, elapsed)
            raise BankDeclined(code or "bank_rejected", message, status_code=status)

        raise BankUnavailable(
            f"bank did not succeed after {self._max_attempts} attempts ({last_error})")

    def _backoff(self, attempt_no, retry_after=None):
        if retry_after is not None:
            return max(0.0, min(retry_after, self._backoff_cap))
        ceiling = min(self._backoff_cap, self._backoff_base * (2 ** (attempt_no - 1)))
        return max(0.05, self._rng.uniform(0, ceiling))

    @staticmethod
    def _record(recorder, attempt_no, status_code, outcome, error_code, duration_ms):
        if recorder is None:
            return
        recorder(Attempt(attempt_no, status_code, outcome, error_code, duration_ms))
def _safe_json(response):
    try:
        parsed = response.json()
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _retry_after_seconds(response):
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None