"""
Topology Inference Engine

Builds a network topology from collected host data by:
1. Building MAC-to-(host, interface) mapping from all hosts
2. Matching neighbor observations to find links
3. Creating bidirectional links where both sides see each other
"""

import logging
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class Port:
    """Represents a network port (interface) on a host."""
    host: str
    interface: str
    mac: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)

    def __hash__(self):
        return hash((self.host, self.interface))

    def __eq__(self, other):
        if not isinstance(other, Port):
            return False
        return self.host == other.host and self.interface == other.interface


@dataclass
class Link:
    """Represents a network link between two ports."""
    port_a: Port
    port_b: Port
    bidirectional: bool = False
    discovery_methods: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "port_a": self.port_a.to_dict(),
            "port_b": self.port_b.to_dict(),
            "bidirectional": self.bidirectional,
            "discovery_methods": self.discovery_methods,
        }

    def involves_port(self, host: str, interface: str) -> bool:
        """Check if this link involves a specific port."""
        return (
            (self.port_a.host == host and self.port_a.interface == interface) or
            (self.port_b.host == host and self.port_b.interface == interface)
        )


@dataclass
class HostInfo:
    """Summary of collected information for a host."""
    host_id: str
    hostname: str
    interfaces: Dict[str, Any] = field(default_factory=dict)
    link_states: Dict[str, Any] = field(default_factory=dict)
    neighbors: Dict[str, List[Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "host_id": self.host_id,
            "hostname": self.hostname,
            "interface_count": len(self.interfaces),
            "interfaces": list(self.interfaces.keys()),
        }


@dataclass
class Topology:
    """Complete network topology."""
    hosts: Dict[str, HostInfo] = field(default_factory=dict)
    links: List[Link] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hosts": {h: info.to_dict() for h, info in self.hosts.items()},
            "links": [link.to_dict() for link in self.links],
            "summary": {
                "host_count": len(self.hosts),
                "link_count": len(self.links),
                "bidirectional_links": sum(1 for l in self.links if l.bidirectional),
                "unidirectional_links": sum(1 for l in self.links if not l.bidirectional),
            }
        }

    def get_links_for_host(self, host_id: str) -> List[Link]:
        """Get all links involving a specific host."""
        return [
            link for link in self.links
            if link.port_a.host == host_id or link.port_b.host == host_id
        ]

    def get_link_for_interface(self, host: str, interface: str) -> Optional[Link]:
        """Get the link for a specific interface, if any."""
        for link in self.links:
            if link.involves_port(host, interface):
                return link
        return None


class TopologyInferrer:
    """
    Infers network topology from collected host data.

    The inference process:
    1. Build a global MAC-to-(host, interface) mapping
    2. For each host's neighbor observations, look up the remote MAC
    3. Create links between local and remote ports
    4. Mark links as bidirectional if both ends observe each other
    """

    def __init__(self):
        self._mac_to_port: Dict[str, Port] = {}
        self._observed_links: Set[Tuple[str, str, str, str]] = set()

    def infer(self, host_data: Dict[str, Dict[str, Any]]) -> Topology:
        """
        Infer topology from collected host data.

        Args:
            host_data: Dictionary mapping host_id to collected data.
                Each host's data should contain:
                - hostname: str
                - interfaces: Dict[str, InterfaceInfo]
                - link_states: Dict[str, LinkState]
                - neighbors: Dict[str, List[NeighborInfo]]

        Returns:
            Inferred Topology object
        """
        topology = Topology()

        # Phase 1: Build MAC-to-port mapping and collect host info
        self._mac_to_port.clear()
        self._observed_links.clear()

        for host_id, data in host_data.items():
            host_info = self._process_host(host_id, data)
            topology.hosts[host_id] = host_info

        logger.info(f"Built MAC mapping with {len(self._mac_to_port)} entries")

        # Phase 2: Process neighbor observations to find links
        links_map: Dict[Tuple[Port, Port], Link] = {}

        for host_id, data in host_data.items():
            neighbors = data.get("neighbors", {})
            interfaces = data.get("interfaces", {})

            for iface, neighbor_list in neighbors.items():
                if iface not in interfaces:
                    continue

                local_mac = self._get_interface_mac(interfaces, iface)
                local_port = Port(host=host_id, interface=iface, mac=local_mac)

                for neighbor in neighbor_list:
                    remote_mac = neighbor.get("remote_mac", "")
                    if not remote_mac:
                        continue

                    remote_port = self._mac_to_port.get(remote_mac)
                    if not remote_port:
                        logger.debug(
                            f"Unknown remote MAC {remote_mac} seen from "
                            f"{host_id}:{iface}"
                        )
                        continue

                    # Skip self-references
                    if remote_port.host == host_id:
                        continue

                    # Create or update link
                    link_key = self._normalize_link_key(local_port, remote_port)
                    discovery_method = neighbor.get("discovery_method", "unknown")

                    if link_key not in links_map:
                        links_map[link_key] = Link(
                            port_a=link_key[0],
                            port_b=link_key[1],
                            bidirectional=False,
                            discovery_methods=[discovery_method],
                        )
                    else:
                        link = links_map[link_key]
                        if discovery_method not in link.discovery_methods:
                            link.discovery_methods.append(discovery_method)

                    # Track observation direction for bidirectional detection
                    obs_key = (host_id, iface, remote_port.host, remote_port.interface)
                    self._observed_links.add(obs_key)

        # Phase 3: Mark bidirectional links
        for link in links_map.values():
            forward = (
                link.port_a.host, link.port_a.interface,
                link.port_b.host, link.port_b.interface
            )
            reverse = (
                link.port_b.host, link.port_b.interface,
                link.port_a.host, link.port_a.interface
            )
            link.bidirectional = forward in self._observed_links and reverse in self._observed_links

        topology.links = list(links_map.values())

        logger.info(
            f"Inferred topology: {len(topology.hosts)} hosts, "
            f"{len(topology.links)} links "
            f"({sum(1 for l in topology.links if l.bidirectional)} bidirectional)"
        )

        return topology

    def _process_host(self, host_id: str, data: Dict[str, Any]) -> HostInfo:
        """Process a single host's data and update MAC mapping."""
        host_info = HostInfo(
            host_id=host_id,
            hostname=data.get("hostname", host_id),
            interfaces=data.get("interfaces", {}),
            link_states=data.get("link_states", {}),
            neighbors=data.get("neighbors", {}),
        )

        # Build MAC-to-port mapping for this host
        for iface_name, iface_data in host_info.interfaces.items():
            mac = self._get_interface_mac_from_data(iface_data)
            if mac:
                port = Port(host=host_id, interface=iface_name, mac=mac)
                if mac in self._mac_to_port:
                    existing = self._mac_to_port[mac]
                    logger.warning(
                        f"Duplicate MAC {mac}: {existing.host}:{existing.interface} "
                        f"and {host_id}:{iface_name}"
                    )
                self._mac_to_port[mac] = port

        return host_info

    def _get_interface_mac(self, interfaces: Dict[str, Any], iface: str) -> str:
        """Get MAC address for an interface from interfaces dict."""
        iface_data = interfaces.get(iface)
        return self._get_interface_mac_from_data(iface_data)

    def _get_interface_mac_from_data(self, iface_data: Any) -> str:
        """Extract MAC address from interface data (dict or object)."""
        if iface_data is None:
            return ""
        if isinstance(iface_data, dict):
            return iface_data.get("mac", "").lower()
        if hasattr(iface_data, "mac"):
            return getattr(iface_data, "mac", "").lower()
        return ""

    def _normalize_link_key(self, port_a: Port, port_b: Port) -> Tuple[Port, Port]:
        """
        Normalize link key to ensure consistent ordering.
        Orders by (host, interface) to avoid duplicate links.
        """
        key_a = (port_a.host, port_a.interface)
        key_b = (port_b.host, port_b.interface)
        if key_a <= key_b:
            return (port_a, port_b)
        return (port_b, port_a)
