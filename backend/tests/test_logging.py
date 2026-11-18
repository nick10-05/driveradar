"""Structured logging: JSON lines, request IDs on every line, secrets redacted."""

import json
import logging
import re
from collections.abc import Iterator
from typing import Any

import pytest
import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging import REDACTED, configure_logging
from app.factory import create_app


def log_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    """Parse every JSON log line written to stdout so far."""
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.startswith("{")]


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    app = create_app(settings)

    async def boom() -> None:
        raise RuntimeError("kaboom")

    app.add_api_route("/boom", boom)
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


class TestRequestId:
    def test_generates_an_id_when_none_is_sent(self, client: TestClient) -> None:
        response = client.get("/healthz")

        assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])

    def test_each_request_gets_a_new_id(self, client: TestClient) -> None:
        first = client.get("/healthz").headers["X-Request-ID"]
        second = client.get("/healthz").headers["X-Request-ID"]

        assert first != second

    def test_valid_incoming_id_is_reused(self, client: TestClient) -> None:
        response = client.get("/healthz", headers={"X-Request-ID": "render-abc.123_X"})

        assert response.headers["X-Request-ID"] == "render-abc.123_X"

    @pytest.mark.parametrize(
        "bad_id",
        ["", "x" * 65, "has space", "inject\\nfake-log-line", "<script>", "a;b"],
    )
    def test_unsafe_incoming_id_is_replaced(self, client: TestClient, bad_id: str) -> None:
        response = client.get("/healthz", headers={"X-Request-ID": bad_id})

        assert response.headers["X-Request-ID"] != bad_id
        assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


class TestRequestLog:
    def test_one_json_access_line_per_request_with_the_same_id(
        self, capsys: pytest.CaptureFixture[str], settings: Settings
    ) -> None:
        app = create_app(settings.model_copy(update={"log_level": "DEBUG"}))
        with TestClient(app) as client:
            capsys.readouterr()  # drop startup output

            response = client.get("/readyz?token=secret-in-query")  # DB down in tests → 503

        lines = [line for line in log_lines(capsys) if line["event"] == "request"]
        assert len(lines) == 1
        line = lines[0]
        assert line["request_id"] == response.headers["X-Request-ID"]
        assert line["method"] == "GET"
        assert line["path"] == "/readyz"  # query string is never logged
        assert line["status_code"] == 503
        assert isinstance(line["duration_ms"], float)
        assert line["level"] == "debug"
        assert "timestamp" in line

    def test_health_probes_are_quiet_at_info_level(
        self, capsys: pytest.CaptureFixture[str], client: TestClient
    ) -> None:
        capsys.readouterr()

        client.get("/healthz")

        assert [line for line in log_lines(capsys) if line["event"] == "request"] == []

    def test_logs_inside_a_request_carry_its_request_id(
        self, capsys: pytest.CaptureFixture[str], client: TestClient
    ) -> None:
        capsys.readouterr()

        response = client.get("/readyz")  # check_database logs "database_unreachable"

        warning = next(
            line for line in log_lines(capsys) if line["event"] == "database_unreachable"
        )
        assert warning["request_id"] == response.headers["X-Request-ID"]
        assert warning["level"] == "warning"

    def test_normal_requests_log_at_info(
        self, capsys: pytest.CaptureFixture[str], client: TestClient
    ) -> None:
        capsys.readouterr()

        client.get("/does-not-exist")

        line = next(line for line in log_lines(capsys) if line["event"] == "request")
        assert line["status_code"] == 404
        assert line["level"] == "info"

    def test_unhandled_error_is_logged_with_request_id_and_500(
        self, capsys: pytest.CaptureFixture[str], client: TestClient
    ) -> None:
        capsys.readouterr()

        response = client.get("/boom", headers={"X-Request-ID": "trace-me"})

        assert response.status_code == 500
        lines = log_lines(capsys)
        failure = next(line for line in lines if line["event"] == "request_failed")
        assert failure["request_id"] == "trace-me"
        assert "RuntimeError" in failure["exception"]
        access = next(line for line in lines if line["event"] == "request")
        assert access["status_code"] == 500
        assert access["request_id"] == "trace-me"

    def test_request_id_does_not_leak_into_logs_after_the_request(
        self, capsys: pytest.CaptureFixture[str], client: TestClient
    ) -> None:
        client.get("/healthz")
        capsys.readouterr()

        structlog.get_logger().info("background_job")

        line = next(line for line in log_lines(capsys) if line["event"] == "background_job")
        assert "request_id" not in line


class TestConfigureLogging:
    def test_secrets_are_redacted_at_any_depth(
        self, settings: Settings, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(settings)

        structlog.get_logger().info(
            "login_attempt",
            email="student@example.com",
            password="hunter2",  # noqa: S106 - fake value; the test checks it gets redacted
            headers={"Authorization": "Bearer abc", "Cookie": "__Host-session=xyz"},
            llm_api_key="sk-123",
        )

        line = log_lines(capsys)[-1]
        assert line["email"] == "student@example.com"
        assert line["password"] == REDACTED
        assert line["headers"] == {"Authorization": REDACTED, "Cookie": REDACTED}
        assert line["llm_api_key"] == REDACTED
        assert "hunter2" not in json.dumps(line)

    def test_stdlib_loggers_are_json_too(
        self, settings: Settings, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(settings)

        logging.getLogger("uvicorn.error").warning("from uvicorn")

        line = log_lines(capsys)[-1]
        assert line["event"] == "from uvicorn"
        assert line["level"] == "warning"

    def test_log_level_setting_filters_lower_levels(
        self, settings: Settings, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(settings.model_copy(update={"log_level": "WARNING"}))

        structlog.get_logger().info("hidden")
        structlog.get_logger().warning("shown")

        events = [line["event"] for line in log_lines(capsys)]
        assert "hidden" not in events
        assert "shown" in events

    def test_dev_uses_readable_console_output(
        self, settings: Settings, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(settings.model_copy(update={"environment": "dev"}))

        structlog.get_logger().info("hello_dev")

        out = capsys.readouterr().out
        assert "hello_dev" in out
        assert not out.strip().startswith("{")
