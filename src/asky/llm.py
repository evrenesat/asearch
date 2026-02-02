"""LLM integration and conversation loop."""

import json
import logging
import os
import re
import tempfile
import time
import webbrowser
import inspect
from typing import Any, Dict, List, Optional, Callable

import requests
from rich.console import Console
from rich.markdown import Markdown

from asky.config import (
    ANSWER_SUMMARY_MAX_CHARS,
    CUSTOM_TOOLS,
    DEEP_DIVE_PROMPT_TEMPLATE,
    DEEP_RESEARCH_PROMPT_TEMPLATE,
    DEFAULT_CONTEXT_SIZE,
    FORCE_SEARCH_PROMPT,
    LLM_USER_AGENT,
    MAX_TURNS,
    MODELS,
    REQUEST_TIMEOUT,
    SUMMARIZE_ANSWER_PROMPT_TEMPLATE,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_SUFFIX,
)
from asky.html import strip_think_tags
from asky import summarization
from asky.tools import (
    _execute_custom_tool,
    execute_get_date_time,
    execute_get_url_content,
    execute_get_url_details,
    execute_web_search,
)

logger = logging.getLogger(__name__)


def is_markdown(text: str) -> bool:
    """Check if the text likely contains markdown formatting."""
    # Basic detection: common markdown patterns
    patterns = [
        r"^#+\s",  # Headers
        r"\*\*.*\*\*",  # Bold
        r"__.*__",  # Bold
        r"\*.*\* ",  # Italic
        r"_.*_",  # Italic
        r"\[.*\]\(.*\)",  # Links
        r"```",  # Code blocks
        r"^\s*[-*+]\s",  # Lists
        r"^\s*\d+\.\s",  # Numbered lists
    ]
    return any(re.search(p, text, re.M) for p in patterns)


def parse_textual_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Parse tool calls from textual format (fallback for some models)."""
    if not text:
        return None
    m = re.search(r"to=functions\.([a-zA-Z0-9_]+)", text)
    if not m:
        return None
    name = m.group(1)
    j = re.search(r"(\{.*\})", text, re.S)
    if not j:
        return None
    try:
        json.loads(j.group(1))
        return {"name": name, "arguments": j.group(1)}
    except Exception:
        return None


class UsageTracker:
    """Track token usage per model alias."""

    def __init__(self):
        self.usage: Dict[str, int] = {}

    def add_usage(self, model_alias: str, tokens: int):
        self.usage[model_alias] = self.usage.get(model_alias, 0) + tokens

    def get_total_usage(self, model_alias: str) -> int:
        return self.usage.get(model_alias, 0)


def count_tokens(messages: List[Dict[str, Any]]) -> int:
    """Naive token counting: chars / 4."""
    total_chars = 0
    for m in messages:
        content = m.get("content")
        if content:
            total_chars += len(content)
        # Also count tool calls and results
        tc = m.get("tool_calls")
        if tc:
            total_chars += len(json.dumps(tc))
    return total_chars // 4


class ToolRegistry:
    """Manages tool schemas and dispatches tool calls."""

    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}  # name -> schema
        self._executors: Dict[str, Callable] = {}  # name -> executor function

    def register(
        self,
        name: str,
        schema: Dict[str, Any],
        executor: Callable[..., Dict[str, Any]],
    ) -> None:
        """Register a tool with its schema and executor."""
        self._tools[name] = schema
        self._executors[name] = executor

    def get_schemas(self) -> List[Dict[str, Any]]:
        """Return list of tool definitions for LLM payload."""
        return [{"type": "function", "function": t} for t in self._tools.values()]

    def get_tool_names(self) -> List[str]:
        """Return list of registered tool names."""
        return list(self._tools.keys())

    def dispatch(
        self,
        call: Dict[str, Any],
        summarize: bool = False,
        usage_tracker: Optional[UsageTracker] = None,
    ) -> Dict[str, Any]:
        """Dispatch a tool call to its registered executor."""
        func_call = call.get("function", {})
        name = func_call.get("name")
        args_str = func_call.get("arguments", "{}")

        try:
            args = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON arguments for tool: {name}"}

        executor = self._executors.get(name)
        if not executor:
            return {"error": f"Unknown tool: {name}"}

        # Check executor signature to see if it accepts summarize or usage_tracker
        try:
            sig = inspect.signature(executor)
            params = sig.parameters
            call_kwargs = {}
            if "summarize" in params:
                call_kwargs["summarize"] = summarize
            if "usage_tracker" in params:
                call_kwargs["usage_tracker"] = usage_tracker

            if call_kwargs:
                # Merge with tool-provided args if they don't overlap
                # Tool provided args take precedence if they arrive from the LLM
                return executor(args, **call_kwargs)
            return executor(args)
        except Exception as e:
            logger.error(f"Error executing tool '{name}': {e}")
            return {"error": f"Tool execution failed: {str(e)}"}


class ConversationEngine:
    """Orchestrates multi-turn LLM conversations with tool execution."""

    def __init__(
        self,
        model_config: Dict[str, Any],
        tool_registry: ToolRegistry,
        summarize: bool = False,
        verbose: bool = False,
        usage_tracker: Optional[UsageTracker] = None,
        open_browser: bool = False,
    ):
        self.model_config = model_config
        self.tool_registry = tool_registry
        self.summarize = summarize
        self.verbose = verbose
        self.usage_tracker = usage_tracker
        self.open_browser = open_browser
        self.start_time: float = 0
        self.final_answer: str = ""

    def run(self, messages: List[Dict[str, Any]]) -> str:
        """Run the multi-turn conversation loop."""
        turn = 0
        self.start_time = time.perf_counter()
        original_system_prompt = (
            messages[0]["content"]
            if messages and messages[0]["role"] == "system"
            else ""
        )

        try:
            while turn < MAX_TURNS:
                turn += 1
                logger.info(f"Starting turn {turn}/{MAX_TURNS}")

                # Token & Turn Tracking
                total_tokens = count_tokens(messages)
                context_size = self.model_config.get(
                    "context_size", DEFAULT_CONTEXT_SIZE
                )
                turns_left = MAX_TURNS - turn + 1

                status_msg = (
                    f"\n\n[SYSTEM UPDATE]:\n"
                    f"- Context Used: {total_tokens / context_size * 100:.2f}%"
                    f"- Turns Remaining: {turns_left} (out of {MAX_TURNS})\n"
                    f"Please manage your context usage efficiently."
                )
                if messages and messages[0]["role"] == "system":
                    messages[0]["content"] = original_system_prompt + status_msg

                msg = get_llm_msg(
                    self.model_config["id"],
                    messages,
                    use_tools=True,
                    verbose=self.verbose,
                    model_alias=self.model_config.get("alias"),
                    usage_tracker=self.usage_tracker,
                    # Pass schemas from registry
                    tool_schemas=self.tool_registry.get_schemas(),
                )

                calls = extract_calls(msg, turn)
                if not calls:
                    self.final_answer = strip_think_tags(msg.get("content", ""))
                    if is_markdown(self.final_answer):
                        console = Console()
                        console.print(Markdown(self.final_answer))
                    else:
                        logger.info(self.final_answer)

                    if self.open_browser:
                        render_to_browser(self.final_answer)
                    break

                messages.append(msg)
                for call in calls:
                    logger.debug(f"Tool call [{len(str(call))} chrs]: {str(call)}")
                    result = self.tool_registry.dispatch(
                        call, self.summarize, self.usage_tracker
                    )
                    logger.debug(
                        f"Tool result [{len(str(result))} chrs]: {str(result)}"
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(result),
                        }
                    )

            if turn >= MAX_TURNS:
                logger.info("Error: Max turns reached.")

        except Exception as e:
            logger.info(f"Error: {str(e)}")
            logger.exception("Engine failure")
        finally:
            logger.info(
                f"\nQuery completed in {time.perf_counter() - self.start_time:.2f} seconds"
            )

        return self.final_answer


def get_llm_msg(
    model_id: str,
    messages: List[Dict[str, Any]],
    use_tools: bool = True,
    verbose: bool = False,
    model_alias: Optional[str] = None,
    usage_tracker: Optional[UsageTracker] = None,
    tool_schemas: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Send messages to the LLM and get a response."""
    # Find the model config based on model_id
    model_config = next((m for m in MODELS.values() if m["id"] == model_id), None)

    url = ""
    headers = {
        "Content-Type": "application/json",
        "User-Agent": LLM_USER_AGENT,
    }

    if model_config and "base_url" in model_config:
        url = model_config["base_url"]

    api_key = None
    if model_config and "api_key" in model_config:
        api_key = model_config["api_key"]
    elif model_config and "api_key_env" in model_config:
        api_key_env_var = model_config["api_key_env"]
        api_key = os.environ.get(api_key_env_var)
        if not api_key:
            logger.info(
                f"Warning: {api_key_env_var} not found in environment variables."
            )

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model_id,
        "messages": messages,
    }
    if use_tools:
        payload["tools"] = tool_schemas
        payload["tool_choice"] = "auto"

    max_retries = 10
    backoff = 2
    max_backoff = 60

    logger.info(f"Sending request to LLM: {model_id}")
    log_payload = {
        **payload,
        "messages": [
            m["content"][:400] + "..." for m in messages if m["role"] != "system"
        ],
    }
    logger.debug(f"Payload: {str(payload)}")

    tokens_sent = count_tokens(messages)
    logger.info(f"[{model_alias or model_id}] Sent: {tokens_sent} tokens")

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
            resp_json = resp.json()

            # Extract usage if available, otherwise use naive count
            usage = resp_json.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", tokens_sent)
            completion_tokens = usage.get("completion_tokens", 0)
            response_message = resp_json["choices"][0]["message"]
            logger.debug(f"Response message: {response_message}")
            if "completion_tokens" not in usage:
                completion_tokens = len(json.dumps(response_message)) // 4

            total_call_tokens = prompt_tokens + completion_tokens

            if usage_tracker and model_alias:
                usage_tracker.add_usage(model_alias, total_call_tokens)

            return response_message
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                if attempt < max_retries - 1:
                    retry_after = e.response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            # Handle potential floating point strings (e.g. "5.0")
                            wait_time = int(float(retry_after))
                        except ValueError:
                            wait_time = backoff
                            backoff = min(backoff * 2, max_backoff)
                    else:
                        wait_time = backoff
                        backoff = min(backoff * 2, max_backoff)

                    logger.info(
                        f"Rate limit exceeded (429). Retrying in {wait_time} seconds..."
                    )
                    time.sleep(wait_time)
                    continue
            raise e
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                logger.info(f"Request error: {e}. Retrying in {backoff} seconds...")
                time.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                continue
            raise e
    raise requests.exceptions.RequestException("Max retries exceeded")


def extract_calls(msg: Dict[str, Any], turn: int) -> List[Dict[str, Any]]:
    """Extract tool calls from an LLM message."""
    tc = msg.get("tool_calls")
    if tc:
        return tc
    parsed = parse_textual_tool_call(msg.get("content", ""))
    if parsed:
        return [{"id": f"textual_call_{turn}", "function": parsed}]
    return []


def construct_system_prompt(
    deep_research_n: int, deep_dive: bool, force_search: bool
) -> str:
    """Build the system prompt based on mode flags."""
    system_content = SYSTEM_PROMPT
    if force_search:
        system_content += FORCE_SEARCH_PROMPT
    system_content += SYSTEM_PROMPT_SUFFIX

    if deep_research_n > 0:
        system_content += DEEP_RESEARCH_PROMPT_TEMPLATE.format(n=deep_research_n)
    if deep_dive:
        system_content += DEEP_DIVE_PROMPT_TEMPLATE
    return system_content


def create_default_tool_registry() -> ToolRegistry:
    """Create a ToolRegistry with all default and custom tools."""
    registry = ToolRegistry()

    registry.register(
        "web_search",
        {
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
        execute_web_search,
    )

    def url_content_executor(
        args: Dict[str, Any],
        summarize: bool = False,
        usage_tracker: Optional[UsageTracker] = None,
    ) -> Dict[str, Any]:
        result = execute_get_url_content(args)
        # LLM can override the global summarize flag in its tool call
        effective_summarize = args.get("summarize", summarize)
        if effective_summarize:
            for url, content in result.items():
                if not content.startswith("Error:"):
                    result[url] = f"Summary of {url}:\n" + _summarize_content(
                        content=content,
                        prompt_template=SUMMARIZE_ANSWER_PROMPT_TEMPLATE,
                        max_output_chars=ANSWER_SUMMARY_MAX_CHARS,
                        usage_tracker=usage_tracker,
                    )
        return result

    registry.register(
        "get_url_content",
        {
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
        url_content_executor,
    )

    registry.register(
        "get_url_details",
        {
            "name": "get_url_details",
            "description": "Fetch content and extract links from a URL. Use this in deep dive mode.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
        execute_get_url_details,
    )

    registry.register(
        "get_date_time",
        {
            "name": "get_date_time",
            "description": "Return the current date and time.",
            "parameters": {"type": "object", "properties": {}},
        },
        lambda _: execute_get_date_time(),
    )

    # Register custom tools from config
    for tool_name, tool_data in CUSTOM_TOOLS.items():
        registry.register(
            tool_name,
            {
                "name": tool_name,
                "description": tool_data.get(
                    "description", f"Custom tool: {tool_name}"
                ),
                "parameters": tool_data.get(
                    "parameters", {"type": "object", "properties": {}}
                ),
            },
            lambda args, name=tool_name: _execute_custom_tool(name, args),
        )

    return registry


def run_conversation_loop(
    model_config: Dict[str, Any],
    messages: List[Dict[str, Any]],
    summarize: bool,
    verbose: bool = False,
    usage_tracker: Optional[UsageTracker] = None,
    open_browser: bool = False,
) -> str:
    """Legacy wrapper for ConversationEngine.run()."""
    registry = create_default_tool_registry()
    engine = ConversationEngine(
        model_config=model_config,
        tool_registry=registry,
        summarize=summarize,
        verbose=verbose,
        usage_tracker=usage_tracker,
        open_browser=open_browser,
    )
    return engine.run(messages)


def render_to_browser(content: str) -> None:
    """Render markdown content in a browser using a template."""
    try:
        from asky.config import TEMPLATE_PATH

        if not TEMPLATE_PATH.exists():
            logger.info(f"Error: Template not found at {TEMPLATE_PATH}")
            return

        with open(TEMPLATE_PATH, "r") as f:
            template = f.read()

        # Escape backticks for JS template literal
        safe_content = content.replace("`", "\\`").replace("${", "\\${")

        html_content = template.replace("{{CONTENT}}", safe_content)

        with tempfile.NamedTemporaryFile(
            "w", delete=False, suffix=".html", prefix="temp_asky_"
        ) as f:
            f.write(html_content)
            temp_path = f.name

        logger.info(f"[Opening browser: {temp_path}]")
        webbrowser.open(f"file://{temp_path}")
    except Exception as e:
        logger.info(f"Error rendering to browser: {e}")


def _summarize_content(
    content: str,
    prompt_template: str,
    max_output_chars: int,
    usage_tracker: Optional[UsageTracker] = None,
) -> str:
    """Legacy wrapper for summarization._summarize_content."""
    return summarization._summarize_content(
        content,
        prompt_template,
        max_output_chars,
        get_llm_msg_func=get_llm_msg,
        usage_tracker=usage_tracker,
    )


def generate_summaries(
    query: str, answer: str, usage_tracker: Optional[UsageTracker] = None
) -> tuple[str, str]:
    """Legacy wrapper for summarization.generate_summaries."""
    return summarization.generate_summaries(
        query, answer, get_llm_msg_func=get_llm_msg, usage_tracker=usage_tracker
    )


def dispatch_tool_call(
    call: Dict[str, Any], summarize: bool, usage_tracker: Optional[UsageTracker] = None
) -> Dict[str, Any]:
    """Legacy wrapper for ToolRegistry.dispatch()."""
    registry = create_default_tool_registry()
    return registry.dispatch(call, summarize, usage_tracker)
