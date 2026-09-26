import pytest

from ledger.domain.enums import TransactionStatus as S
from ledger.domain.state import can_transition, is_terminal


@pytest.mark.parametrize("target", [S.COMPLETED, S.FAILED])
def test_pending_can_reach_terminal_states(target: S) -> None:
    assert can_transition(S.PENDING, target)


@pytest.mark.parametrize("current", [S.COMPLETED, S.FAILED])
@pytest.mark.parametrize("target", list(S))
def test_terminal_states_cannot_transition(current: S, target: S) -> None:
    assert is_terminal(current)
    assert not can_transition(current, target)


def test_pending_cannot_transition_to_itself() -> None:
    assert not is_terminal(S.PENDING)
    assert not can_transition(S.PENDING, S.PENDING)
