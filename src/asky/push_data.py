"""HTTP data push functionality for asky."""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from asky.config import MODELS

logger = logging.getLogger(__name__)

# Special variable names that can be auto-filled
SPECIAL_VARIABLES = {"query", "answer", "timestamp", "model"}


def _resolve_field_value(
    key: str,
    value: Any,
    dynamic_args: Dict[str, str],
    special_vars: Dict[str, str],
) -> str:
    """
    Resolve a field value based on its type:
    - Static: literal string value
    - Environment: key ends with "_env", read from environment
    - Dynamic: "${param}" placeholder, get from dynamic_args
    - Special: "${query}", "${answer}", etc., get from special_vars

    Args:
        key: Field name
        value: Field value from config
        dynamic_args: Dynamic parameters from LLM/CLI
        special_vars: Special variables (query, answer, timestamp, model)

    Returns:
        Resolved string value

    Raises:
        ValueError: If dynamic parameter is missing or environment variable not found
    """
    # Environment variable (key ends with _env)
    if key.endswith("_env"):
        env_var_name = str(value)
        env_value = os.environ.get(env_var_name)
        if env_value is None:
            raise ValueError(f"Environment variable '{env_var_name}' not found")
        return env_value

    # Dynamic or special variable placeholder
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        param_name = value[2:-1]  # Extract name from ${...}

        # Check if it's a special variable
        if param_name in SPECIAL_VARIABLES:
            if param_name not in special_vars:
                raise ValueError(f"Special variable '{param_name}' not available")
            return special_vars[param_name]

        # Otherwise it's a dynamic parameter
        if param_name not in dynamic_args:
            raise ValueError(f"Missing required parameter: {param_name}")
        return dynamic_args[param_name]

    # Static value
    return str(value)


def _resolve_headers(
    headers_config: Dict[str, Any],
) -> Dict[str, str]:
    """
    Resolve headers, handling _env suffix for environment variables.

    Args:
        headers_config: Headers configuration from config.toml

    Returns:
        Resolved headers dictionary

    Raises:
        ValueError: If environment variable not found
    """
    resolved = {}
    for key, value in headers_config.items():
        if key.endswith("_env"):
            # Remove _env suffix for actual header name
            header_name = key[:-4]
            env_var_name = str(value)
            env_value = os.environ.get(env_var_name)
            if env_value is None:
                raise ValueError(f"Environment variable '{env_var_name}' not found")
            resolved[header_name] = env_value
        else:
            resolved[key] = str(value)
    return resolved


def _build_payload(
    fields_config: Dict[str, Any],
    dynamic_args: Dict[str, str],
    special_vars: Dict[str, str],
) -> Dict[str, str]:
    """
    Build request payload from field configuration.

    Args:
        fields_config: Fields configuration from config.toml
        dynamic_args: Dynamic parameters from LLM/CLI
        special_vars: Special variables (query, answer, timestamp, model)

    Returns:
        Resolved payload dictionary

    Raises:
        ValueError: If required parameter is missing
    """
    payload = {}
    for key, value in fields_config.items():
        resolved_value = _resolve_field_value(key, value, dynamic_args, special_vars)
        payload[key] = resolved_value
    return payload


def execute_push_data(
    endpoint_name: str,
    dynamic_args: Optional[Dict[str, str]] = None,
    query: Optional[str] = None,
    answer: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute a push_data request to a configured endpoint.

    Args:
        endpoint_name: Name of the endpoint from config.toml
        dynamic_args: Dynamic parameters provided by LLM or CLI
        query: Query text (special variable)
        answer: Answer text (special variable)
        model: Model alias (special variable)

    Returns:
        Result dictionary with status and details

    Raises:
        ValueError: If endpoint not found or configuration invalid
    """
    from asky.config import _CONFIG

    dynamic_args = dynamic_args or {}

    # Get endpoint configuration
    push_data_config = _CONFIG.get("push_data", {})
    if endpoint_name not in push_data_config:
        raise ValueError(f"Push data endpoint '{endpoint_name}' not found in configuration")

    endpoint_config = push_data_config[endpoint_name]

    # Extract configuration
    url = endpoint_config.get("url")
    if not url:
        raise ValueError(f"Endpoint '{endpoint_name}' missing 'url' field")

    method = endpoint_config.get("method", "post").lower()
    if method not in ("get", "post"):
        raise ValueError(f"Endpoint '{endpoint_name}' has invalid method: {method}")

    # Build special variables
    special_vars = {}
    if query is not None:
        special_vars["query"] = query
    if answer is not None:
        special_vars["answer"] = answer
    if model is not None:
        special_vars["model"] = model
    special_vars["timestamp"] = datetime.now(timezone.utc).isoformat()

    # Resolve headers
    headers_config = endpoint_config.get("headers", {})
    try:
        headers = _resolve_headers(headers_config)
    except ValueError as e:
        logger.error(f"Failed to resolve headers for endpoint '{endpoint_name}': {e}")
        return {
            "success": False,
            "error": str(e),
            "endpoint": endpoint_name,
        }

    # Build payload
    fields_config = endpoint_config.get("fields", {})
    try:
        payload = _build_payload(fields_config, dynamic_args, special_vars)
    except ValueError as e:
        logger.error(f"Failed to build payload for endpoint '{endpoint_name}': {e}")
        return {
            "success": False,
            "error": str(e),
            "endpoint": endpoint_name,
        }

    # Execute request
    try:
        if method == "get":
            response = requests.get(url, params=payload, headers=headers, timeout=30)
        else:  # post
            response = requests.post(url, json=payload, headers=headers, timeout=30)

        response.raise_for_status()

        logger.info(f"Successfully pushed data to '{endpoint_name}': {response.status_code}")

        return {
            "success": True,
            "endpoint": endpoint_name,
            "status_code": response.status_code,
            "url": url,
        }

    except requests.RequestException as e:
        logger.error(f"Failed to push data to '{endpoint_name}': {e}")
        return {
            "success": False,
            "error": str(e),
            "endpoint": endpoint_name,
            "url": url,
        }


def get_enabled_endpoints() -> Dict[str, Dict[str, Any]]:
    """
    Get all push_data endpoints that are enabled for LLM tool registration.

    Returns:
        Dictionary of enabled endpoint names to their configurations
    """
    from asky.config import _CONFIG

    push_data_config = _CONFIG.get("push_data", {})
    enabled = {}

    for name, config in push_data_config.items():
        if config.get("enabled", False):
            enabled[name] = config

    return enabled
