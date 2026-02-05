"""Research mode tool executors."""

import logging
from typing import Any, Dict, List, Optional

import requests

from asky.config import (
    USER_AGENT,
    FETCH_TIMEOUT,
    RESEARCH_MAX_LINKS_PER_URL,
    RESEARCH_MAX_RELEVANT_LINKS,
    RESEARCH_MEMORY_MAX_RESULTS,
)
from asky.html import HTMLStripper
from asky.research.cache import ResearchCache
from asky.research.chunker import chunk_text
from asky.research.embeddings import get_embedding_client
from asky.research.vector_store import get_vector_store

logger = logging.getLogger(__name__)


# Tool Schemas for LLM
RESEARCH_TOOL_SCHEMAS = [
    {
        "name": "extract_links",
        "description": """Extract and discover links from web pages for research exploration.
Returns ONLY link labels and URLs - the actual page content is cached for later retrieval.
Use this to explore what information is available before deciding what to read in depth.
Optionally provide a research query to rank links by semantic relevance (requires embedding model).

Example: extract_links(urls=["https://example.com"], query="machine learning applications")""",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URLs to extract links from",
                },
                "url": {
                    "type": "string",
                    "description": "Single URL (alternative to urls array)",
                },
                "query": {
                    "type": "string",
                    "description": "Optional: research query to rank links by relevance",
                },
                "max_links": {
                    "type": "integer",
                    "default": 30,
                    "description": "Maximum links to return per URL",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_link_summaries",
        "description": """Get AI-generated summaries of previously cached pages.
Use after extract_links to preview page contents before requesting full content.
Summaries are generated in the background - status may show 'processing' if not ready yet.
This is efficient for deciding which pages are worth reading in full.""",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URLs to get summaries for (must be previously cached via extract_links)",
                },
            },
            "required": ["urls"],
        },
    },
    {
        "name": "get_relevant_content",
        "description": """Retrieve only the most relevant content sections from cached pages using RAG.
Uses semantic search to find sections matching your specific query - much more efficient than full content.
Best for extracting specific information without loading entire pages.
Requires embedding model to be available.""",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URLs to retrieve content from (must be cached)",
                },
                "query": {
                    "type": "string",
                    "description": "What specific information are you looking for?",
                },
                "max_chunks": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum content sections to return per URL",
                },
            },
            "required": ["urls", "query"],
        },
    },
    {
        "name": "get_full_content",
        "description": """Retrieve the complete cached content from pages.
Use when you need comprehensive understanding of a page, not just specific sections.
More token-intensive than get_relevant_content - use sparingly.
Content must have been cached previously via extract_links.""",
        "parameters": {
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "URLs to get full content from (must be cached)",
                },
            },
            "required": ["urls"],
        },
    },
    {
        "name": "save_finding",
        "description": """Save a discovered fact or insight to research memory for future reference.
Use this to persist important findings that may be useful in future research sessions.
Findings are stored with embeddings for semantic retrieval.
Include source URL and tags for better organization and retrieval.""",
        "parameters": {
            "type": "object",
            "properties": {
                "finding": {
                    "type": "string",
                    "description": "The fact, insight, or piece of information to save",
                },
                "source_url": {
                    "type": "string",
                    "description": "URL where this information was found",
                },
                "source_title": {
                    "type": "string",
                    "description": "Title of the source page",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for categorization (e.g., ['climate', 'statistics', '2024'])",
                },
            },
            "required": ["finding"],
        },
    },
    {
        "name": "query_research_memory",
        "description": """Search your research memory for previously saved findings.
Uses semantic search to find relevant information from past research sessions.
Useful for recalling facts, statistics, or insights you've discovered before.""",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in research memory",
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum number of findings to return",
                },
            },
            "required": ["query"],
        },
    },
]


def _sanitize_url(url: str) -> str:
    """Remove artifacts from URLs."""
    if not url:
        return ""
    return url.replace("\\", "")


def _fetch_and_parse(url: str) -> Dict[str, Any]:
    """Fetch URL and extract content + links."""
    url = _sanitize_url(url)

    try:
        headers = {"User-Agent": USER_AGENT}
        resp = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT)
        resp.raise_for_status()

        stripper = HTMLStripper(base_url=url)
        stripper.feed(resp.text)

        content = stripper.get_data()
        links = stripper.get_links()

        # Extract title (first non-empty line, limited length)
        title = ""
        if content:
            for line in content.split("\n"):
                line = line.strip()
                if line:
                    title = line[:200]
                    break

        return {
            "content": content,
            "title": title or url,
            "links": links,
            "error": None,
        }
    except requests.exceptions.Timeout:
        return {
            "content": "",
            "title": "",
            "links": [],
            "error": f"Request timed out after {FETCH_TIMEOUT}s",
        }
    except requests.exceptions.RequestException as e:
        return {
            "content": "",
            "title": "",
            "links": [],
            "error": str(e),
        }
    except Exception as e:
        return {
            "content": "",
            "title": "",
            "links": [],
            "error": f"Unexpected error: {str(e)}",
        }


def _get_cache() -> ResearchCache:
    """Get the research cache instance."""
    return ResearchCache()


def _try_embed_links(cache_id: int, links: List[Dict[str, str]]) -> bool:
    """Try to embed links for relevance filtering. Returns True if successful."""
    try:
        vector_store = get_vector_store()
        if not vector_store.has_link_embeddings(cache_id):
            vector_store.store_link_embeddings(cache_id, links)
        return True
    except Exception as e:
        logger.warning(f"Link embedding failed (will use unranked links): {e}")
        return False


def execute_extract_links(args: Dict[str, Any]) -> Dict[str, Any]:
    """Extract links from URLs, cache content, return only links.

    If 'query' is provided, ranks links by semantic relevance.
    """
    urls = args.get("urls", [])
    if isinstance(urls, str):
        urls = [urls]

    # Also support single 'url' parameter
    single_url = args.get("url")
    if single_url:
        urls.append(single_url)

    # Deduplicate and filter
    urls = list(set([_sanitize_url(u) for u in urls if u]))
    if not urls:
        return {"error": "No URLs provided. Please specify 'urls' or 'url' parameter."}

    query = args.get("query")
    max_links = args.get("max_links", RESEARCH_MAX_LINKS_PER_URL)

    cache = _get_cache()
    results = {}

    for url in urls:
        # Check cache first
        cached = cache.get_cached(url)

        if cached:
            links = cached["links"]
            cache_id = cached["id"]
            from_cache = True
            logger.debug(f"Cache hit for {url}")
        else:
            # Fetch fresh
            logger.debug(f"Fetching {url}")
            parsed = _fetch_and_parse(url)

            if parsed["error"]:
                results[url] = {"error": parsed["error"]}
                continue

            # Cache the content (triggers background summarization)
            cache_id = cache.cache_url(
                url=url,
                content=parsed["content"],
                title=parsed["title"],
                links=parsed["links"],
                trigger_summarization=True,
            )

            links = parsed["links"]
            from_cache = False

        # Try to embed links for relevance filtering
        _try_embed_links(cache_id, links)

        # Apply relevance filtering if query provided
        if query and links:
            try:
                vector_store = get_vector_store()
                ranked = vector_store.rank_links_by_relevance(
                    cache_id, query, top_k=min(max_links, RESEARCH_MAX_RELEVANT_LINKS)
                )
                if ranked:
                    links = [
                        {
                            "text": link["text"],
                            "href": link["href"],
                            "relevance": round(score, 3),
                        }
                        for link, score in ranked
                    ]
                else:
                    # Fallback to unranked if ranking failed
                    links = links[:max_links]
            except Exception as e:
                logger.warning(f"Relevance ranking failed, using unranked: {e}")
                links = links[:max_links]
        else:
            links = links[:max_links]

        results[url] = {
            "links": links,
            "cached": from_cache,
            "link_count": len(links),
            "note": "Content cached. Use get_link_summaries or get_relevant_content to read.",
        }

    return results


def execute_get_link_summaries(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get summaries for cached URLs."""
    urls = args.get("urls", [])
    if isinstance(urls, str):
        urls = [urls]

    urls = list(set([_sanitize_url(u) for u in urls if u]))
    if not urls:
        return {"error": "No URLs provided."}

    cache = _get_cache()
    results = {}

    for url in urls:
        summary_info = cache.get_summary(url)

        if not summary_info:
            results[url] = {
                "error": "Not cached. Use extract_links first to cache this URL."
            }
            continue

        status = summary_info.get("summary_status", "unknown")
        summary = summary_info.get("summary")

        if status == "completed" and summary:
            results[url] = {
                "title": summary_info.get("title", ""),
                "summary": summary,
            }
        elif status == "processing":
            results[url] = {
                "title": summary_info.get("title", ""),
                "summary": "(Summary is being generated... try again in a moment)",
                "status": "processing",
            }
        elif status == "failed":
            results[url] = {
                "title": summary_info.get("title", ""),
                "summary": "(Summary generation failed)",
                "status": "failed",
            }
        else:
            results[url] = {
                "title": summary_info.get("title", ""),
                "summary": "(Summary pending)",
                "status": status,
            }

    return results


def execute_get_relevant_content(args: Dict[str, Any]) -> Dict[str, Any]:
    """Retrieve relevant content chunks from cached URLs using RAG."""
    urls = args.get("urls", [])
    if isinstance(urls, str):
        urls = [urls]

    urls = list(set([_sanitize_url(u) for u in urls if u]))
    query = args.get("query", "")
    max_chunks = args.get("max_chunks", 5)

    if not urls:
        return {"error": "No URLs provided."}
    if not query:
        return {"error": "Query is required for relevant content retrieval."}

    cache = _get_cache()
    results = {}

    for url in urls:
        cached = cache.get_cached(url)

        if not cached:
            results[url] = {
                "error": "Not cached. Use extract_links first to cache this URL."
            }
            continue

        cache_id = cached["id"]
        content = cached["content"]

        if not content:
            results[url] = {"error": "Cached content is empty."}
            continue

        try:
            vector_store = get_vector_store()

            # Ensure chunks are embedded
            if not vector_store.has_chunk_embeddings(cache_id):
                logger.debug(f"Generating chunk embeddings for {url}")
                chunks = chunk_text(content)
                stored = vector_store.store_chunk_embeddings(cache_id, chunks)
                if stored == 0:
                    raise Exception("Failed to store chunk embeddings")

            # Search for relevant chunks
            relevant = vector_store.search_chunks(cache_id, query, top_k=max_chunks)

            if relevant:
                results[url] = {
                    "title": cached.get("title", ""),
                    "chunks": [
                        {"text": text, "relevance": round(score, 3)}
                        for text, score in relevant
                    ],
                    "chunk_count": len(relevant),
                }
            else:
                # No relevant chunks found - return truncated content as fallback
                results[url] = {
                    "title": cached.get("title", ""),
                    "note": "No highly relevant sections found. Returning content preview.",
                    "content_preview": content[:2000]
                    + ("..." if len(content) > 2000 else ""),
                }

        except Exception as e:
            logger.error(f"RAG retrieval failed for {url}: {e}")
            # Fallback: return truncated full content
            results[url] = {
                "title": cached.get("title", ""),
                "fallback": True,
                "note": f"Semantic search unavailable ({str(e)[:50]}). Returning content preview.",
                "content_preview": content[:3000]
                + ("..." if len(content) > 3000 else ""),
            }

    return results


def execute_get_full_content(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get full cached content for URLs."""
    urls = args.get("urls", [])
    if isinstance(urls, str):
        urls = [urls]

    urls = list(set([_sanitize_url(u) for u in urls if u]))
    if not urls:
        return {"error": "No URLs provided."}

    cache = _get_cache()
    results = {}

    for url in urls:
        cached = cache.get_cached(url)

        if not cached:
            results[url] = {
                "error": "Not cached. Use extract_links first to cache this URL."
            }
            continue

        content = cached.get("content", "")
        if not content:
            results[url] = {"error": "Cached content is empty."}
            continue

        results[url] = {
            "title": cached.get("title", ""),
            "content": content,
            "content_length": len(content),
        }

    return results


def execute_save_finding(args: Dict[str, Any]) -> Dict[str, Any]:
    """Save a research finding to persistent memory."""
    finding = args.get("finding", "").strip()
    if not finding:
        return {"error": "Finding text is required."}

    source_url = args.get("source_url")
    source_title = args.get("source_title")
    tags = args.get("tags", [])

    # Ensure tags is a list
    if isinstance(tags, str):
        tags = [tags]

    cache = _get_cache()
    finding_id = cache.save_finding(
        finding_text=finding,
        source_url=source_url,
        source_title=source_title,
        tags=tags,
    )

    # Try to embed for semantic search
    embedded = False
    try:
        vector_store = get_vector_store()
        embedded = vector_store.store_finding_embedding(finding_id, finding)
    except Exception as e:
        logger.warning(f"Finding embedding failed (will still be saved): {e}")

    return {
        "status": "saved",
        "finding_id": finding_id,
        "embedded": embedded,
        "note": "Finding saved to research memory"
        + (" with embedding" if embedded else " (without embedding - API unavailable)"),
    }


def execute_query_research_memory(args: Dict[str, Any]) -> Dict[str, Any]:
    """Search research memory for previously saved findings."""
    query = args.get("query", "").strip()
    if not query:
        return {"error": "Query is required."}

    limit = args.get("limit", RESEARCH_MEMORY_MAX_RESULTS)

    # Try semantic search first
    try:
        vector_store = get_vector_store()
        results = vector_store.search_findings(query, top_k=limit)

        if results:
            return {
                "findings": [
                    {
                        "finding": finding["finding_text"],
                        "source_url": finding.get("source_url"),
                        "source_title": finding.get("source_title"),
                        "tags": finding.get("tags", []),
                        "relevance": round(score, 3),
                        "saved_at": finding.get("created_at"),
                    }
                    for finding, score in results
                ],
                "count": len(results),
                "search_type": "semantic",
            }
        else:
            # No results from semantic search, try returning recent findings
            cache = _get_cache()
            findings = cache.get_all_findings(limit=limit)

            if findings:
                return {
                    "findings": [
                        {
                            "finding": f["finding_text"],
                            "source_url": f.get("source_url"),
                            "source_title": f.get("source_title"),
                            "tags": f.get("tags", []),
                            "saved_at": f.get("created_at"),
                        }
                        for f in findings
                    ],
                    "count": len(findings),
                    "note": "No semantically relevant findings. Showing recent findings.",
                    "search_type": "recent",
                }
            else:
                return {
                    "findings": [],
                    "note": "No findings in research memory yet. Use save_finding to store discoveries.",
                }

    except Exception as e:
        logger.warning(f"Semantic search unavailable: {e}")
        # Fallback to returning recent findings
        cache = _get_cache()
        findings = cache.get_all_findings(limit=limit)

        return {
            "findings": [
                {
                    "finding": f["finding_text"],
                    "source_url": f.get("source_url"),
                    "source_title": f.get("source_title"),
                    "tags": f.get("tags", []),
                    "saved_at": f.get("created_at"),
                }
                for f in findings
            ],
            "count": len(findings),
            "note": f"Semantic search unavailable ({str(e)[:30]}). Showing recent findings.",
            "search_type": "fallback",
        }
