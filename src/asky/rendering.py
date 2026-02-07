"""Browser rendering utilities for asky."""

import logging
import re
import tempfile
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

from asky.config import ARCHIVE_DIR
from asky.core.utils import generate_slug

logger = logging.getLogger(__name__)


# Regex pattern to extract H1 markdown header (# Title)
H1_PATTERN = re.compile(r"^#\s+(.+?)(?:\n|$)", re.MULTILINE)


def extract_markdown_title(content: str) -> Optional[str]:
    """Extract the first H1 markdown header from content.

    Args:
        content: The markdown content to search.

    Returns:
        The title text if found, None otherwise.
    """
    if not content:
        return None

    match = H1_PATTERN.search(content)
    if match:
        return match.group(1).strip()
    return None


def _create_html_content(content: str) -> str:
    """Wrap content in HTML template."""
    from asky.config import TEMPLATE_PATH

    if not TEMPLATE_PATH.exists():
        logger.warning(f"Template not found at {TEMPLATE_PATH}")
        return f"<html><body><pre>{content}</pre></body></html>"

    with open(TEMPLATE_PATH, "r") as f:
        template = f.read()

    # Escape backticks for JS template literal
    safe_content = content.replace("`", "\\`").replace("${", "\\${")
    return template.replace("{{CONTENT}}", safe_content)


def render_to_browser(content: str, filename_hint: Optional[str] = None) -> None:
    """Render markdown content in a browser using a template.

    Args:
        content: The markdown content to render.
        filename_hint: Optional text to help generate a meaningful filename.
                       If not provided, attempts to extract H1 title from content.
    """
    try:
        html_content = _create_html_content(content)
        file_path = _save_to_archive(html_content, content, filename_hint)

        logger.info(f"[Opening browser: {file_path}]")
        webbrowser.open(f"file://{file_path}")
    except Exception as e:
        logger.error(f"Error rendering to browser: {e}")


def save_html_report(content: str, filename_hint: Optional[str] = None) -> str:
    """
    Save markdown content as an HTML report in the archive directory.
    Returns the absolute path to the saved file.
    """
    try:
        html_content = _create_html_content(content)
        file_path = _save_to_archive(html_content, content, filename_hint)
        return str(file_path)
    except Exception as e:
        logger.error(f"Error saving HTML report: {e}")
        return ""


def _save_to_archive(
    html_content: str,
    markdown_content: Optional[str] = None,
    filename_hint: Optional[str] = None,
) -> Path:
    """Save HTML content to the archive directory with a unique name.

    Args:
        html_content: The HTML content to save.
        markdown_content: Original markdown content for title extraction.
        filename_hint: Explicit hint for filename (overrides title extraction).
    """
    if not ARCHIVE_DIR.exists():
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Priority: 1. Explicit hint, 2. Extracted H1 title, 3. "untitled"
    slug_source = filename_hint
    if not slug_source and markdown_content:
        extracted_title = extract_markdown_title(markdown_content)
        if extracted_title:
            slug_source = extracted_title
            logger.debug(f"Extracted title for filename: {extracted_title}")

    slug = generate_slug(slug_source or "untitled", max_words=5)

    filename = f"{slug}_{timestamp}.html"
    file_path = ARCHIVE_DIR / filename

    with open(file_path, "w") as f:
        f.write(html_content)

    return file_path
