"""Prompt-related CLI commands for asky."""

from rich.console import Console
from rich.table import Table

from asky.config import USER_PROMPTS

# Maximum characters to display for prompt expansion in the table
PROMPT_EXPANSION_MAX_DISPLAY_CHARS = 50


def list_prompts_command(filter_prefix: str | None = None) -> None:
    """List all configured user prompts.

    Args:
        filter_prefix: Optional prefix to filter prompts by (case-insensitive).
                       If provided but no matches found, shows message then all prompts.
    """
    if not USER_PROMPTS:
        print("\nNo user prompts configured.")
        return

    console = Console()

    # Filter prompts if prefix provided
    if filter_prefix:
        filtered = {
            k: v
            for k, v in USER_PROMPTS.items()
            if k.lower().startswith(filter_prefix.lower())
        }
        if not filtered:
            console.print(f"\n[yellow]No matches for '/{filter_prefix}'[/yellow]")
            filtered = USER_PROMPTS  # Show all prompts as fallback
    else:
        filtered = USER_PROMPTS

    # Build the table
    table = Table(title="User Prompts")
    table.add_column("Shortcut", style="cyan")
    table.add_column("Expansion", style="white")

    for alias, prompt in filtered.items():
        # Clip expansion to max chars
        if len(prompt) > PROMPT_EXPANSION_MAX_DISPLAY_CHARS:
            display_prompt = prompt[:PROMPT_EXPANSION_MAX_DISPLAY_CHARS] + "..."
        else:
            display_prompt = prompt
        table.add_row(f"/{alias}", display_prompt)

    console.print()
    console.print(table)
