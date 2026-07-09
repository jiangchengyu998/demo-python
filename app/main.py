from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db, migrate_database
from app.observability import configure_observability, prometheus_response
from app.schemas import ApiError, ItemRequest, ItemResponse, PageResponse
from app.service import create_item, delete_item, get_item, list_items, update_item


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    migrate_database()
    yield


app = FastAPI(
    title="Cloud Deploy Python Demo",
    description="FastAPI CRUD demo for cloud one-click deployment",
    version="0.1.0",
    docs_url="/swagger-ui.html",
    openapi_url="/v3/api-docs",
    lifespan=lifespan,
)
configure_observability(app, settings)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return _error_response(exc.status_code, _reason_phrase(exc.status_code), str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        f"{'.'.join(str(part) for part in error['loc'] if part != 'body')}: {error['msg']}"
        for error in exc.errors()
    ]
    return _error_response(
        status.HTTP_400_BAD_REQUEST,
        "Bad Request",
        "Request validation failed",
        details,
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> str:
    return INDEX_HTML


@app.get("/api/items", response_model=PageResponse[ItemResponse], tags=["Items"])
def list_api_items(
    page: int = Query(default=0, ge=0),
    size: int = Query(default=20, ge=1, le=100),
    sort: str = Query(default="id"),
    db: Session = Depends(get_db),
) -> PageResponse[ItemResponse]:
    return list_items(db, page=page, size=size, sort=sort)


@app.get("/api/items/{item_id}", response_model=ItemResponse, tags=["Items"])
def get_api_item(item_id: int, db: Session = Depends(get_db)) -> ItemResponse:
    return get_item(db, item_id)


@app.post(
    "/api/items",
    response_model=ItemResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Items"],
)
def create_api_item(request: ItemRequest, db: Session = Depends(get_db)) -> ItemResponse:
    return create_item(db, request)


@app.put("/api/items/{item_id}", response_model=ItemResponse, tags=["Items"])
def update_api_item(
    item_id: int, request: ItemRequest, db: Session = Depends(get_db)
) -> ItemResponse:
    return update_item(db, item_id, request)


@app.delete(
    "/api/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    tags=["Items"],
)
def delete_api_item(item_id: int, db: Session = Depends(get_db)) -> Response:
    delete_item(db, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/actuator/health", tags=["Actuator"])
def health() -> dict[str, str]:
    return {"status": "UP"}


@app.get("/actuator/prometheus", include_in_schema=False)
def prometheus() -> Response:
    return prometheus_response()


def _error_response(
    status_code: int, error: str, message: str, details: list[str] | None = None
) -> JSONResponse:
    body = ApiError(
        timestamp=datetime.now(tz=UTC),
        status=status_code,
        error=error,
        message=message,
        details=details or [],
    )
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def _reason_phrase(status_code: int) -> str:
    return {
        status.HTTP_400_BAD_REQUEST: "Bad Request",
        status.HTTP_404_NOT_FOUND: "Not Found",
        status.HTTP_500_INTERNAL_SERVER_ERROR: "Internal Server Error",
    }.get(status_code, "Error")


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>云朵平台 Python Demo</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f9fc;
      --panel: #ffffff;
      --text: #172033;
      --muted: #62708a;
      --line: #d9e1ee;
      --primary: #1769e0;
      --primary-hover: #1157bd;
      --accent: #15a36d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--text);
      background: linear-gradient(180deg, rgba(23,105,224,.08), rgba(21,163,109,.06)), var(--bg);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 32px 16px;
    }
    main {
      width: min(720px, 100%);
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 40px;
      box-shadow: 0 18px 50px rgba(23,32,51,.08);
    }
    .eyebrow {
      margin: 0 0 12px;
      color: var(--accent);
      font-size: 14px;
      font-weight: 700;
    }
    h1 {
      margin: 0;
      font-size: 34px;
      line-height: 1.2;
      font-weight: 750;
    }
    p {
      margin: 18px 0 0;
      color: var(--muted);
      font-size: 17px;
      line-height: 1.7;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 28px;
    }
    a {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 44px;
      padding: 0 18px;
      border-radius: 6px;
      font-weight: 700;
      text-decoration: none;
    }
    .primary { color: #ffffff; background: var(--primary); }
    .primary:hover { background: var(--primary-hover); }
    .secondary {
      color: var(--text);
      border: 1px solid var(--line);
      background: #ffffff;
    }
    .meta {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 32px;
    }
    .meta div {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 14px;
      color: var(--muted);
      font-size: 14px;
    }
    .meta strong {
      display: block;
      margin-bottom: 4px;
      color: var(--text);
      font-size: 15px;
    }
    @media (max-width: 640px) {
      main { padding: 28px 20px; }
      h1 { font-size: 28px; }
      .meta { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
<main>
  <p class="eyebrow">Cloud Deploy Python Demo</p>
  <h1>云朵平台 Python FastAPI Demo</h1>
  <p>
    这是用于云朵一键部署平台的 Python 示例应用，包含标准 CRUD 接口，
    并接入 MySQL、Swagger/OpenAPI、Prometheus 和 OpenTelemetry。
  </p>
  <div class="actions">
    <a class="primary" href="/swagger-ui.html">打开 Swagger</a>
    <a class="secondary" href="/actuator/health">查看健康检查</a>
  </div>
  <section class="meta" aria-label="Demo capabilities">
    <div><strong>CRUD API</strong>/api/items</div>
    <div><strong>Metrics</strong>/actuator/prometheus</div>
    <div><strong>Tracing</strong>OTEL OTLP</div>
  </section>
</main>
</body>
</html>
"""
