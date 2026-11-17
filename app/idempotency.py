from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from .errors import IdempotencyKeyReuse, OperationInProgress
from .models import IdempotencyRecord, utcnow

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Replay:
    status_code: int
    body: dict[str, Any]


def request_fingerprint(payload: Any, pepper: str) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(pepper.encode(), canonical.encode(), hashlib.sha256).hexdigest()


class IdempotencyStore:
    def __init__(self, session_factory, *, pepper, ttl_hours=24, stale_seconds=60):
        self._session_factory = session_factory
        self._pepper = pepper
        self._ttl = dt.timedelta(hours=ttl_hours)
        self._stale = dt.timedelta(seconds=stale_seconds)
    def begin(self, key, scope, payload):
        fingerprint = request_fingerprint(payload, self._pepper)
        now = utcnow()

        with self._session_factory() as session:
            inserted = session.execute(
                pg_insert(IdempotencyRecord)
                .values(
                    key=key,
                    scope=scope,
                    request_hash=fingerprint,
                    status="in_progress",
                    locked_at=now,
                    created_at=now,
                )
                .on_conflict_do_nothing(index_elements=["key", "scope"])
                .returning(IdempotencyRecord.key)
            )
            won = inserted.first() is not None
            session.commit()
            if won:
                return None

        with self._session_factory() as session:
            record = session.get(IdempotencyRecord, (key, scope))
            if record is None:
                return self.begin(key, scope, payload)

            if not hmac.compare_digest(record.request_hash, fingerprint):
                raise IdempotencyKeyReuse(key)

            if record.status == "completed":
                return Replay(
                    status_code=record.response_status or 200,
                    body=record.response_body or {},
                )

            if record.locked_at > now - self._stale:
                raise OperationInProgress(record.payment_id)

            taken = session.execute(
                update(IdempotencyRecord)
                .where(
                    IdempotencyRecord.key == key,
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.status == "in_progress",
                    IdempotencyRecord.locked_at == record.locked_at,
                )
                .values(locked_at=now)
                .returning(IdempotencyRecord.key)
            )
            won = taken.first() is not None
            session.commit()
            if won:
                log.warning(
                    "took over stale idempotency key",
                    extra={"event": "idempotency_takeover"},
                )
                return None
            raise OperationInProgress(record.payment_id)
    def complete(self, key, scope, status_code, body, payment_id):
        now = utcnow()
        with self._session_factory() as session:
            session.execute(
                update(IdempotencyRecord)
                .where(
                    IdempotencyRecord.key == key,
                    IdempotencyRecord.scope == scope,
                )
                .values(
                    status="completed",
                    response_status=status_code,
                    response_body=body,
                    payment_id=payment_id,
                    completed_at=now,
                    locked_at=now,
                )
            )
            session.commit()

    def abandon(self, key, scope):
        with self._session_factory() as session:
            session.execute(
                delete(IdempotencyRecord).where(
                    IdempotencyRecord.key == key,
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.status == "in_progress",
                )
            )
            session.commit()
    def purge_expired(self, now=None):
        cutoff = (now or utcnow()) - self._ttl
        with self._session_factory() as session:
            result = session.execute(
                delete(IdempotencyRecord).where(IdempotencyRecord.created_at < cutoff)
            )
            session.commit()
            return result.rowcount or 0

    def get(self, key, scope):
        with self._session_factory() as session:
            return session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.key == key,
                    IdempotencyRecord.scope == scope,
                )
           )