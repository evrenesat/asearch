"""Configuration constants and static declarations for asearch."""

import os
import tomllib
from pathlib import Path
import copy
from typing import Dict, Any


# Default Configuration Values
# Default Configuration Values
DEFAULT_CONFIG = {
    "general": {
        "db_path_env_var": "SEARXNG_HISTORY_DB_PATH",
        "query_summary_max_chars": 40,
        "answer_summary_max_chars": 200,
        "searxng_url": "http://localhost:8888",
        "max_turns": 20,
        "default_model": "gf",
        "summarization_model": "lfm",
    },
    "api": {
        "gemini": {
            "url": "https://generativelanguage.googleapis.com/v1beta/chat/completions",
            "api_key_env": "GOOGLE_API_KEY",
        },
        "lmstudio": {
            "url": "http://localhost:1234/v1/chat/completions",
            "api_key": "lm-studio",
        },
    },
    "models": {
        "q34t": {
            "id": "qwen/qwen3-4b-thinking-2507",
            "api": "lmstudio",
            "max_chars": 4000,
            "context_size": 32000,
        },
        "q34": {
            "id": "qwen/qwen3-4b-2507",
            "api": "lmstudio",
            "max_chars": 4000,
            "context_size": 32000,
        },
        "lfm": {
            "id": "liquid/lfm2.5-1.2b",
            "api": "lmstudio",
            "max_chars": 100000,
            "context_size": 32000,
        },
        "q8": {
            "id": "qwen/qwen3-8b",
            "api": "lmstudio",
            "max_chars": 4000,
            "context_size": 32000,
        },
        "q30": {
            "id": "qwen/qwen3-30b-a3b-2507",
            "api": "lmstudio",
            "max_chars": 3000,
            "context_size": 32000,
        },
        "gf": {
            "id": "gemini-flash-latest",
            "api": "gemini",
            "max_chars": 1000000,
            "context_size": 1000000,
        },
    },
    "prompts": {
        "system_prefix": (
            "You are a helpful assistant with web searc and URL retrieval capabilities. "
            "Use get_date_time for current date/time if needed (e.g., for 'today' or 'recently'). "
        ),
        "force_search": (
            "Unless you are asked to use a specific URL, always use web_search, never try to answer without using web_search. "
        ),
        "system_suffix": (
            "Then use get_url_content for details of the search results. "
            "You can pass a list of URLs to get_url_content to fetch multiple pages efficiently at once. "
            "Use tools, don't say you can't."
            "You have {MAX_TURNS} turns to complete your task, if you reach the limit, process will be terminated."
            "You should finish your task before reaching %100 of your token limit."
        ),
        "deep_research": (
            "\nYou are in DEEP RESEARCH mode. You MUST perform at least {n} "
            "distinct web searches, or make {n} get_url_content calls to gather comprehensive information before providing a final answer."
            "If you need to get links from a URL, use get_url_details. If you just need to get content from a URL, use get_url_content."
        ),
        "deep_dive": (
            "\nYou are in DEEP DIVE mode. Follow these instructions:\n"
            "1. Use 'get_url_details' for the INITIAL page to retrieve content and links.\n"
            "2. Follow up to 25 relevant links within the same domain to gather comprehensive information.\n"
            "3. IMPORTANT: Use 'get_url_details' ONLY for the first page. Use 'get_url_content' for all subsequent links.\n"
            "4. Do not rely on your internal knowledge; base your answer strictly on the retrieved content."
            "5. Do not use web_search in deep dive mode."
        ),
    },
}


def _get_config_dir() -> Path:
    """Return the configuration directory path."""
    return Path.home() / ".config" / "asearch"


def _create_default_config(path: Path):
    """Create the default configuration file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    # We construct the TOML manually to avoid adding a write dependency
    toml_content = [
        "# asearch Configuration File",
        "",
        "[general]",
    ]

    gen = DEFAULT_CONFIG["general"]
    for k, v in gen.items():
        if isinstance(v, str):
            toml_content.append(f'{k} = "{v}"')
        elif isinstance(v, int):
            toml_content.append(f"{k} = {v}")

    toml_content.append("")
    for api_name, api_data in DEFAULT_CONFIG.get("api", {}).items():
        toml_content.append(f"[api.{api_name}]")
        for k, v in api_data.items():
            if isinstance(v, str):
                toml_content.append(f'{k} = "{v}"')
            elif isinstance(v, int):
                toml_content.append(f"{k} = {v}")
        toml_content.append("")

    toml_content.append("[prompts]")
    prompts = DEFAULT_CONFIG["prompts"]
    for k, v in prompts.items():
        # Multiline strings for prompts
        clean_v = v.replace('"', '\\"')
        toml_content.append(f'{k} = """{clean_v}"""')

    toml_content.append("")
    toml_content.append("# Model Definitions")
    for model_key, model_data in DEFAULT_CONFIG["models"].items():
        toml_content.append(f"\n[models.{model_key}]")
        for k, v in model_data.items():
            if isinstance(v, str):
                toml_content.append(f'{k} = "{v}"')
            elif isinstance(v, int):
                toml_content.append(f"{k} = {v}")

    with open(path, "w") as f:
        f.write("\n".join(toml_content))


def _hydrate_models(config: Dict[str, Any]) -> Dict[str, Any]:
    """Hydrate model definitions with API details."""
    api_defs = config.get("api", {})
    models = config.get("models", {})

    for model_data in models.values():
        api_ref = model_data.get("api")
        if api_ref and api_ref in api_defs:
            api_config = api_defs[api_ref]
            # Copy relevant fields if not present in model
            # Map 'url' from api to 'base_url' for the model if needed, or just keep it as url
            # The LLM module likely looks for 'base_url'.
            # Let's standardize on 'base_url' for the internal model config representation.

            if "url" in api_config and "base_url" not in model_data:
                model_data["base_url"] = api_config["url"]
            elif (
                "url" in api_config
            ):  # If model has base_url, do nothing? or overwrite?
                # if both exist, model config should probably win, but here we are filling in defaults.
                pass

            if "api_key" in api_config and "api_key" not in model_data:
                model_data["api_key"] = api_config["api_key"]

            if "api_key_env" in api_config and "api_key_env" not in model_data:
                model_data["api_key_env"] = api_config["api_key_env"]

    return config


def load_config() -> Dict[str, Any]:
    """Load configuration from TOML file, falling back to defaults."""
    config_path = _get_config_dir() / "config.toml"

    if not config_path.exists():
        try:
            _create_default_config(config_path)
        except Exception:
            pass

    if config_path.exists():
        try:
            with open(config_path, "rb") as f:
                user_config = tomllib.load(f)

            # Recursive merge with default config

            def merge(base, update):
                for k, v in update.items():
                    if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                        merge(base[k], v)
                    else:
                        base[k] = v

            final_config = copy.deepcopy(DEFAULT_CONFIG)
            merge(final_config, user_config)

            # Post-process to hydrate models
            return _hydrate_models(final_config)

        except Exception as e:
            print(f"Warning: Failed to load config from {config_path}: {e}")
            return _hydrate_models(copy.deepcopy(DEFAULT_CONFIG))

    return _hydrate_models(copy.deepcopy(DEFAULT_CONFIG))


# --- Initialize Configuration ---
_CONFIG = load_config()

# --- Expose Constants ---

# General
_gen = _CONFIG["general"]
QUERY_SUMMARY_MAX_CHARS = _gen["query_summary_max_chars"]
ANSWER_SUMMARY_MAX_CHARS = _gen["answer_summary_max_chars"]
ANSWER_SUMMARY_MAX_CHARS = _gen["answer_summary_max_chars"]
SEARXNG_URL = _gen["searxng_url"]
MAX_TURNS = _gen["max_turns"]
DEFAULT_MODEL = _gen["default_model"]
SUMMARIZATION_MODEL = _gen["summarization_model"]

# Database
# DB Path logic:
# 1. Env Var (name defined in config, e.g. SEARXNG_HISTORY_DB_PATH)
# 2. Configured 'db_path' in [general]
# 3. Default: ~/.config/asearch/history.db

_db_env_var_name = _gen.get("db_path_env_var", "SEARXNG_HISTORY_DB_PATH")
_env_path = os.environ.get(_db_env_var_name)

if _env_path:
    DB_PATH = Path(_env_path)
elif "db_path" in _gen and _gen["db_path"]:
    DB_PATH = Path(_gen["db_path"]).expanduser()
else:
    DB_PATH = _get_config_dir() / "history.db"

# Models
MODELS = _CONFIG["models"]

# Prompts
_prompts = _CONFIG["prompts"]
SYSTEM_PROMPT = _prompts["system_prefix"]
FORCE_SEARCH_PROMPT = _prompts["force_search"]
SYSTEM_PROMPT_SUFFIX = _prompts["system_suffix"]
DEEP_RESEARCH_PROMPT_TEMPLATE = _prompts["deep_research"]
DEEP_DIVE_PROMPT_TEMPLATE = _prompts["deep_dive"]


# --- Tool Definitions ---
# Tools are code-coupled schemas, keeping them here as constants.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web and return top results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "count": {"type": "integer", "default": 5},
                },
                "required": ["q"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_url_content",
            "description": "Fetch the content of one or more URLs and return their text content (HTML stripped).",
            "parameters": {
                "type": "object",
                "properties": {
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of URLs to fetch content from.",
                    },
                    "url": {
                        "type": "string",
                        "description": "Single URL (deprecated, use 'urls' instead).",
                    },
                    "summarize": {
                        "type": "boolean",
                        "description": "If true, summarize the content of the page using an LLM.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_url_details",
            "description": "Fetch content and extract links from a URL. Use this in deep dive mode.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_date_time",
            "description": "Return the current date and time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]
