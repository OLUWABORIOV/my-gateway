from app.state import ALLOWED_TRANSITIONS, PaymentState as S, can_transition


def test_pending_can_be_authorized():
    assert can_transition(S.PENDING, S.AUTHORIZED)


def test_authorized_can_be_captured_voided_or_expired():
    assert can_transition(S.AUTHORIZED, S.CAPTURED)
    assert can_transition(S.AUTHORIZED, S.VOIDED)
    assert can_transition(S.AUTHORIZED, S.EXPIRED)


def test_captured_can_only_be_refunded():
    assert can_transition(S.CAPTURED, S.REFUNDED)
    assert not can_transition(S.CAPTURED, S.VOIDED)


def test_pending_cannot_skip_to_captured():
    assert not can_transition(S.PENDING, S.CAPTURED)


def test_end_states_allow_nothing():
    for end in (S.VOIDED, S.REFUNDED, S.FAILED, S.EXPIRED):
        for target in S:
            assert not can_transition(end, target)

def test_pending_can_fail():
    assert can_transition(S.PENDING, S.FAILED)


def test_authorized_cannot_be_refunded_directly():
    assert not can_transition(S.AUTHORIZED, S.REFUNDED)


def test_captured_cannot_be_authorized_again():
    assert not can_transition(S.CAPTURED, S.AUTHORIZED)


def test_no_state_transitions_to_itself():
    for state in S:
        assert not can_transition(state, state)


def test_every_state_has_a_rule():
    for state in S:
        assert state in ALLOWED_TRANSITIONS