from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.repositories.user_repo import UserCreateData, UserRepository


@pytest.fixture
def repo_ctx():
    session = AsyncMock()
    repo = UserRepository(session=session)
    return repo, session


@pytest.mark.asyncio
async def test_get_by_email_returns_first_match(repo_ctx):
    repo, session = repo_ctx
    expected = MagicMock()
    result_proxy = MagicMock()
    scalars_proxy = MagicMock()
    scalars_proxy.first.return_value = expected
    result_proxy.scalars.return_value = scalars_proxy
    session.execute.return_value = result_proxy

    result = await repo.get_by_email("alice@example.com")

    assert result is expected
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "users.email" in sql


@pytest.mark.asyncio
async def test_get_by_username_returns_first_match(repo_ctx):
    repo, session = repo_ctx
    expected = MagicMock()
    result_proxy = MagicMock()
    scalars_proxy = MagicMock()
    scalars_proxy.first.return_value = expected
    result_proxy.scalars.return_value = scalars_proxy
    session.execute.return_value = result_proxy

    result = await repo.get_by_username("alice")

    assert result is expected
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "users.username" in sql


@pytest.mark.asyncio
async def test_get_existing_usernames_short_circuits_on_empty_input(repo_ctx):
    repo, session = repo_ctx

    result = await repo.get_existing_usernames([])

    assert result == set()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_existing_usernames_returns_set(repo_ctx):
    repo, session = repo_ctx
    result_proxy = MagicMock()
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = ["alice", "bob", "alice"]
    result_proxy.scalars.return_value = scalars_proxy
    session.execute.return_value = result_proxy

    result = await repo.get_existing_usernames(["alice", "bob", "charlie"])

    assert result == {"alice", "bob"}
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_multi_returns_empty_sequence(repo_ctx):
    repo, session = repo_ctx
    result_proxy = MagicMock()
    scalars_proxy = MagicMock()
    scalars_proxy.all.return_value = []
    result_proxy.scalars.return_value = scalars_proxy
    session.execute.return_value = result_proxy

    result = await repo.get_multi()

    assert result == []


@pytest.mark.asyncio
async def test_create_accepts_persistence_data_only(repo_ctx):
    repo, _ = repo_ctx
    expected = MagicMock()
    repo.crud.create = AsyncMock(return_value=expected)
    obj_in = UserCreateData(
        username="alice",
        email="alice@example.com",
        hashed_password="hashed-password",
        max_tokens=100000,
    )

    result = await repo.create(obj_in=obj_in)

    assert result is expected
    create_data = repo.crud.create.await_args.kwargs["obj_in"]
    assert create_data == {
        "username": "alice",
        "email": "alice@example.com",
        "hashed_password": "hashed-password",
        "max_tokens": 100000,
    }
    assert "password" not in create_data
    assert "confirm_password" not in create_data


@pytest.mark.asyncio
async def test_bulk_upsert_validates_required_keys(repo_ctx):
    repo, _ = repo_ctx

    with pytest.raises(ValueError, match="missing required keys"):
        await repo.bulk_upsert(
            [
                {
                    "username": "alice",
                    "email": "alice@example.com",
                    # hashed_password intentionally missing
                }
            ]
        )


@pytest.mark.asyncio
async def test_bulk_upsert_executes_insert_statement(repo_ctx):
    repo, session = repo_ctx

    await repo.bulk_upsert(
        [
            {
                "username": "alice",
                "email": "alice@example.com",
                "hashed_password": "hash-a",
            },
            {
                "username": "bob",
                "email": "bob@example.com",
                "hashed_password": "hash-b",
            },
        ]
    )

    session.execute.assert_awaited_once()
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "INSERT INTO users" in sql
    assert "ON CONFLICT (email) DO UPDATE" in sql


@pytest.mark.asyncio
async def test_increment_used_tokens_executes_atomic_update(repo_ctx):
    repo, session = repo_ctx
    user_id = uuid.uuid4()

    await repo.increment_used_tokens(user_id=user_id, amount=5)

    session.execute.assert_awaited_once()
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "UPDATE users SET used_tokens=" in sql
    assert "users.used_tokens +" in sql


@pytest.mark.asyncio
async def test_try_increment_used_tokens_with_limit_returns_true_when_row_updated(repo_ctx):
    repo, session = repo_ctx
    user_id = uuid.uuid4()
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = user_id
    session.execute.return_value = result_proxy

    result = await repo.try_increment_used_tokens_with_limit(user_id=user_id, amount=5)

    assert result is True
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "UPDATE users SET used_tokens=" in sql
    assert "RETURNING users.id" in sql


@pytest.mark.asyncio
async def test_try_increment_used_tokens_with_limit_returns_false_when_no_row_updated(
    repo_ctx,
):
    repo, session = repo_ctx
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = None
    session.execute.return_value = result_proxy

    result = await repo.try_increment_used_tokens_with_limit(
        user_id=uuid.uuid4(),
        amount=5,
    )

    assert result is False
