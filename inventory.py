"""
Inventory Loader

Loads and parses the hosts.yaml configuration file,
merging defaults with per-host settings.
"""

import os
import logging
from typing import Dict, List, Any, Optional

import yaml

logger = logging.getLogger(__name__)


class InventoryError(Exception):
    """Exception raised for inventory loading errors."""
    pass


def load_inventory(path: str) -> Dict[str, Any]:
    """
    Load and parse the inventory configuration file.

    Args:
        path: Path to the hosts.yaml file

    Returns:
        Dictionary containing:
        - hosts: Dict of host configurations with defaults merged
        - exclude_interfaces: List of interface exclusion patterns

    Raises:
        InventoryError: If file cannot be loaded or parsed
    """
    path = os.path.expanduser(path)

    if not os.path.isfile(path):
        raise InventoryError(f"Inventory file not found: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise InventoryError(f"Failed to parse inventory file: {e}")
    except IOError as e:
        raise InventoryError(f"Failed to read inventory file: {e}")

    if not data:
        raise InventoryError("Inventory file is empty")

    return _process_inventory(data)


def _process_inventory(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process raw inventory data, merging defaults with host configs.

    Args:
        data: Raw parsed YAML data

    Returns:
        Processed inventory with merged host configurations
    """
    # Extract defaults
    defaults = data.get("ssh_defaults", {})
    default_port = defaults.get("port", 22)
    default_username = defaults.get("username", "root")
    default_auth_type = defaults.get("auth_type", "key")
    default_key_file = defaults.get("key_file")
    default_password = defaults.get("password")
    default_timeout = defaults.get("timeout", 10)

    # Process hosts
    raw_hosts = data.get("hosts", {})
    if not raw_hosts:
        raise InventoryError("No hosts defined in inventory")

    hosts = {}
    for host_id, host_config in raw_hosts.items():
        if not host_config:
            logger.warning(f"Host {host_id} has no configuration, skipping")
            continue

        hostname = host_config.get("hostname")
        if not hostname:
            logger.warning(f"Host {host_id} has no hostname, skipping")
            continue

        hosts[host_id] = {
            "hostname": hostname,
            "port": host_config.get("port", default_port),
            "username": host_config.get("username", default_username),
            "auth_type": host_config.get("auth_type", default_auth_type),
            "key_file": host_config.get("key_file", default_key_file),
            "password": host_config.get("password", default_password),
            "timeout": host_config.get("timeout", default_timeout),
            "description": host_config.get("description", ""),
        }

    # Extract interface exclusion patterns
    exclude_interfaces = data.get("exclude_interfaces", [])

    return {
        "hosts": hosts,
        "exclude_interfaces": exclude_interfaces,
    }


def get_host_ssh_config(inventory: Dict[str, Any], host_id: str) -> Dict[str, Any]:
    """
    Extract SSH connection parameters for a specific host.

    Args:
        inventory: Processed inventory data
        host_id: Host identifier

    Returns:
        Dictionary with SSH connection parameters

    Raises:
        InventoryError: If host not found
    """
    hosts = inventory.get("hosts", {})
    if host_id not in hosts:
        raise InventoryError(f"Host not found in inventory: {host_id}")

    host = hosts[host_id]
    return {
        "hostname": host["hostname"],
        "port": host["port"],
        "username": host["username"],
        "auth_type": host["auth_type"],
        "key_file": host["key_file"],
        "password": host["password"],
        "timeout": host["timeout"],
    }


def list_hosts(inventory: Dict[str, Any]) -> List[str]:
    """
    Get list of all host IDs in the inventory.

    Args:
        inventory: Processed inventory data

    Returns:
        List of host identifiers
    """
    return list(inventory.get("hosts", {}).keys())
