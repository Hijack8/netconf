#!/usr/bin/env python3
"""
Network Topology Discovery Script

Main entry point for discovering network topology across multiple hosts.

Usage:
    python scripts/discover.py --inventory inventory/hosts.yaml --output topology.json
    python scripts/discover.py -i inventory/hosts.yaml -o topology.json --format text
"""

import argparse
import logging
import os
import sys
from typing import Dict, Any, List

# Add parent directory to path for imports when running as script
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def collect_host_data(
    ssh,
    host_id: str,
    hostname: str,
    exclude_patterns: List[str],
    use_probe: bool = False
) -> Dict[str, Any]:
    """
    Collect all network data from a single host.

    Args:
        ssh: Connected SSH client
        host_id: Host identifier
        hostname: Host hostname/IP
        exclude_patterns: Interface exclusion patterns
        use_probe: Whether to use active probing

    Returns:
        Dictionary containing all collected data
    """
    from collector import InterfaceCollector, LinkStateCollector, NeighborDiscovery

    logger = logging.getLogger(__name__)

    # Collect interface information
    logger.info("  Collecting interfaces...")
    iface_collector = InterfaceCollector(ssh)
    interfaces = iface_collector.collect(exclude_patterns=exclude_patterns)
    logger.info(f"    Found {len(interfaces)} interfaces")

    # Get interface names for subsequent collectors
    interface_names = list(interfaces.keys())

    # Collect link states
    logger.info("  Collecting link states...")
    link_collector = LinkStateCollector(ssh)
    link_states = link_collector.collect(interface_names)

    # Collect neighbor information
    logger.info("  Discovering neighbors...")
    host_index = int(host_id.replace("host", "")) if host_id.startswith("host") else 0
    neighbor_discovery = NeighborDiscovery(ssh, host_id=host_index)
    neighbors = neighbor_discovery.discover_all(
        interface_names,
        use_lldp=True,
        use_arp=True,
        use_probe=use_probe
    )

    neighbor_count = sum(len(n) for n in neighbors.values())
    logger.info(f"    Found {neighbor_count} neighbor entries")

    # Convert dataclasses to dicts for serialization
    return {
        "hostname": hostname,
        "interfaces": {k: v.to_dict() for k, v in interfaces.items()},
        "link_states": {k: v.to_dict() for k, v in link_states.items()},
        "neighbors": {k: [n.to_dict() for n in v] for k, v in neighbors.items()},
    }


def discover_topology(
    inventory_path: str,
    use_probe: bool = False,
    hosts_filter: List[str] = None
) -> tuple:
    """
    Discover network topology from all hosts in inventory.

    Args:
        inventory_path: Path to hosts.yaml
        use_probe: Whether to use active probing
        hosts_filter: Optional list of specific hosts to scan

    Returns:
        Tuple of (Topology, List[ValidationIssue], raw_data dict)
    """
    from ssh_client import SSHClient, SSHClientError
    from inventory import load_inventory, get_host_ssh_config, list_hosts
    from engine import TopologyInferrer, TopologyValidator

    logger = logging.getLogger(__name__)

    # Load inventory
    logger.info(f"Loading inventory from {inventory_path}")
    inventory = load_inventory(inventory_path)
    exclude_patterns = inventory.get("exclude_interfaces", [])

    # Get hosts to scan
    all_hosts = list_hosts(inventory)
    if hosts_filter:
        hosts_to_scan = [h for h in hosts_filter if h in all_hosts]
        if not hosts_to_scan:
            raise ValueError(f"None of the specified hosts found in inventory: {hosts_filter}")
    else:
        hosts_to_scan = all_hosts

    logger.info(f"Will scan {len(hosts_to_scan)} hosts: {', '.join(hosts_to_scan)}")

    # Collect data from all hosts
    host_data: Dict[str, Dict[str, Any]] = {}
    failed_hosts: List[str] = []

    for host_id in hosts_to_scan:
        logger.info(f"Connecting to {host_id}...")

        try:
            ssh_config = get_host_ssh_config(inventory, host_id)
            hostname = ssh_config.pop("hostname")

            with SSHClient(hostname=hostname, **ssh_config) as ssh:
                data = collect_host_data(
                    ssh, host_id, hostname,
                    exclude_patterns, use_probe
                )
                host_data[host_id] = data

        except SSHClientError as e:
            logger.error(f"Failed to connect to {host_id}: {e}")
            failed_hosts.append(host_id)
        except Exception as e:
            logger.error(f"Error collecting data from {host_id}: {e}")
            failed_hosts.append(host_id)

    if failed_hosts:
        logger.warning(f"Failed to collect from {len(failed_hosts)} hosts: {', '.join(failed_hosts)}")

    if not host_data:
        raise RuntimeError("No data collected from any host")

    # Infer topology
    logger.info("Inferring topology...")
    inferrer = TopologyInferrer()
    topology = inferrer.infer(host_data)

    # Validate topology
    logger.info("Validating topology...")
    validator = TopologyValidator()
    issues = validator.validate(topology, host_data)

    return topology, issues, host_data


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Discover network topology across multiple hosts"
    )
    parser.add_argument(
        "-i", "--inventory",
        default="inventory/hosts.yaml",
        help="Path to inventory file (default: inventory/hosts.yaml)"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file path (default: stdout for text, required for JSON)"
    )
    parser.add_argument(
        "-f", "--format",
        choices=["json", "text", "ascii"],
        default="text",
        help="Output format: text, ascii (visual diagram), or json (default: text)"
    )
    parser.add_argument(
        "--hosts",
        nargs="+",
        help="Specific hosts to scan (default: all hosts in inventory)"
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Enable active probing for neighbor discovery"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )

    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Import here to allow --help to work without dependencies
    from ssh_client import SSHClientError
    from inventory import InventoryError
    from output import to_json, to_text, to_ascii, format_issues

    try:
        # Run discovery
        topology, issues, raw_data = discover_topology(
            args.inventory,
            use_probe=args.probe,
            hosts_filter=args.hosts
        )

        # Output results
        if args.format == "json":
            if not args.output:
                print("Error: --output is required for JSON format", file=sys.stderr)
                sys.exit(1)
            to_json(topology, args.output, issues)
            print(f"Topology written to {args.output}")

            # Also print summary
            print(f"\nDiscovered {len(topology.hosts)} hosts and {len(topology.links)} links")
            if issues:
                print(format_issues(issues))

        elif args.format == "ascii":
            text = to_ascii(topology, issues)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(text)
                print(f"ASCII diagram written to {args.output}")
            else:
                print(text)

        else:  # text format
            text = to_text(topology, issues)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(text)
                print(f"Report written to {args.output}")
            else:
                print(text)

    except InventoryError as e:
        logger.error(f"Inventory error: {e}")
        sys.exit(1)
    except SSHClientError as e:
        logger.error(f"SSH error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
