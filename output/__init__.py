"""
Output module - Topology output formatters

Contains formatters for different output formats:
- JSON
- Text (human-readable)
- ASCII art (visual topology diagram)
"""

from .formatters import to_json, to_text, to_ascii, format_issues

__all__ = ['to_json', 'to_text', 'to_ascii', 'format_issues']
