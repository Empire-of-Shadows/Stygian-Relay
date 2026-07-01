# ───────────────────────────────────────────────────────────────────────────
# VENDORED from storage_engine/ — DO NOT EDIT HERE.
# Edit the master at <repo-root>/EmpireSystems/storage_engine/ and run:
#     python tools/sync_storage_engine.py
# Drift is enforced by:  python tools/sync_storage_engine.py --check
# ───────────────────────────────────────────────────────────────────────────
"""Performance-timing helpers built on the engine logger.

A context manager / decorator pair plus a small timing context, all of which log operation
start/end and elapsed seconds. Part of the shared logging toolkit; some bots don't use these
yet, but they stay here so every bot has the same surface.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from datetime import datetime
from functools import wraps


class PerformanceLogger:
    """Context manager for measuring execution time of a named operation."""

    def __init__(self, logger: logging.Logger, operation_name: str):
        self.logger = logger
        self.operation_name = operation_name
        self.start_time = None

    def __enter__(self):
        self.start_time = datetime.now()
        self.logger.debug(f"Starting operation: {self.operation_name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()
        self.logger.info(f"Operation '{self.operation_name}' completed in {duration:.4f}s")


def log_performance(operation_name: str = None):
    """Decorator to log function execution time for both sync and async functions."""

    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            # Handle async functions
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                logger = logging.getLogger(func.__module__)
                op_name = operation_name or f"{func.__name__}"

                with PerformanceLogger(logger, op_name):
                    return await func(*args, **kwargs)

            return async_wrapper
        else:
            # Handle sync functions
            @wraps(func)
            def wrapper(*args, **kwargs):
                logger = logging.getLogger(func.__module__)
                op_name = operation_name or f"{func.__name__}"

                with PerformanceLogger(logger, op_name):
                    return func(*args, **kwargs)

            return wrapper

    return decorator


@contextmanager
def log_context(logger: logging.Logger, operation_name: str, level: int = logging.INFO):
    """Context manager for logging operation start and end with elapsed time."""
    logger.log(level, f"Starting: {operation_name}")
    start_time = datetime.now()

    try:
        yield
        duration = (datetime.now() - start_time).total_seconds()
        logger.log(level, f"Completed: {operation_name} (took {duration:.4f}s)")
    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        logger.error(f"Failed: {operation_name} after {duration:.4f}s - {str(e)}")
        raise
