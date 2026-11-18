"""ASGI entry point for `fastapi dev app/main.py` and uvicorn.

load_config() runs at import time on purpose: a misconfigured deploy fails at startup
with a clear list of problems, not on the first request.
"""

from app.core.config import load_config
from app.factory import create_app

app = create_app(load_config())
