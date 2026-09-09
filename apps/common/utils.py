import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def sanitize_string(value: str) -> str:
    """Strips leading, trailing, and excessive internal whitespace from a string."""
    if not value:
        return ""
    return " ".join(value.split()).strip()


def exclude_slashless_duplicate_routes(endpoints):
    """
    Preprocessing hook for drf-spectacular: excludes duplicate slashless routes from Swagger UI.
    Only canonical routes ending with '/' are documented, while both slashed and slashless
    endpoints remain fully functional at runtime.
    """
    return [
        (path, path_regex, method, callback)
        for path, path_regex, method, callback in endpoints
        if path.endswith('/')
    ]

