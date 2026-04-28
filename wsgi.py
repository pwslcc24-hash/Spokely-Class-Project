"""
WSGI entry point for Gunicorn.

  cd /path/to/project
  export SECRET_KEY=...   # or use a .env file (loaded from web_app)
  gunicorn -w 1 wsgi:app --bind 0.0.0.0:8000

Use a single worker (-w 1) with SQLite to limit concurrent write contention.
"""

from web_app import app  # noqa: F401  # side effect: app init + DB migrate on import

__all__ = ["app"]
