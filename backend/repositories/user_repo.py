import uuid
from collections.abc import Sequence
from typing import Any, TypedDict

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.orm.user import User
from backend.models.schemas.user_schema import UserUpdate
from backend.repositories.base import CRUDBase


class UserCreateData(TypedDict):
    username: str
    email: str
    hashed_password: str
    max_tokens: int


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.crud: CRUDBase[User, BaseModel, UserUpdate] = CRUDBase(User, session)

    async def get(self, id: Any) -> User | None:
        return await self.crud.get(id)

    async def get_multi(
        self, *, skip: int = 0, limit: int = 100
    ) -> Sequence[User]:
        return await self.crud.get_multi(skip=skip, limit=limit)

    async def create(self, *, obj_in: UserCreateData) -> User:
        create_data: dict[str, Any] = {
            "username": obj_in["username"],
            "email": obj_in["email"],
            "hashed_password": obj_in["hashed_password"],
            "max_tokens": obj_in["max_tokens"],
        }
        return await self.crud.create(obj_in=create_data)

    async def update(
        self, *, db_obj: User, obj_in: UserUpdate | dict[str, Any]
    ) -> User:
        return await self.crud.update(db_obj=db_obj, obj_in=obj_in)

    async def remove(self, *, id: Any) -> User | None:
        return await self.crud.remove(id=id)

    async def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == email)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_by_username(self, username: str) -> User | None:
        statement = select(User).where(User.username == username)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_existing_usernames(self, usernames: list[str]) -> set[str]:
        """返回数据库中已存在的用户名集合。"""
        if not usernames:
            return set()

        # 只查询 username 字段，避免批量导入预检查读取整行用户数据。
        stmt = select(User.username).where(User.username.in_(usernames))
        result = await self.session.execute(stmt)

        return set(result.scalars().all())

    async def bulk_upsert(self, user_maps: list[dict[str, str]]) -> None:
        """
        执行 Postgres 专用的 upsert 逻辑
        """
        required_keys = {"username", "email", "hashed_password"}
        normalized_rows: list[dict[str, str]] = []
        for idx, row in enumerate(user_maps):
            missing = required_keys.difference(row.keys())
            if missing:
                missing_text = ", ".join(sorted(missing))
                raise ValueError(f"row {idx} is missing required keys: {missing_text}")
            normalized_rows.append(
                {
                    "username": row["username"],
                    "email": row["email"],
                    "hashed_password": row["hashed_password"],
                }
            )

        stmt = pg_insert(User).values(normalized_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["email"], set_={"username": stmt.excluded.username}
        )
        await self.session.execute(stmt)

    async def increment_used_tokens(self, user_id: uuid.UUID, amount: int) -> None:
        """
        原子增加用户的已用 Token 数。
        使用 SQL 级别的原子操作 (SET used_tokens = used_tokens + amount)，
        避免并发下的「读-改-写」丢失更新问题。

        注意：此方法不做上限检查，适用于非关键路径（如后台统计）。
        关键对话路径请使用 increment_used_tokens_guarded。
        """
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(used_tokens=User.used_tokens + amount)
        )
        await self.session.execute(stmt)

    async def get_with_lock(self, user_id: uuid.UUID) -> User | None:
        """
        SELECT FOR UPDATE 读取用户行，锁定直到当前事务结束。

        用于余额检查前的悲观锁读，防止多个并发请求同时通过余额校验（TOCTOU）。
        必须在已开启事务的 UoW 上下文内调用（即 async with uow 块中）。
        """
        stmt = select(User).where(User.id == user_id).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def increment_used_tokens_guarded(
        self,
        user_id: uuid.UUID,
        amount: int,
    ) -> bool:
        """
        带上限检查的条件原子 Token 累加（R1 + R5 修复）。

        实现：单条 UPDATE WHERE used_tokens + amount <= max_tokens。
        若未返回更新后的用户 ID，表示额度不足或用户不存在。

        此方法是原子的，不存在读-改-写竞态，与 get_with_lock 配合可彻底
        消除高并发下的 Token 超支问题。
        """
        stmt = (
            update(User)
            .where(
                User.id == user_id,
                User.used_tokens + amount <= User.max_tokens,
            )
            .values(used_tokens=User.used_tokens + amount)
            .returning(User.id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
