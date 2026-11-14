from enum import StrEnum



class PaymentState(StrEnum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    VOIDED = "voided"
    REFUNDED = "refunded"
    FAILED = "failed"
    EXPIRED = "expired"


class Operation(StrEnum):
    AUTHORIZE = "authorize"
    CAPTURE = "capture"
    VOID = "void"
    REFUND = "refund"
    EXPIRE = "expire"

ALLOWED_TRANSITIONS = {
    PaymentState.PENDING: {PaymentState.AUTHORIZED, PaymentState.FAILED},
    PaymentState.AUTHORIZED: {PaymentState.CAPTURED, PaymentState.VOIDED, PaymentState.EXPIRED},
    PaymentState.CAPTURED: {PaymentState.REFUNDED},
    PaymentState.VOIDED: set(),
    PaymentState.REFUNDED: set(),
    PaymentState.FAILED: set(),
    PaymentState.EXPIRED: set(),

}













REQUIRED_STATE = {
    Operation.CAPTURE: PaymentState.AUTHORIZED,
    Operation.VOID: PaymentState.AUTHORIZED,
    Operation.REFUND: PaymentState.CAPTURED,
}



RESULT_STATE = {
    Operation.AUTHORIZE: PaymentState.AUTHORIZED,
    Operation.CAPTURE: PaymentState.CAPTURED,
    Operation.VOID: PaymentState.VOIDED,
    Operation.REFUND: PaymentState.REFUNDED,
}


def can_transition(current, target):
    return target in ALLOWED_TRANSITIONS[current]


TERMINAL_STATES = frozenset({
    PaymentState.VOIDED,
    PaymentState.REFUNDED,
    PaymentState.FAILED,
    PaymentState.EXPIRED,
})

LIVE_STATES = frozenset({
    PaymentState.PENDING,
    PaymentState.AUTHORIZED,
    PaymentState.CAPTURED,
    PaymentState.VOIDED,
    PaymentState.REFUNDED,
})


class InvalidTransition(Exception):
    def __init__(self, current, target):
        self.current = current
        self.target = target
        super().__init__(f"cannot move payment from {current} to {target}")


def assert_transition(current, target):
    if not can_transition(current, target):
        raise InvalidTransition(current, target)






















    