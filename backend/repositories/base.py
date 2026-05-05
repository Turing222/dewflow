from collections.abc import Sequence
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)


class CRUDBase[ModelType, CreateSchemaType: BaseModel, UpdateSchemaType: BaseModel]:
    def __init__(self, model: type[ModelType], session: AsyncSession) -> None:
        self.model = model
        self.session = session

    async def get(self, id: Any) -> ModelType | None:
        """根据主键读取单条记录。"""
        return await self.session.get(self.model, id)

    async def get_by(self, **kwargs: Any) -> ModelType | None:
        """按唯一约束字段读取单条记录。"""
        statement = select(self.model).filter_by(**kwargs)
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_multi(
        self, *, skip: int = 0, limit: int = 100
    ) -> Sequence[ModelType]:
        """分页读取记录列表。"""
        stmt = select(self.model).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create(self, *, obj_in: CreateSchemaType | dict[str, Any]) -> ModelType:
        """创建记录并刷新数据库默认值。"""
        if isinstance(obj_in, dict):
            create_data = obj_in
        else:
            create_data = obj_in.model_dump()

        db_obj = self.model(**create_data)

        self.session.add(db_obj)
        await self.session.flush()
        await self.session.refresh(db_obj)

        return db_obj

    async def update(
        self,
        *,
        db_obj: ModelType,
        obj_in: UpdateSchemaType | dict[str, Any],
    ) -> ModelType:
        """更新记录并刷新数据库默认值。"""
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        unknown_fields = [field for field in update_data if not hasattr(db_obj, field)]
        if unknown_fields:
            field_text = ", ".join(sorted(unknown_fields))
            raise ValueError(
                f"Unknown fields for {type(db_obj).__name__} update: {field_text}"
            )

        for field, value in update_data.items():
            setattr(db_obj, field, value)

        self.session.add(db_obj)
        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj

    async def remove(self, *, id: Any) -> ModelType | None:
        """按主键删除记录，记录不存在时返回 None。"""
        obj = await self.session.get(self.model, id)
        if obj:
            await self.session.delete(obj)
            await self.session.flush()
        return obj
