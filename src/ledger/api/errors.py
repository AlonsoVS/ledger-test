from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from ledger.domain import errors as e

STATUS_BY_ERROR: dict[type[e.LedgerError], int] = {
    e.AccountNotFound: status.HTTP_404_NOT_FOUND,
    e.TransactionNotFound: status.HTTP_404_NOT_FOUND,
    e.IdempotencyConflict: status.HTTP_409_CONFLICT,
    e.InvalidStateTransition: status.HTTP_409_CONFLICT,
    e.InvalidAmount: status.HTTP_422_UNPROCESSABLE_CONTENT,
    e.InvalidRequest: status.HTTP_422_UNPROCESSABLE_CONTENT,
    e.InsufficientCredit: status.HTTP_422_UNPROCESSABLE_CONTENT,
    e.Overpayment: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


async def handle_ledger_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, e.LedgerError)
    return JSONResponse(
        status_code=STATUS_BY_ERROR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        content={"code": exc.code, "message": str(exc)},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(e.LedgerError, handle_ledger_error)
