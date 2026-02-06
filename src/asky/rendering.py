"""Browser rendering utilities for asky."""

import logging
import tempfile
import webbrowser
from datetime import datetime
from pathlib import Path

from asky.config import ARCHIVE_DIR
from asky.core.utils import generate_slug

logger = logging.getLogger(__name__)


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


def render_to_browser(content: str, filename_hint: str = None) -> None:
    """Render markdown content in a browser using a template.

    Args:
        content: The markdown content to render.
        filename_hint: Optional text to help generate a meaningful filename.
    """
    try:
        html_content = _create_html_content(content)
        file_path = _save_to_archive(html_content, filename_hint)

        logger.info(f"[Opening browser: {file_path}]")
        webbrowser.open(f"file://{file_path}")
    except Exception as e:
        logger.error(f"Error rendering to browser: {e}")


def save_html_report(content: str, filename_hint: str = None) -> str:
    """
    Save markdown content as an HTML report in the archive directory.
    Returns the absolute path to the saved file.
    """
    try:
        html_content = _create_html_content(content)
        file_path = _save_to_archive(html_content, filename_hint)
        return str(file_path)
    except Exception as e:
        logger.error(f"Error saving HTML report: {e}")
        return ""


def _save_to_archive(html_content: str, filename_hint: str = None) -> Path:
    """Save HTML content to the archive directory with a unique name."""

    if not ARCHIVE_DIR.exists():
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Use explicit hint if provided, otherwise try to extract title/slug from content?
    # Actually, for content-based slug, we might need the original markdown,
    # but here we have the HTML.
    # Ideally, filename_hint should be passed. If not, 'untitled'.
    slug = (
        generate_slug(filename_hint or "untitled", max_words=5)
        if filename_hint
        else "untitled"
    )

    filename = f"{slug}_{timestamp}.html"
    file_path = ARCHIVE_DIR / filename

    with open(file_path, "w") as f:
        f.write(html_content)

    return file_path
