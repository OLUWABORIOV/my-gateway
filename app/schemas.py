from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import Payment, PaymentEvent


def luhn_ok(number: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(number)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


class CardInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str = Field(min_length=13, max_length=19)
    cvv: str = Field(min_length=3, max_length=4)
    expiry_month: int = Field(ge=1, le=12)
    expiry_year: int = Field(ge=2000, le=2099)

    @field_validator("number")
    @classmethod
    def _number_is_digits(cls, value):
        if not value.isdigit():
            raise ValueError("card number must contain only digits")
        if not luhn_ok(value):
            raise ValueError("card number failed the Luhn check")
        return value

    @field_validator("cvv")
    @classmethod
    def _cvv_is_digits(cls, value):
        if not value.isdigit():
            raise ValueError("cvv must contain only digits")
        return value
class AuthorizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=128)
    customer_id: str = Field(min_length=1, max_length=128)
    amount_cents: int = Field(gt=0, le=10**12)
    currency: Literal["USD"] = "USD"
    card: CardInput
class CardSummary(BaseModel):
    last4: str
    bin: str
    fingerprint: str


class BankReferences(BaseModel):
    authorization_id: str | None = None
    capture_id: str | None = None
    void_id: str | None = None
    refund_id: str | None = None


class Failure(BaseModel):
    code: str
    message: str


class Timestamps(BaseModel):
    created_at: dt.datetime
    updated_at: dt.datetime
    authorized_at: dt.datetime | None = None
    captured_at: dt.datetime | None = None
    voided_at: dt.datetime | None = None
    refunded_at: dt.datetime | None = None
    failed_at: dt.datetime | None = None
    expired_at: dt.datetime | None = None
class PaymentResponse(BaseModel):
    payment_id: str
    order_id: str
    customer_id: str
    amount_cents: int
    currency: str
    state: str
    card: CardSummary
    bank_references: BankReferences
    failure: Failure | None = None
    needs_review: bool
    authorization_expires_at: dt.datetime | None = None
    timestamps: Timestamps

    @classmethod
    def from_payment(cls, payment: Payment):
        failure = None
        if payment.failure_code:
            failure = Failure(
                code=payment.failure_code,
                message=payment.failure_message or "",
            )
        return cls(
            payment_id=payment.id,
            order_id=payment.order_id,
            customer_id=payment.customer_id,
            amount_cents=payment.amount_cents,
            currency=payment.currency,
            state=payment.state,
            card=CardSummary(
                last4=payment.card_last4,
                bin=payment.card_bin,
                fingerprint=payment.card_fingerprint,
            ),
            bank_references=BankReferences(
                authorization_id=payment.auth_id,
                capture_id=payment.capture_id,
                void_id=payment.void_id,
                refund_id=payment.refund_id,
            ),
            failure=failure,
            needs_review=payment.needs_review,
            authorization_expires_at=payment.auth_expires_at,
            timestamps=Timestamps(
                created_at=payment.created_at,
                updated_at=payment.updated_at,
                authorized_at=payment.authorized_at,
                captured_at=payment.captured_at,
                voided_at=payment.voided_at,
                refunded_at=payment.refunded_at,
                failed_at=payment.failed_at,
                expired_at=payment.expired_at,
            ),
        )
class EventResponse(BaseModel):
    seq: int
    operation: str
    from_state: str | None
    to_state: str | None
    bank_reference: str | None
    detail: dict | None
    created_at: dt.datetime

    @classmethod
    def from_event(cls, event: PaymentEvent):
        return cls(
            seq=event.seq,
            operation=event.operation,
            from_state=event.from_state,
            to_state=event.to_state,
            bank_reference=event.bank_reference,
            detail=event.detail,
            created_at=event.created_at,
        )


class PaymentListResponse(BaseModel):
    items: list[PaymentResponse]


class EventListResponse(BaseModel):
    items: list[EventResponse]


class ReconcileResponse(BaseModel):
    examined: int
    recovered: int
    expired: int
    failed: int


class HealthResponse(BaseModel):
    status: Literal["healthy", "unhealthy"]
    database: bool
    bank: bool