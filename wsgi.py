"""WSGI entrypoint for production servers (Gunicorn/uWSGI).

Example:
    gunicorn -w 2 -b 127.0.0.1:8000 wsgi:app

Configure secrets/DB via environment variables (see README.md).
"""

from app import app

__all__ = ["app"]
