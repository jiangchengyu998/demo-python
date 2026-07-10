from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote_plus, urlparse


DEFAULT_JDBC_URL = (
    "jdbc:mysql://192.168.50.18:3306/cloud_deploy_demo"
    "?createDatabaseIfNotExist=true&useUnicode=true&characterEncoding=utf8"
    "&useSSL=false&allowPublicKeyRetrieval=true&serverTimezone=Asia/Shanghai"
)

DEFAULT_LOCAL_DATABASE_URL = "sqlite+pysqlite:///./cloud_deploy_demo.db"
DEFAULT_OTEL_ENDPOINT = (
    "http://opentelemetry-collector.observability.svc.cluster.local:4318/v1/traces"
)
DEFAULT_SERVER_PORT = 8000

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    app_name: str
    deployment_environment: str
    database_url: str
    server_port: int
    otel_traces_endpoint: str
    otel_debug_logging_enabled: bool
    otel_sdk_disabled: bool
    tracing_sampling_probability: float


def get_settings() -> Settings:
    deployment_environment = os.getenv("DEPLOYMENT_ENVIRONMENT", "local")
    otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", DEFAULT_OTEL_ENDPOINT)
    return Settings(
        app_name=os.getenv("SPRING_APPLICATION_NAME", "cloud-deploy-demo-python"),
        deployment_environment=deployment_environment,
        database_url=_database_url_from_env(),
        server_port=_server_port_from_env(),
        otel_traces_endpoint=otel_endpoint,
        otel_debug_logging_enabled=_env_bool("OTEL_DEBUG_LOGGING_ENABLED", True),
        otel_sdk_disabled=_otel_sdk_disabled(deployment_environment),
        tracing_sampling_probability=float(
            os.getenv("MANAGEMENT_TRACING_SAMPLING_PROBABILITY", "1.0")
        ),
    )


def _database_url_from_env() -> str:
    direct_url = os.getenv("DATABASE_URL")
    if direct_url:
        return direct_url

    if not _has_spring_datasource_env():
        return DEFAULT_LOCAL_DATABASE_URL

    jdbc_url = os.getenv("SPRING_DATASOURCE_URL", DEFAULT_JDBC_URL)
    username = os.getenv("SPRING_DATASOURCE_USERNAME", "root")
    password = os.getenv("SPRING_DATASOURCE_PASSWORD", "")

    if jdbc_url.startswith("jdbc:mysql://"):
        return _mysql_jdbc_to_sqlalchemy_url(jdbc_url, username, password)

    logger.warning("Using SPRING_DATASOURCE_URL as a raw SQLAlchemy URL")
    return jdbc_url


def _mysql_jdbc_to_sqlalchemy_url(jdbc_url: str, username: str, password: str) -> str:
    parsed = urlparse(jdbc_url.removeprefix("jdbc:"))
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    charset = query.get("characterEncoding") or query.get("charset") or "utf8mb4"
    database = parsed.path.lstrip("/")
    auth = quote_plus(username)
    if password:
        auth = f"{auth}:{quote_plus(password)}"
    return f"mysql+pymysql://{auth}@{parsed.netloc}/{database}?charset={charset}"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _server_port_from_env() -> int:
    return int(os.getenv("PORT", os.getenv("SERVER_PORT", str(DEFAULT_SERVER_PORT))))


def _has_spring_datasource_env() -> bool:
    return any(
        os.getenv(name)
        for name in (
            "SPRING_DATASOURCE_URL",
            "SPRING_DATASOURCE_USERNAME",
            "SPRING_DATASOURCE_PASSWORD",
        )
    )


def _otel_sdk_disabled(deployment_environment: str) -> bool:
    explicit = os.getenv("OTEL_SDK_DISABLED")
    if explicit is not None:
        return _env_bool("OTEL_SDK_DISABLED", False)
    return (
        deployment_environment == "local"
        and os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") is None
    )
