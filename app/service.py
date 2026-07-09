from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from typing import TypeVar

from fastapi import HTTPException, status
from opentelemetry import trace
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session

from app.models import Item
from app.schemas import ItemRequest, ItemResponse, PageResponse


logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
T = TypeVar("T")

SORT_COLUMNS = {
    "id": Item.id,
    "name": Item.name,
    "createdAt": Item.created_at,
    "created_at": Item.created_at,
    "updatedAt": Item.updated_at,
    "updated_at": Item.updated_at,
}


def list_items(
    db: Session, page: int = 0, size: int = 20, sort: str = "id"
) -> PageResponse[ItemResponse]:
    page = max(page, 0)
    size = min(max(size, 1), 100)

    return _trace_operation(
        "ItemService.list",
        lambda: _list_items(db, page, size, sort),
        {"page": str(page), "size": str(size)},
    )


def get_item(db: Session, item_id: int) -> ItemResponse:
    item = _trace_operation(
        "ItemService.get",
        lambda: _find_item(db, item_id),
        {"item.id": str(item_id)},
    )
    logger.info("ItemService.get id=%s", item_id)
    return ItemResponse.model_validate(item)


def create_item(db: Session, request: ItemRequest) -> ItemResponse:
    def operation() -> ItemResponse:
        item = Item(name=request.name, description=request.description)
        db.add(item)
        db.commit()
        db.refresh(item)
        logger.info("ItemService.create id=%s name=%s", item.id, item.name)
        return ItemResponse.model_validate(item)

    return _trace_operation(
        "ItemService.create",
        operation,
        {"item.name": request.name},
    )


def update_item(db: Session, item_id: int, request: ItemRequest) -> ItemResponse:
    def operation() -> ItemResponse:
        item = _find_item(db, item_id)
        item.name = request.name
        item.description = request.description
        db.commit()
        db.refresh(item)
        logger.info("ItemService.update id=%s name=%s", item.id, item.name)
        return ItemResponse.model_validate(item)

    return _trace_operation(
        "ItemService.update",
        operation,
        {"item.id": str(item_id), "item.name": request.name},
    )


def delete_item(db: Session, item_id: int) -> None:
    def operation() -> None:
        item = _find_item(db, item_id)
        db.delete(item)
        db.commit()
        logger.info("ItemService.delete id=%s", item_id)

    _trace_operation("ItemService.delete", operation, {"item.id": str(item_id)})


def _list_items(
    db: Session, page: int, size: int, sort_spec: str
) -> PageResponse[ItemResponse]:
    order_by = _parse_sort(sort_spec)
    total = db.scalar(select(func.count()).select_from(Item)) or 0
    items = db.scalars(
        select(Item).order_by(order_by).offset(page * size).limit(size)
    ).all()
    total_pages = math.ceil(total / size) if total else 0
    response = PageResponse[ItemResponse](
        content=[ItemResponse.model_validate(item) for item in items],
        page=page,
        size=size,
        totalElements=total,
        totalPages=total_pages,
        first=page == 0,
        last=total_pages == 0 or page >= total_pages - 1,
    )
    logger.info(
        "ItemService.list page=%s size=%s totalElements=%s",
        response.page,
        response.size,
        response.total_elements,
    )
    return response


def _find_item(db: Session, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item not found: {item_id}",
        )
    return item


def _parse_sort(sort_spec: str):
    parts = [part.strip() for part in sort_spec.split(",") if part.strip()]
    direction = asc
    column_name = parts[0] if parts else "id"
    if column_name.startswith("-"):
        column_name = column_name[1:]
        direction = desc
    if len(parts) > 1 and parts[1].lower() == "desc":
        direction = desc
    column = SORT_COLUMNS.get(column_name, Item.id)
    return direction(column)


def _trace_operation(
    span_name: str, operation: Callable[[], T], attributes: dict[str, str] | None = None
) -> T:
    started_at = time.perf_counter()
    with tracer.start_as_current_span(span_name) as span:
        for key, value in (attributes or {}).items():
            span.set_attribute(key, value)
        try:
            result = operation()
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            span.set_attribute("duration.ms", duration_ms)
            logger.info("%s completed durationMs=%s", span_name, duration_ms)
            return result
        except Exception as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            span.set_attribute("duration.ms", duration_ms)
            span.record_exception(exc)
            logger.warning(
                "%s failed durationMs=%s error=%s",
                span_name,
                duration_ms,
                exc.__class__.__name__,
            )
            raise
