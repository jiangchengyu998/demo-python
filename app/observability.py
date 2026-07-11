from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.config import Settings
from app.database import engine


logger = logging.getLogger(__name__)
_record_factory_installed = False
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="none")
_span_id_var: ContextVar[str] = ContextVar("span_id", default="none")

REQUEST_COUNT = Counter(
    "http_server_requests_total",
    "Total HTTP requests",
    ("method", "path", "status"),
)
REQUEST_LATENCY = Histogram(
    "http_server_request_duration_seconds",
    "HTTP request latency",
    ("method", "path"),
)


def configure_logging() -> None:
    global _record_factory_installed
    if not _record_factory_installed:
        previous_factory = logging.getLogRecordFactory()

        def record_factory(*args, **kwargs):
            record = previous_factory(*args, **kwargs)
            trace_id, span_id = current_trace_fields()
            record.trace_id = trace_id
            record.span_id = span_id
            return record

        logging.setLogRecordFactory(record_factory)
        _record_factory_installed = True

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s %(levelname)s %(name)s "
            "traceId=%(trace_id)s spanId=%(span_id)s - %(message)s"
        ),
    )


def configure_observability(app: FastAPI, settings: Settings) -> None:
    _configure_metrics(app)

    if settings.otel_sdk_disabled:
        logger.info("OTEL SDK disabled")
    else:
        _configure_tracing(app, settings)

        if settings.otel_debug_logging_enabled:
            logger.info(
                "OTEL debug logging enabled: serviceName=%s, environment=%s, "
                "tracesEndpoint=%s, samplingProbability=%s",
                settings.app_name,
                settings.deployment_environment,
                settings.otel_traces_endpoint,
                settings.tracing_sampling_probability,
            )

def _configure_tracing(app: FastAPI, settings: Settings) -> None:
    resource = Resource.create(
        {
            "service.name": settings.app_name,
            "deployment.environment": settings.deployment_environment,
        }
    )
    provider = TracerProvider(
        resource=resource,
        sampler=TraceIdRatioBased(settings.tracing_sampling_probability),
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_traces_endpoint))
    )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    SQLAlchemyInstrumentor().instrument(engine=engine)


def _configure_metrics(app: FastAPI) -> None:
    @app.middleware("http")
    async def metrics_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        trace_token = _trace_id_var.set("none")
        span_token = _span_id_var.set("none")
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            duration = time.perf_counter() - started_at
            REQUEST_COUNT.labels(request.method, path, str(response.status_code)).inc()
            REQUEST_LATENCY.labels(request.method, path).observe(duration)

            logger.info(
                "HTTP trace method=%s uri=%s status=%s durationMs=%s",
                request.method,
                request.url.path,
                response.status_code,
                int(duration * 1000),
            )
            return response
        finally:
            _trace_id_var.reset(trace_token)
            _span_id_var.reset(span_token)


def current_trace_fields() -> tuple[str, str]:
    span = trace.get_current_span()
    span_context = span.get_span_context()
    if not span_context or not span_context.is_valid:
        return _trace_id_var.get(), _span_id_var.get()
    trace_id = format(span_context.trace_id, "032x")
    span_id = format(span_context.span_id, "016x")
    _trace_id_var.set(trace_id)
    _span_id_var.set(span_id)
    return trace_id, span_id


def prometheus_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
