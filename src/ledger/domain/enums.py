from enum import StrEnum


class TransactionType(StrEnum):
    DISBURSEMENT = "DISBURSEMENT"
    PURCHASE = "PURCHASE"
    PAYMENT = "PAYMENT"


class TransactionStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
