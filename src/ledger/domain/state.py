from types import MappingProxyType

from ledger.domain.enums import TransactionStatus

ALLOWED_TRANSITIONS = MappingProxyType(
    {
        TransactionStatus.PENDING: frozenset(
            {TransactionStatus.COMPLETED, TransactionStatus.FAILED}
        ),
        TransactionStatus.COMPLETED: frozenset[TransactionStatus](),
        TransactionStatus.FAILED: frozenset[TransactionStatus](),
    }
)


def can_transition(current: TransactionStatus, target: TransactionStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def is_terminal(status: TransactionStatus) -> bool:
    return not ALLOWED_TRANSITIONS[status]
