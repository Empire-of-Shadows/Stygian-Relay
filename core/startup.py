"""
Startup orchestration helpers (shared sibling-pattern across EoS bots).

Provides the unified startup-phase logging used by every Empire of Shadows bot so
their boot logs read identically:
    - `startup_phase(name)`  → "🔄 Starting phase: …" / "✅ Completed phase: … in …s"
    - `log_startup_summary()` → "📈 Startup Performance Summary:" + table
    - `log_all_commands(bot)` → "📝 Registered Prefix Commands …" / "⚡ Registered Slash Commands …"

This module is intentionally dependency-light (stdlib `logging` + `tabulate`) so the
exact same file can be dropped into each bot regardless of its logger API.
"""

import logging
import time
from collections import OrderedDict
from contextlib import asynccontextmanager

from tabulate import tabulate

__all__ = [
    "startup_metrics",
    "startup_phase",
    "log_startup_summary",
    "log_all_commands",
]

logger = logging.getLogger(__name__)

# Ordered record of each timed startup phase: phase name -> duration (seconds).
# Populated by `startup_phase`; rendered by `log_startup_summary`.
startup_metrics: "OrderedDict[str, float]" = OrderedDict()


@asynccontextmanager
async def startup_phase(phase_name: str):
    """Time a startup phase and record it into `startup_metrics`."""
    start_time = time.perf_counter()
    logger.info(f"🔄 Starting phase: {phase_name}")
    try:
        yield
        duration = time.perf_counter() - start_time
        startup_metrics[phase_name] = duration
        logger.info(f"✅ Completed phase: {phase_name} in {duration:.4f}s")
    except Exception as e:
        duration = time.perf_counter() - start_time
        startup_metrics[phase_name] = duration
        logger.error(f"❌ Failed phase: {phase_name} after {duration:.4f}s - {e}")
        raise


def log_startup_summary() -> None:
    """Print a tabulated summary of every startup phase that ran."""
    total_time = sum(startup_metrics.values())

    rows = []
    for name, duration in startup_metrics.items():
        pct = f"{(duration / total_time * 100):.1f}%" if total_time > 0 else "0%"
        rows.append([name, f"{duration:.4f}", pct])
    rows.append(["TOTAL", f"{total_time:.4f}", "100%"])

    table = tabulate(rows, headers=["Phase", "Duration (s)", "Percentage"], tablefmt="fancy_grid")
    logger.info(f"📈 Startup Performance Summary:\n{table}")


async def log_all_commands(bot) -> None:
    """Log all registered prefix and slash commands in tabular form."""
    prefix_commands = [
        [cmd.name, cmd.help or "No description provided", ", ".join(cmd.aliases) or "None"]
        for cmd in bot.commands
    ]

    if prefix_commands:
        prefix_table = tabulate(
            prefix_commands,
            headers=["Prefix Command", "Description", "Aliases"],
            tablefmt="fancy_grid",
        )
        logger.info(f"📝 Registered Prefix Commands ({len(prefix_commands)}):\n{prefix_table}")
    else:
        logger.info("📝 No prefix commands registered")

    slash_commands = []

    def collect_commands(commands_, parent_name="N/A"):
        for cmd in commands_:
            if hasattr(cmd, "commands") and cmd.commands:
                collect_commands(cmd.commands, cmd.name)
            else:
                slash_commands.append(
                    [cmd.qualified_name, cmd.description or "No description provided", parent_name]
                )

    collect_commands(bot.tree.get_commands())

    if slash_commands:
        slash_table = tabulate(
            slash_commands,
            headers=["Slash Command", "Description", "Parent Command (Group)"],
            tablefmt="fancy_grid",
        )
        logger.info(f"⚡ Registered Slash Commands ({len(slash_commands)}):\n{slash_table}")
    else:
        logger.info("⚡ No slash commands registered")
