"""Module-level entry shim so 'uvicorn main:app' (old style) also works."""
from app.main import app  # noqa: F401
