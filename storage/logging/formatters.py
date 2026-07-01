# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""Log formatters and filters for the engine's structured logger.

Pure, stateless ``logging.Formatter`` subclasses (plus a small message filter) shared by the
logger factory. No engine/bot dependencies — only the stdlib.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List


class ColoredConsoleFormatter(logging.Formatter):
    """Formatter that adds ANSI colors to console output based on log level."""

    COLORS = {
        'DEBUG': '\033[36m',  # Cyan
        'INFO': '\033[32m',  # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',  # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, '')
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)


class IndentedFormatter(logging.Formatter):
    """Place the log message on a new line and indent it for readability."""

    def __init__(self, fmt=None, datefmt=None, style='%', validate=True, indent_size=25):
        super().__init__(fmt, datefmt, style, validate)
        self.indent_size = indent_size

    def format(self, record):
        # Process the log message using the base formatter
        original_message = super().format(record)

        # Add a newline and indent the log message part
        if ": " in original_message:
            # Split the log parts: 'timestamp [level]:' and 'message'
            parts = original_message.split(": ", 1)
            indent = " " * self.indent_size
            formatted_message = f"{parts[0]}:\n{indent}{parts[1]}"
        else:
            formatted_message = original_message  # Fallback if format is unexpected

        return formatted_message


class JSONFormatter(logging.Formatter):
    """Emit log records as JSON objects (one per line), including any extra fields."""

    def format(self, record):
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'thread': record.thread,
            'thread_name': record.threadName,
        }

        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)

        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename',
                           'module', 'exc_info', 'exc_text', 'stack_info', 'lineno', 'funcName',
                           'created', 'msecs', 'relativeCreated', 'thread', 'threadName',
                           'processName', 'process', 'message']:
                log_entry[key] = value

        return json.dumps(log_entry)


class LogFilter:
    """Include/exclude log records by substring match on the rendered message."""

    def __init__(self, include_patterns: List[str] = None, exclude_patterns: List[str] = None):
        self.include_patterns = include_patterns or []
        self.exclude_patterns = exclude_patterns or []

    def filter(self, record):
        message = record.getMessage()

        # If include patterns are specified, message must match at least one
        if self.include_patterns:
            if not any(pattern in message for pattern in self.include_patterns):
                return False

        # If exclude patterns are specified, message must not match any
        if self.exclude_patterns:
            if any(pattern in message for pattern in self.exclude_patterns):
                return False

        return True
