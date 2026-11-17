from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.bank import (
    Attempt,
    BankAuthorization,
    BankCapture,
    BankRefund,
    BankVoid,
)
from app.errors import BankDeclined, BankUnavailable


@dataclass
class Call:
    operation: str
    idempotency_key: str
    payload: dict[str, Any]
    attempt: int


class FakeBank:
    def __init__(self, clock=None):
        self.calls = []
        self.scripts = defaultdict(list)
        self.responses = {}
        self.health_ok = True
        self._clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self._attempts = defaultdict(int)

    def queue(self, operation, *items):
        self.scripts[operation].extend(items)

    def fail_next(self, operation, exc=None, times=1):
        error = exc or BankUnavailable("injected transient failure")
        self.queue(operation, *([error] * times))

    def calls_for(self, operation):
        return [call for call in self.calls if call.operation == operation]

    def keys_for(self, operation):
        return {call.idempotency_key for call in self.calls_for(operation)}

    def health(self):
        return self.health_ok
    def authorize(self, *, card_number, cvv, expiry_month, expiry_year,
                  amount_cents, idempotency_key, on_attempt=None):
        payload = {
            "card_number": card_number,
            "cvv": cvv,
            "expiry_month": expiry_month,
            "expiry_year": expiry_year,
            "amount": amount_cents,
        }
        now = self._clock()
        return self._invoke(
            "authorize",
            idempotency_key,
            payload,
            lambda: BankAuthorization(
                authorization_id=f"auth_{uuid.uuid4()}",
                amount_cents=amount_cents,
                currency="USD",
                expires_at=now + dt.timedelta(days=7),
                created_at=now,
            ),
            on_attempt,
        )

    def capture(self, *, authorization_id, amount_cents,
                idempotency_key, on_attempt=None):
        payload = {"authorization_id": authorization_id, "amount": amount_cents}
        now = self._clock()
        return self._invoke(
            "capture",
            idempotency_key,
            payload,
            lambda: BankCapture(
                capture_id=f"cap_{uuid.uuid4()}",
                authorization_id=authorization_id,
                amount_cents=amount_cents,
                currency="USD",
                captured_at=now,
            ),
            on_attempt,
        )
    def void(self, *, authorization_id, idempotency_key, on_attempt=None):
        payload = {"authorization_id": authorization_id}
        now = self._clock()
        return self._invoke(
            "void",
            idempotency_key,
            payload,
            lambda: BankVoid(
                void_id=f"void_{uuid.uuid4()}",
                authorization_id=authorization_id,
                voided_at=now,
            ),
            on_attempt,
        )

    def refund(self, *, capture_id, amount_cents,
               idempotency_key, on_attempt=None):
        payload = {"capture_id": capture_id, "amount": amount_cents}
        now = self._clock()
        return self._invoke(
            "refund",
            idempotency_key,
            payload,
            lambda: BankRefund(
                refund_id=f"ref_{uuid.uuid4()}",
                capture_id=capture_id,
                amount_cents=amount_cents,
                currency="USD",
                refunded_at=now,
            ),
            on_attempt,
        )
    def _invoke(self, operation, key, payload, factory, on_attempt):
        self._attempts[operation] += 1
        attempt_no = self._attempts[operation]
        self.calls.append(Call(operation, key, payload, attempt_no))

        if self.scripts[operation]:
            item = self.scripts[operation].pop(0)
            if isinstance(item, BaseException):
                outcome = "rejected" if isinstance(item, BankDeclined) else "transient"
                status = (
                    getattr(item, "status_code", None)
                    if isinstance(item, BankDeclined)
                    else 503
                )
                code = (
                    getattr(item, "code", None)
                    if isinstance(item, BankDeclined)
                    else None
                )
                if on_attempt:
                    on_attempt(Attempt(attempt_no, status, outcome, code, 1))
                raise item
            self.responses[(operation, key)] = item
            if on_attempt:
                on_attempt(Attempt(attempt_no, 200, "ok", None, 1))
            return item

        cached = self.responses.get((operation, key))
        if cached is not None:
            if on_attempt:
                on_attempt(Attempt(attempt_no, 200, "ok", None, 1))
            return cached

        result = factory()
        self.responses[(operation, key)] = result
        if on_attempt:
            on_attempt(Attempt(attempt_no, 200, "ok", None, 1))
        return result
@dataclass
class FrozenClock:
    current: dt.datetime = field(
        default_factory=lambda: dt.datetime(2026, 11, 7, 12, 0, tzinfo=dt.timezone.utc)
    )

    def __call__(self):
        return self.current

    def advance(self, **kwargs):
        self.current += dt.timedelta(**kwargs)

    def set(self, value):
        self.current = value