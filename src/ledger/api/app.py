from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Request, Response, status

from ledger.api.errors import register_error_handlers
from ledger.api.schemas import (
    AccountCreate,
    AccountOut,
    AccountWithBalanceOut,
    ErrorOut,
    TransactionCreate,
    TransactionOut,
)
from ledger.db.session import make_engine, make_session_factory
from ledger.service import LedgerService
from ledger.settings import get_settings

router = APIRouter()
ERRORS: dict[int | str, dict[str, Any]] = {code: {"model": ErrorOut} for code in (404, 409, 422)}


def get_service(request: Request) -> LedgerService:
    service: LedgerService = request.app.state.service
    return service


Service = Annotated[LedgerService, Depends(get_service)]


@router.post("/accounts", status_code=status.HTTP_201_CREATED, responses=ERRORS)
def create_account(body: AccountCreate, service: Service) -> AccountOut:
    return AccountOut.from_record(service.create_account(body.customer_id))


@router.get("/accounts/{account_id}", responses=ERRORS)
def get_account(account_id: UUID, service: Service) -> AccountWithBalanceOut:
    return AccountWithBalanceOut.from_view(service.get_account(account_id))


@router.post(
    "/accounts/{account_id}/transactions",
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": TransactionOut, "description": "Idempotent replay"}, **ERRORS},
)
def create_transaction(
    account_id: UUID,
    body: TransactionCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
    response: Response,
    service: Service,
) -> TransactionOut:
    result = service.create_transaction(account_id, body.type, body.amount, idempotency_key)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return TransactionOut.from_record(result.transaction)


@router.get("/accounts/{account_id}/transactions", responses=ERRORS)
def list_transactions(account_id: UUID, service: Service) -> list[TransactionOut]:
    return [TransactionOut.from_record(tx) for tx in service.list_transactions(account_id)]


@router.post("/transactions/{transaction_id}/complete", responses=ERRORS)
def complete_transaction(transaction_id: UUID, service: Service) -> TransactionOut:
    return TransactionOut.from_record(service.complete_transaction(transaction_id))


@router.post("/transactions/{transaction_id}/fail", responses=ERRORS)
def fail_transaction(transaction_id: UUID, service: Service) -> TransactionOut:
    return TransactionOut.from_record(service.fail_transaction(transaction_id))


def create_app(service: LedgerService | None = None) -> FastAPI:
    app = FastAPI(title="Credit Ledger", version="0.1.0")
    app.state.service = service or LedgerService(
        make_session_factory(make_engine(get_settings().database_url))
    )
    app.include_router(router)
    register_error_handlers(app)
    return app


app = create_app()
