"""
Output Formatters

Provides functions to format topology and validation results
for different output formats.
"""

import json
import logging
from typing import List, Optional, TextIO
from pathlib import Path

from engine.infer import Topology
from engine.validate import ValidationIssue

logger = logging.getLogger(__name__)


def to_json(
    topology: Topology,
    path: str,
    issues: Optional[List[ValidationIssue]] = None,
    indent: int = 2
) -> None:
    """
    Write topology to a JSON file.

    Args:
        topology: Topology object to serialize
        path: Output file path
        issues: Optional list of validation issues to include
        indent: JSON indentation level
    """
    output = topology.to_dict()

    if issues is not None:
        output["validation_issues"] = [issue.to_dict() for issue in issues]
        output["summary"]["issue_count"] = len(issues)
        output["summary"]["error_count"] = sum(1 for i in issues if i.severity == "error")
        output["summary"]["warning_count"] = sum(1 for i in issues if i.severity == "warning")

    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=indent, ensure_ascii=False)

    logger.info(f"Topology written to {path}")


def to_text(
    topology: Topology,
    issues: Optional[List[ValidationIssue]] = None,
    file: Optional[TextIO] = None
) -> str:
    """
    Format topology as human-readable text.

    Args:
        topology: Topology object to format
        issues: Optional list of validation issues
        file: Optional file to write to

    Returns:
        Formatted text string
    """
    lines = []

    # Header
    lines.append("=" * 60)
    lines.append("NETWORK TOPOLOGY REPORT")
    lines.append("=" * 60)
    lines.append("")

    # Summary
    summary = topology.to_dict()["summary"]
    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"  Hosts:              {summary['host_count']}")
    lines.append(f"  Total Links:        {summary['link_count']}")
    lines.append(f"  Bidirectional:      {summary['bidirectional_links']}")
    lines.append(f"  Unidirectional:     {summary['unidirectional_links']}")
    lines.append("")

    # Hosts
    lines.append("HOSTS")
    lines.append("-" * 40)
    for host_id, host_info in sorted(topology.hosts.items()):
        iface_count = len(host_info.interfaces)
        lines.append(f"  {host_id} ({host_info.hostname})")
        lines.append(f"    Interfaces: {iface_count}")

        # List interfaces with their MACs
        for iface_name, iface_data in sorted(host_info.interfaces.items()):
            mac = _get_mac(iface_data)
            state = _get_state(iface_data)
            lines.append(f"      - {iface_name}: {mac} ({state})")

    lines.append("")

    # Links
    lines.append("LINKS")
    lines.append("-" * 40)
    if topology.links:
        for link in topology.links:
            direction = "<-->" if link.bidirectional else "--->"
            methods = ", ".join(link.discovery_methods)
            lines.append(
                f"  {link.port_a.host}:{link.port_a.interface} "
                f"{direction} "
                f"{link.port_b.host}:{link.port_b.interface}"
            )
            lines.append(f"    Discovered via: {methods}")
    else:
        lines.append("  No links discovered")
    lines.append("")

    # Validation issues
    if issues:
        lines.append("VALIDATION ISSUES")
        lines.append("-" * 40)
        for issue in issues:
            severity_marker = {
                "error": "[ERROR]",
                "warning": "[WARN]",
                "info": "[INFO]"
            }.get(issue.severity, "[?]")

            lines.append(f"  {severity_marker} {issue.host}:{issue.interface}")
            lines.append(f"    {issue.message}")
        lines.append("")

    # Footer
    lines.append("=" * 60)

    text = "\n".join(lines)

    if file is not None:
        file.write(text)

    return text


def format_issues(issues: List[ValidationIssue]) -> str:
    """
    Format validation issues as a summary text.

    Args:
        issues: List of validation issues

    Returns:
        Formatted summary string
    """
    if not issues:
        return "No validation issues found."

    lines = []

    error_count = sum(1 for i in issues if i.severity == "error")
    warning_count = sum(1 for i in issues if i.severity == "warning")
    info_count = sum(1 for i in issues if i.severity == "info")

    lines.append(f"Found {len(issues)} issues: {error_count} errors, {warning_count} warnings, {info_count} info")
    lines.append("")

    for issue in issues:
        prefix = {
            "error": "ERROR",
            "warning": "WARN",
            "info": "INFO"
        }.get(issue.severity, "???")

        lines.append(f"[{prefix}] {issue.host}:{issue.interface} - {issue.message}")

    return "\n".join(lines)


def _get_mac(iface_data) -> str:
    """Extract MAC from interface data."""
    if isinstance(iface_data, dict):
        return iface_data.get("mac", "unknown")
    if hasattr(iface_data, "mac"):
        return getattr(iface_data, "mac", "unknown")
    return "unknown"


def _get_state(iface_data) -> str:
    """Extract state from interface data."""
    if isinstance(iface_data, dict):
        return iface_data.get("state", "unknown")
    if hasattr(iface_data, "state"):
        return getattr(iface_data, "state", "unknown")
    return "unknown"
