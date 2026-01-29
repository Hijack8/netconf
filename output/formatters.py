"""
Output Formatters

Provides functions to format topology and validation results
for different output formats.
"""

import json
import logging
from collections import defaultdict
from typing import List, Optional, TextIO, Dict, Set, Tuple
from pathlib import Path

from engine.infer import Topology, Link
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


def to_ascii(
    topology: Topology,
    issues: Optional[List[ValidationIssue]] = None,
) -> str:
    """
    Generate ASCII art visualization of the network topology.

    Args:
        topology: Topology object to visualize
        issues: Optional list of validation issues

    Returns:
        ASCII art string representation
    """
    lines = []

    # Build connection lookup: (host, iface) -> (peer_host, peer_iface, bidirectional)
    connections: Dict[Tuple[str, str], Tuple[str, str, bool]] = {}
    for link in topology.links:
        connections[(link.port_a.host, link.port_a.interface)] = (
            link.port_b.host, link.port_b.interface, link.bidirectional
        )
        connections[(link.port_b.host, link.port_b.interface)] = (
            link.port_a.host, link.port_a.interface, link.bidirectional
        )

    # Title
    lines.append("╔" + "═" * 62 + "╗")
    lines.append("║" + "NETWORK TOPOLOGY".center(62) + "║")
    lines.append("╚" + "═" * 62 + "╝")
    lines.append("")

    # Summary bar
    summary = topology.to_dict()["summary"]
    lines.append(f"  Hosts: {summary['host_count']}  │  "
                 f"Links: {summary['link_count']}  │  "
                 f"Bidirectional: {summary['bidirectional_links']}  │  "
                 f"Unidirectional: {summary['unidirectional_links']}")
    lines.append("")

    # Draw each host as a box
    for host_id in sorted(topology.hosts.keys()):
        host_info = topology.hosts[host_id]
        lines.extend(_draw_host_box(host_id, host_info, connections))
        lines.append("")

    # Connection matrix
    lines.append("┌" + "─" * 62 + "┐")
    lines.append("│" + "CONNECTION MATRIX".center(62) + "│")
    lines.append("└" + "─" * 62 + "┘")
    lines.append("")
    lines.extend(_draw_connection_matrix(topology))
    lines.append("")

    # Link diagram
    lines.append("┌" + "─" * 62 + "┐")
    lines.append("│" + "LINK DIAGRAM".center(62) + "│")
    lines.append("└" + "─" * 62 + "┘")
    lines.append("")
    lines.extend(_draw_link_diagram(topology))

    # Validation issues
    if issues:
        lines.append("")
        lines.append("┌" + "─" * 62 + "┐")
        lines.append("│" + "VALIDATION ISSUES".center(62) + "│")
        lines.append("└" + "─" * 62 + "┘")
        for issue in issues:
            icon = {"error": "✗", "warning": "⚠", "info": "ℹ"}.get(issue.severity, "?")
            lines.append(f"  {icon} [{issue.severity.upper()}] {issue.host}:{issue.interface}")
            lines.append(f"      {issue.message}")

    return "\n".join(lines)


def _draw_host_box(
    host_id: str,
    host_info,
    connections: Dict[Tuple[str, str], Tuple[str, str, bool]]
) -> List[str]:
    """Draw a single host as an ASCII box with interface connections."""
    lines = []

    # Determine box width
    hostname = host_info.hostname if hasattr(host_info, 'hostname') else host_id
    title = f" {host_id} ({hostname}) "
    box_width = max(58, len(title) + 4)

    # Top border
    lines.append("┌" + "─" * box_width + "┐")
    lines.append("│" + title.center(box_width) + "│")
    lines.append("├" + "─" * box_width + "┤")

    # Get interfaces
    interfaces = host_info.interfaces if hasattr(host_info, 'interfaces') else {}

    if not interfaces:
        lines.append("│" + "(no interfaces)".center(box_width) + "│")
    else:
        for iface_name in sorted(interfaces.keys()):
            iface_data = interfaces[iface_name]
            mac = _get_mac(iface_data)
            state = _get_state(iface_data)

            # Check if connected
            conn_key = (host_id, iface_name)
            if conn_key in connections:
                peer_host, peer_iface, bidirectional = connections[conn_key]
                arrow = "⟷" if bidirectional else "→"
                conn_str = f"{arrow} {peer_host}:{peer_iface}"
                icon = "●"  # Connected
            else:
                conn_str = "(no link)"
                icon = "○"  # Not connected

            # State indicator
            state_icon = "▲" if state == "up" else "▼" if state == "down" else "?"

            # Format line
            left_part = f"  {icon} {iface_name}"
            right_part = f"{conn_str}  {state_icon}"

            # Calculate padding
            padding = box_width - len(left_part) - len(right_part)
            if padding < 1:
                padding = 1

            line_content = left_part + " " * padding + right_part
            lines.append("│" + line_content[:box_width].ljust(box_width) + "│")

    # Bottom border
    lines.append("└" + "─" * box_width + "┘")

    return lines


def _draw_connection_matrix(topology: Topology) -> List[str]:
    """Draw a matrix showing connections between hosts."""
    lines = []
    hosts = sorted(topology.hosts.keys())

    if not hosts:
        lines.append("  (no hosts)")
        return lines

    # Build adjacency data: host -> list of (local_iface, peer_host, peer_iface)
    adjacency: Dict[str, Dict[str, List[Tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))

    for link in topology.links:
        h1, i1 = link.port_a.host, link.port_a.interface
        h2, i2 = link.port_b.host, link.port_b.interface
        adjacency[h1][h2].append((i1, i2))
        adjacency[h2][h1].append((i2, i1))

    # Header row
    col_width = 12
    header = "  " + " " * col_width
    for h in hosts:
        header += h[:col_width].center(col_width)
    lines.append(header)
    lines.append("  " + "─" * (col_width + len(hosts) * col_width))

    # Data rows
    for h1 in hosts:
        row = f"  {h1[:col_width]:<{col_width}}"
        for h2 in hosts:
            if h1 == h2:
                cell = "─"
            elif h2 in adjacency[h1]:
                conns = adjacency[h1][h2]
                if len(conns) == 1:
                    cell = f"{conns[0][0]}↔{conns[0][1]}"
                else:
                    cell = f"{len(conns)} links"
            else:
                cell = "·"
            row += cell[:col_width].center(col_width)
        lines.append(row)

    return lines


def _draw_link_diagram(topology: Topology) -> List[str]:
    """Draw a visual diagram of all links."""
    lines = []

    if not topology.links:
        lines.append("  (no links discovered)")
        return lines

    # Group links by type
    bidir_links = [l for l in topology.links if l.bidirectional]
    unidir_links = [l for l in topology.links if not l.bidirectional]

    if bidir_links:
        lines.append("  Bidirectional Links (confirmed both directions):")
        lines.append("  " + "─" * 50)
        for link in bidir_links:
            left = f"{link.port_a.host}:{link.port_a.interface}"
            right = f"{link.port_b.host}:{link.port_b.interface}"
            methods = ", ".join(link.discovery_methods)
            lines.append(f"    {left:>25} ⟷ {right:<25}")
            lines.append(f"    {'':>25}   └─ [{methods}]")
        lines.append("")

    if unidir_links:
        lines.append("  Unidirectional Links (seen from one side only):")
        lines.append("  " + "─" * 50)
        for link in unidir_links:
            left = f"{link.port_a.host}:{link.port_a.interface}"
            right = f"{link.port_b.host}:{link.port_b.interface}"
            methods = ", ".join(link.discovery_methods)
            lines.append(f"    {left:>25} → {right:<25}")
            lines.append(f"    {'':>25}   └─ [{methods}]")

    return lines
