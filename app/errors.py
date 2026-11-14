
from dataclasses import dataclass, field


@dataclass
class GatewayError(Exception):
    code: str
    message: str
    status_code: int = 400
    retryable: bool = False
    payment_id: str | None = None
    retry_after_seconds: int | None = None
    detail: dict = field(default_factory=dict)

    def __str__(self):
        return f"{self.code}: {self.message}"
    

class ValidationError(GatewayError):
    def __init__(self, code, message):
        super().__init__(code=code, message=message, status_code=422)


class MissingIdempotencyKey(GatewayError):
    def __init__(self):
        super().__init__(
            code="missing_idempotency_key",
            message="the Idempotency-Key header is required for this endpoint",
            status_code=400,
        )


class IdempotencyKeyReuse(GatewayError):
    def __init__(self, key):
        super().__init__(
            code="idempotency_key_reuse",
            message=f"Idempotency-Key '{key}' was already used with a different request body",
            status_code=422,
        )


class OperationInProgress(GatewayError):
    def __init__(self, payment_id=None):
        super().__init__(
            code="operation_in_progress",
            message="another request is already operating on this payment; retry shortly",
            status_code=409,
            retryable=True,
            payment_id=payment_id,
            retry_after_seconds=2,
        )


class PaymentNotFound(GatewayError):
    def __init__(self, payment_id):
        super().__init__(
            code="payment_not_found",
            message=f"payment '{payment_id}' does not exist",
            status_code=404,
            payment_id=payment_id,
        )


class OrderNotFound(GatewayError):
    def __init__(self, order_id):
        super().__init__(
            code="order_not_found",
            message=f"no payment found for order '{order_id}'",
            status_code=404,
        )


class OrderConflict(GatewayError):
    def __init__(self, order_id, payment_id):
        super().__init__(
            code="order_already_has_live_payment",
            message=f"order '{order_id}' already has live payment '{payment_id}'",
            status_code=409,
            payment_id=payment_id,
        )


class InvalidStateTransition(GatewayError):
    def __init__(self, current, operation, payment_id):
        super().__init__(
            code="invalid_state_transition",
            message=f"cannot {operation} a payment in state '{current}'",
            status_code=409,
            payment_id=payment_id,
            detail={"state": current},
        )


class AuthorizationExpired(GatewayError):
    def __init__(self, payment_id):
        super().__init__(
            code="authorization_expired",
            message="the authorization expired before it was captured",
            status_code=409,
            payment_id=payment_id,
        )
class BankDeclined(GatewayError):
    def __init__(self, bank_code, message, *, status_code=400, payment_id=None):
        super().__init__(
            code=bank_code,
            message=message,
            status_code=status_code,
            retryable=False,
            payment_id=payment_id,
        )


class BankUnavailable(GatewayError):
    def __init__(
        self,
        message="the bank is unavailable; retry with the same Idempotency-Key",
        *,
        payment_id=None,
        retry_after_seconds=3,
    ):
        super().__init__(
            code="bank_unavailable",
            message=message,
            status_code=503,
            retryable=True,
            payment_id=payment_id,
            retry_after_seconds=retry_after_seconds,
        )


class InternalError(GatewayError):
    def __init__(self, message="an internal error occurred"):
        super().__init__(code="internal_error", message=message, status_code=500)