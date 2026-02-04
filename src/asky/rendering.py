"""Browser rendering utilities for asky."""

import logging
import tempfile
import webbrowser
from pathlib import Path

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


def render_to_browser(content: str) -> None:
    """Render markdown content in a browser using a template."""
    try:
        html_content = _create_html_content(content)

        with tempfile.NamedTemporaryFile(
            "w", delete=False, suffix=".html", prefix="temp_asky_"
        ) as f:
            f.write(html_content)
            temp_path = f.name

        logger.info(f"[Opening browser: {temp_path}]")
        webbrowser.open(f"file://{temp_path}")
    except Exception as e:
        logger.error(f"Error rendering to browser: {e}")


def save_html_report(content: str, filename: str = "asky_latest_output.html") -> str:
    """
    Save markdown content as an HTML report in the temporary directory.
    Returns the absolute path to the saved file.
    """
    import os

    try:
        html_content = _create_html_content(content)
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, filename)

        with open(file_path, "w") as f:
            f.write(html_content)

        return file_path
    except Exception as e:
        logger.error(f"Error saving HTML report: {e}")
        return ""
