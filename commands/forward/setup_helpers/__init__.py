"""Setup helpers for the forward extension.

The interactive /setup /forward wizard was removed (it registered no commands and
was unreachable); only the shared rule-defaults factory remains, still used by the
admin panel's Forwarding Rules section.
"""
from .rule_setup import rule_setup_helper

__all__ = [
    'rule_setup_helper',
]
