from __future__ import annotations

import logging
import time
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


def configure_observability(app: FastAPI, settings: Settings) -> None:
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

    _configure_metrics(app)


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
        started_at = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        duration = time.perf_counter() - started_at
        REQUEST_COUNT.labels(request.method, path, str(response.status_code)).inc()
        REQUEST_LATENCY.labels(request.method, path).observe(duration)

        span = trace.get_current_span()
        span_context = span.get_span_context()
        trace_id = (
            format(span_context.trace_id, "032x")
            if span_context and span_context.is_valid
            else "none"
        )
        span_id = (
            format(span_context.span_id, "016x")
            if span_context and span_context.is_valid
            else "none"
        )
        logger.info(
            "HTTP trace method=%s uri=%s status=%s durationMs=%s traceId=%s spanId=%s",
            request.method,
            request.url.path,
            response.status_code,
            int(duration * 1000),
            trace_id,
            span_id,
        )
        return response


def prometheus_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
