"""App-wide error handlers.

Interview note: FastAPI's default 422 body echoes each rejected value ("input"), which
for /auth/register means the password. Error bodies end up in proxy logs, browser
devtools and bug reports, so the rejected value is dropped. Field location, error type
and message are enough for the frontend to show the problem.
"""

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def validation_error_without_input(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101 - registered only for this type
    errors = [{key: value for key, value in e.items() if key != "input"} for e in exc.errors()]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": jsonable_encoder(errors)},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_error_without_input)
