from fastapi import Request

from backend.contracts.interfaces import AbstractUnitOfWork
from backend.services.unit_of_work import SQLAlchemyUnitOfWork


async def get_uow(request: Request) -> AbstractUnitOfWork:
    return SQLAlchemyUnitOfWork(request.app.state.session_factory)
