import re
from typing import Callable, Awaitable


def slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')


async def generate_unique_code(
    base_slug: str,
    check_exists: Callable[[str], Awaitable[bool]]
) -> str:
    """
    Generate unique code by appending -1, -2, etc. if code already exists (async version).

    Args:
        base_slug: The base slug (e.g., "my-shapefile")
        check_exists: Async function that returns True if code exists in DB

    Returns:
        Unique code (e.g., "my-shapefile" or "my-shapefile-1" or "my-shapefile-2")
    """
    code = base_slug
    sequence = 1

    while await check_exists(code):
        code = f"{base_slug}-{sequence}"
        sequence += 1

    return code


def generate_unique_code_sync(
    base_slug: str,
    check_exists: Callable[[str], bool]
) -> str:
    """
    Generate unique code by appending -1, -2, etc. if code already exists (sync version).

    Args:
        base_slug: The base slug (e.g., "my-shapefile")
        check_exists: Sync function that returns True if code exists in DB

    Returns:
        Unique code (e.g., "my-shapefile" or "my-shapefile-1" or "my-shapefile-2")
    """
    code = base_slug
    sequence = 1

    while check_exists(code):
        code = f"{base_slug}-{sequence}"
        sequence += 1

    return code
