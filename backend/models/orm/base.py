"""SQLAlchemy declarative base and shared ORM mixins.

职责：集中定义模型基类、ID 生成策略和审计时间字段。
边界：本模块不声明业务表，只提供 ORM 模型的公共结构。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from ulid import ULID

naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "%(table_name)s_pkey",
}


class IDGenerator:
    """生成应用层主键。"""

    @staticmethod
    def new_ulid_as_uuid() -> uuid.UUID:
        return ULID().to_uuid()


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类。"""

    metadata = MetaData(naming_convention=naming_convention)


class BaseIdModel:
    """提供基于 ULID 的 UUID 主键。"""

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        # ULID 由应用层生成，数据库默认值只作为直接 SQL 写入时的兜底。
        default=IDGenerator.new_ulid_as_uuid,
        nullable=False,
        comment="基于ULID生成的唯一标识",
        server_default=text("gen_random_uuid()"),
    )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id}>"


class AuditMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="最后更新时间",
    )
