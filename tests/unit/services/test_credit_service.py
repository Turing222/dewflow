"""CreditService unit tests.

职责：验证 Credits 账户只读查询、签到并发恢复和模型扣费幂等性；
边界：使用 mock repository，不连接真实数据库；副作用：无。
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError

from backend.core.exceptions import AppException
from backend.services.credit_service import CreditService

pytestmark = pytest.mark.asyncio


def make_account(*, balance: int = 1000) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), user_id=uuid.uuid4(), balance=balance)


def make_uow() -> SimpleNamespace:
    credit_repo = AsyncMock()
    credit_repo.get_account.return_value = None
    credit_repo.get_account_with_lock.return_value = None
    credit_repo.get_transaction_by_idempotency_key.return_value = None
    credit_repo.get_usage_record_by_chat_message_id.return_value = None
    credit_repo.list_transactions.return_value = []
    credit_repo.count_transactions.return_value = 0
    credit_repo.list_accounts_needing_expiration.return_value = []
    credit_repo.get_spent_sum.return_value = 0
    credit_repo.get_already_expired_sum.return_value = 0
    credit_repo.get_expired_grants_sum.return_value = 0

    @asynccontextmanager
    async def _noop_savepoint():
        yield uow

    uow = SimpleNamespace(
        credit_repo=credit_repo,
        rollback=AsyncMock(),
        savepoint=_noop_savepoint,
    )
    return uow


async def test_get_account_does_not_create_when_missing() -> None:
    uow = make_uow()
    service = CreditService(uow)

    result = await service.get_account(uuid.uuid4())

    assert result is None
    uow.credit_repo.create_account.assert_not_awaited()


async def test_list_user_transactions_returns_empty_when_account_missing() -> None:
    uow = make_uow()
    service = CreditService(uow)

    transactions, total = await service.list_user_transactions(
        user_id=uuid.uuid4(),
        skip=0,
        limit=20,
    )

    assert transactions == []
    assert total == 0
    uow.credit_repo.list_transactions.assert_not_awaited()
    uow.credit_repo.count_transactions.assert_not_awaited()


async def test_ensure_sufficient_balance_rejects_empty_balance() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=0)
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.return_value = account
    service = CreditService(uow)

    with pytest.raises(AppException) as exc_info:
        await service.ensure_sufficient_balance(user_id)

    assert exc_info.value.code == "CREDIT_QUOTA_EXCEEDED"
    assert exc_info.value.details == {"balance": 0, "estimated_cost": 10}
    uow.credit_repo.create_account.assert_not_awaited()


async def test_ensure_sufficient_balance_uses_savepoint_not_rollback() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=100)
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.side_effect = [None, account]
    uow.credit_repo.create_account.side_effect = IntegrityError("insert", {}, None)
    service = CreditService(uow)

    result = await service.ensure_sufficient_balance(user_id)

    assert result is account
    uow.rollback.assert_not_awaited()
    assert uow.credit_repo.get_account_with_lock.await_count == 2


async def test_ensure_sufficient_balance_rejects_balance_below_estimated_cost() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=3)
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.return_value = account
    service = CreditService(uow)

    with pytest.raises(AppException) as exc_info:
        await service.ensure_sufficient_balance(user_id, estimated_cost=5)

    assert exc_info.value.code == "CREDIT_QUOTA_EXCEEDED"
    assert exc_info.value.details == {"balance": 3, "estimated_cost": 5}


async def test_ensure_sufficient_balance_recovers_from_concurrent_account_create() -> (
    None
):
    user_id = uuid.uuid4()
    account = make_account(balance=100)
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.side_effect = [None, account]
    uow.credit_repo.create_account.side_effect = IntegrityError("insert", {}, None)
    service = CreditService(uow)

    result = await service.ensure_sufficient_balance(user_id)

    assert result is account
    uow.rollback.assert_not_awaited()
    assert uow.credit_repo.get_account_with_lock.await_count == 2


async def test_daily_checkin_recovers_from_concurrent_account_create() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=0)
    transaction = SimpleNamespace(id=uuid.uuid4(), amount=100)
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.side_effect = [None, account]
    uow.credit_repo.create_account.side_effect = IntegrityError("insert", {}, None)
    uow.credit_repo.add_transaction.return_value = transaction

    service = CreditService(uow)

    result_account, result_transaction = await service.daily_checkin(user_id)

    assert result_account is account
    assert result_transaction is transaction
    assert account.balance == 100
    uow.rollback.assert_not_awaited()
    uow.credit_repo.update_account_balance.assert_awaited_once_with(account.id, 100)


async def test_daily_checkin_rejects_duplicate_checkin() -> None:
    user_id = uuid.uuid4()
    account = make_account(balance=100)
    uow = make_uow()
    uow.credit_repo.get_account_with_lock.return_value = account
    uow.credit_repo.get_transaction_by_idempotency_key.return_value = SimpleNamespace(
        id=uuid.uuid4()
    )

    service = CreditService(uow)

    with pytest.raises(AppException) as exc_info:
        await service.daily_checkin(user_id)

    assert exc_info.value.code == "ALREADY_CHECKED_IN"
    uow.credit_repo.add_transaction.assert_not_awaited()


async def test_spend_for_model_usage_is_idempotent_for_same_message() -> None:
    user_id = uuid.uuid4()
    chat_message_id = uuid.uuid4()
    usage_record = SimpleNamespace(id=uuid.uuid4())
    transaction = SimpleNamespace(id=uuid.uuid4())
    uow = make_uow()
    uow.credit_repo.get_transaction_by_idempotency_key.return_value = transaction
    uow.credit_repo.get_usage_record_by_chat_message_id.return_value = usage_record

    service = CreditService(uow)

    result_usage_record, result_transaction = await service.spend_for_model_usage(
        user_id=user_id,
        tokens_input=10,
        tokens_output=5,
        model_name="default",
        chat_message_id=chat_message_id,
    )

    assert result_usage_record is usage_record
    assert result_transaction is transaction
    uow.credit_repo.try_decrement_balance.assert_not_awaited()
    uow.credit_repo.create_usage_record.assert_not_awaited()
    uow.credit_repo.add_transaction.assert_not_awaited()


async def test_expire_credits_does_not_charge_future_balance_for_spent_grants() -> None:
    account_id = uuid.uuid4()
    account = make_account(balance=100)
    uow = make_uow()
    uow.credit_repo.list_accounts_needing_expiration.return_value = [account_id]
    uow.credit_repo.get_account_by_id_with_lock.return_value = account
    uow.credit_repo.get_expired_grants_sum.return_value = 100
    uow.credit_repo.get_spent_sum.return_value = 100

    service = CreditService(uow)

    expired_count = await service.expire_credits()

    assert expired_count == 0
    assert account.balance == 100
    uow.credit_repo.update_account_balance.assert_not_awaited()
    uow.credit_repo.add_transaction.assert_not_awaited()


async def test_expire_credits_charges_only_unspent_expired_grants() -> None:
    account_id = uuid.uuid4()
    account = make_account(balance=100)
    uow = make_uow()
    uow.credit_repo.list_accounts_needing_expiration.return_value = [account_id]
    uow.credit_repo.get_account_by_id_with_lock.return_value = account
    uow.credit_repo.get_expired_grants_sum.return_value = 100
    uow.credit_repo.get_spent_sum.return_value = 40
    uow.credit_repo.add_transaction.return_value = SimpleNamespace(id=uuid.uuid4())

    service = CreditService(uow)

    expired_count = await service.expire_credits()

    assert expired_count == 1
    assert account.balance == 40
    uow.credit_repo.update_account_balance.assert_awaited_once_with(account.id, 40)
    uow.credit_repo.add_transaction.assert_awaited_once()
    assert uow.credit_repo.add_transaction.await_args.kwargs["amount"] == -60
    assert (
        uow.credit_repo.add_transaction.await_args.kwargs["metadata"]["spent_sum"] == 40
    )
