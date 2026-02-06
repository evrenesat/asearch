"""Adapter helpers for routing research targets to custom user tools."""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from asky.config import RESEARCH_SOURCE_ADAPTERS
from asky.tools import _execute_custom_tool

logger = logging.getLogger(__name__)

DEFAULT_ADAPTER_MAX_LINKS = 50

LINK_HREF_FIELDS = ("href", "url", "target", "id", "path")
LINK_TEXT_FIELDS = ("text", "title", "name", "label")


@dataclass(frozen=True)
class ResearchSourceAdapter:
    """Configuration for a research source adapter."""

    name: str
    prefix: str
    discover_tool: str
    read_tool: str


def _get_enabled_adapters() -> List[ResearchSourceAdapter]:
    """Build enabled adapter definitions from configuration."""
    adapters: List[ResearchSourceAdapter] = []

    for name, cfg in RESEARCH_SOURCE_ADAPTERS.items():
        if not isinstance(cfg, dict):
            continue
        if not cfg.get("enabled", True):
            continue

        default_tool = str(cfg.get("tool", "")).strip()
        discover_tool = str(
            cfg.get("discover_tool") or cfg.get("list_tool") or default_tool
        ).strip()
        read_tool = str(cfg.get("read_tool") or default_tool).strip()

        if not discover_tool and not read_tool:
            logger.warning(
                f"Research source adapter '{name}' has no tool configured."
            )
            continue
        if not discover_tool:
            discover_tool = read_tool
        if not read_tool:
            read_tool = discover_tool

        prefix = str(cfg.get("prefix", f"{name}://")).strip()
        if not prefix:
            logger.warning(f"Research source adapter '{name}' has an empty prefix.")
            continue

        adapters.append(
            ResearchSourceAdapter(
                name=name,
                prefix=prefix,
                discover_tool=discover_tool,
                read_tool=read_tool,
            )
        )

    adapters.sort(key=lambda adapter: len(adapter.prefix), reverse=True)
    return adapters


def get_source_adapter(target: str) -> Optional[ResearchSourceAdapter]:
    """Resolve adapter for a target identifier."""
    if not target:
        return None

    for adapter in _get_enabled_adapters():
        if target.startswith(adapter.prefix):
            return adapter
    return None


def has_source_adapter(target: str) -> bool:
    """Check whether a target is handled by a configured source adapter."""
    return get_source_adapter(target) is not None


def _coerce_text(value: Any, fallback: str = "") -> str:
    """Coerce any adapter payload value to text."""
    if value is None:
        return fallback
    return str(value)


def _normalize_link(item: Any) -> Optional[Dict[str, str]]:
    """Normalize a single link-like item to {text, href} format."""
    if isinstance(item, str):
        text = item.strip()
        if not text:
            return None
        return {"text": text, "href": text}

    if not isinstance(item, dict):
        return None

    href = ""
    for field in LINK_HREF_FIELDS:
        if item.get(field):
            href = _coerce_text(item.get(field)).strip()
            if href:
                break

    if not href:
        return None

    text = ""
    for field in LINK_TEXT_FIELDS:
        if item.get(field):
            text = _coerce_text(item.get(field)).strip()
            if text:
                break

    if not text:
        text = href

    return {"text": text, "href": href}


def _normalize_links(raw_links: Any, max_links: int) -> List[Dict[str, str]]:
    """Normalize links from adapter payload."""
    if not isinstance(raw_links, list):
        return []

    links: List[Dict[str, str]] = []
    for item in raw_links:
        normalized = _normalize_link(item)
        if normalized:
            links.append(normalized)
        if len(links) >= max_links:
            break
    return links


def _parse_adapter_stdout(stdout: str) -> Dict[str, Any]:
    """Parse adapter stdout as JSON object."""
    if not stdout.strip():
        return {"error": "Adapter tool returned empty stdout."}

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return {"error": f"Adapter tool returned invalid JSON: {exc}"}

    if not isinstance(data, dict):
        return {"error": "Adapter tool JSON output must be an object."}

    return data


def _normalize_adapter_payload(
    payload: Dict[str, Any],
    target: str,
    max_links: int,
) -> Dict[str, Any]:
    """Normalize adapter payload into research fetch contract."""
    if payload.get("error"):
        return {
            "content": "",
            "title": target,
            "links": [],
            "error": _coerce_text(payload.get("error")),
        }

    title = _coerce_text(payload.get("title") or payload.get("name"), fallback=target)
    content = _coerce_text(payload.get("content"), fallback="")
    raw_links = payload.get("links", payload.get("items", []))
    links = _normalize_links(raw_links, max_links=max_links)

    return {
        "content": content,
        "title": title,
        "links": links,
        "error": None,
    }


def fetch_source_via_adapter(
    target: str,
    query: Optional[str] = None,
    max_links: Optional[int] = None,
    operation: str = "discover",
) -> Optional[Dict[str, Any]]:
    """Fetch source metadata/content via matching custom tool adapter.

    Returns None when no adapter matches the target.
    """
    adapter = get_source_adapter(target)
    if not adapter:
        return None

    link_limit = (
        max_links
        if isinstance(max_links, int) and max_links > 0
        else DEFAULT_ADAPTER_MAX_LINKS
    )
    tool_name = adapter.read_tool if operation == "read" else adapter.discover_tool

    tool_args: Dict[str, Any] = {
        "target": target,
        "max_links": link_limit,
        "operation": operation,
    }
    if query:
        tool_args["query"] = query

    result = _execute_custom_tool(tool_name, tool_args)
    if result.get("error"):
        return {
            "content": "",
            "title": target,
            "links": [],
            "error": _coerce_text(result.get("error")),
        }

    payload = _parse_adapter_stdout(_coerce_text(result.get("stdout"), fallback=""))
    return _normalize_adapter_payload(payload, target=target, max_links=link_limit)
