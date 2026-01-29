"""
Topology Validation Engine

Validates the inferred topology and collected data for:
- Unidirectional links (warning)
- Speed mismatches between link ends
- Interfaces with no detected link
- Error counters above threshold
"""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict

from .infer import Topology, Link

logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    """Represents a validation issue found in the topology."""
    severity: str  # "error", "warning", "info"
    host: str
    interface: str
    message: str
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        if result["details"] is None:
            del result["details"]
        return result


class TopologyValidator:
    """
    Validates topology and collected data for issues.

    Validation checks:
    1. Unidirectional links - only one side sees the other
    2. Speed mismatches - link ends have different speeds
    3. No link detected - interface is up but no link
    4. Error counters - RX/TX errors above threshold
    5. Duplex mismatches - different duplex settings
    """

    # Default thresholds
    DEFAULT_ERROR_THRESHOLD = 100
    DEFAULT_DROPPED_THRESHOLD = 1000

    def __init__(
        self,
        error_threshold: int = DEFAULT_ERROR_THRESHOLD,
        dropped_threshold: int = DEFAULT_DROPPED_THRESHOLD
    ):
        """
        Initialize validator with thresholds.

        Args:
            error_threshold: Max acceptable error count before warning
            dropped_threshold: Max acceptable dropped packet count before warning
        """
        self.error_threshold = error_threshold
        self.dropped_threshold = dropped_threshold

    def validate(
        self,
        topology: Topology,
        raw_data: Dict[str, Dict[str, Any]]
    ) -> List[ValidationIssue]:
        """
        Validate topology and collected data.

        Args:
            topology: Inferred topology
            raw_data: Raw collected data from all hosts

        Returns:
            List of validation issues found
        """
        issues: List[ValidationIssue] = []

        # Check for unidirectional links
        issues.extend(self._check_unidirectional_links(topology))

        # Check for speed/duplex mismatches
        issues.extend(self._check_link_mismatches(topology, raw_data))

        # Check for interfaces without links
        issues.extend(self._check_no_link_detected(topology, raw_data))

        # Check error counters
        issues.extend(self._check_error_counters(raw_data))

        # Sort by severity (error first, then warning, then info)
        severity_order = {"error": 0, "warning": 1, "info": 2}
        issues.sort(key=lambda x: (severity_order.get(x.severity, 3), x.host, x.interface))

        logger.info(
            f"Validation complete: {len(issues)} issues "
            f"({sum(1 for i in issues if i.severity == 'error')} errors, "
            f"{sum(1 for i in issues if i.severity == 'warning')} warnings)"
        )

        return issues

    def _check_unidirectional_links(self, topology: Topology) -> List[ValidationIssue]:
        """Check for links where only one side sees the other."""
        issues = []

        for link in topology.links:
            if not link.bidirectional:
                issues.append(ValidationIssue(
                    severity="warning",
                    host=link.port_a.host,
                    interface=link.port_a.interface,
                    message=(
                        f"Unidirectional link to {link.port_b.host}:{link.port_b.interface} - "
                        f"only one side observes the connection"
                    ),
                    details={
                        "remote_host": link.port_b.host,
                        "remote_interface": link.port_b.interface,
                        "discovery_methods": link.discovery_methods,
                    }
                ))

        return issues

    def _check_link_mismatches(
        self,
        topology: Topology,
        raw_data: Dict[str, Dict[str, Any]]
    ) -> List[ValidationIssue]:
        """Check for speed/duplex mismatches between link endpoints."""
        issues = []

        for link in topology.links:
            port_a_state = self._get_link_state(
                raw_data, link.port_a.host, link.port_a.interface
            )
            port_b_state = self._get_link_state(
                raw_data, link.port_b.host, link.port_b.interface
            )

            if not port_a_state or not port_b_state:
                continue

            # Check speed mismatch
            speed_a = port_a_state.get("speed", "")
            speed_b = port_b_state.get("speed", "")

            if speed_a and speed_b and speed_a != speed_b:
                issues.append(ValidationIssue(
                    severity="warning",
                    host=link.port_a.host,
                    interface=link.port_a.interface,
                    message=(
                        f"Speed mismatch with {link.port_b.host}:{link.port_b.interface}: "
                        f"{speed_a} vs {speed_b}"
                    ),
                    details={
                        "local_speed": speed_a,
                        "remote_speed": speed_b,
                        "remote_host": link.port_b.host,
                        "remote_interface": link.port_b.interface,
                    }
                ))

            # Check duplex mismatch
            duplex_a = port_a_state.get("duplex", "")
            duplex_b = port_b_state.get("duplex", "")

            if duplex_a and duplex_b and duplex_a != duplex_b:
                issues.append(ValidationIssue(
                    severity="warning",
                    host=link.port_a.host,
                    interface=link.port_a.interface,
                    message=(
                        f"Duplex mismatch with {link.port_b.host}:{link.port_b.interface}: "
                        f"{duplex_a} vs {duplex_b}"
                    ),
                    details={
                        "local_duplex": duplex_a,
                        "remote_duplex": duplex_b,
                        "remote_host": link.port_b.host,
                        "remote_interface": link.port_b.interface,
                    }
                ))

        return issues

    def _check_no_link_detected(
        self,
        topology: Topology,
        raw_data: Dict[str, Dict[str, Any]]
    ) -> List[ValidationIssue]:
        """Check for interfaces that are up but have no detected link."""
        issues = []

        for host_id, data in raw_data.items():
            interfaces = data.get("interfaces", {})
            link_states = data.get("link_states", {})

            for iface_name, iface_data in interfaces.items():
                # Get interface state
                state = self._get_value(iface_data, "state", "unknown")
                if state != "up":
                    continue

                # Check if link is detected
                link_state = link_states.get(iface_name, {})
                link_detected = self._get_value(link_state, "link_detected", False)
                carrier = self._get_value(link_state, "carrier", False)

                if not link_detected and not carrier:
                    # Check if there's a topology link for this interface
                    has_topo_link = topology.get_link_for_interface(host_id, iface_name) is not None

                    if not has_topo_link:
                        issues.append(ValidationIssue(
                            severity="info",
                            host=host_id,
                            interface=iface_name,
                            message="Interface is up but no link detected and no neighbors found",
                        ))

        return issues

    def _check_error_counters(
        self,
        raw_data: Dict[str, Dict[str, Any]]
    ) -> List[ValidationIssue]:
        """Check for interfaces with high error counters."""
        issues = []

        for host_id, data in raw_data.items():
            link_states = data.get("link_states", {})

            for iface_name, link_state in link_states.items():
                stats = self._get_value(link_state, "stats", {})
                if not stats:
                    continue

                # Check RX errors
                rx_errors = self._get_value(stats, "rx_errors", 0)
                if rx_errors > self.error_threshold:
                    issues.append(ValidationIssue(
                        severity="warning",
                        host=host_id,
                        interface=iface_name,
                        message=f"High RX error count: {rx_errors}",
                        details={"rx_errors": rx_errors, "threshold": self.error_threshold},
                    ))

                # Check TX errors
                tx_errors = self._get_value(stats, "tx_errors", 0)
                if tx_errors > self.error_threshold:
                    issues.append(ValidationIssue(
                        severity="warning",
                        host=host_id,
                        interface=iface_name,
                        message=f"High TX error count: {tx_errors}",
                        details={"tx_errors": tx_errors, "threshold": self.error_threshold},
                    ))

                # Check RX dropped
                rx_dropped = self._get_value(stats, "rx_dropped", 0)
                if rx_dropped > self.dropped_threshold:
                    issues.append(ValidationIssue(
                        severity="info",
                        host=host_id,
                        interface=iface_name,
                        message=f"High RX dropped count: {rx_dropped}",
                        details={"rx_dropped": rx_dropped, "threshold": self.dropped_threshold},
                    ))

                # Check TX dropped
                tx_dropped = self._get_value(stats, "tx_dropped", 0)
                if tx_dropped > self.dropped_threshold:
                    issues.append(ValidationIssue(
                        severity="info",
                        host=host_id,
                        interface=iface_name,
                        message=f"High TX dropped count: {tx_dropped}",
                        details={"tx_dropped": tx_dropped, "threshold": self.dropped_threshold},
                    ))

        return issues

    def _get_link_state(
        self,
        raw_data: Dict[str, Dict[str, Any]],
        host: str,
        interface: str
    ) -> Optional[Dict[str, Any]]:
        """Get link state for a specific interface."""
        host_data = raw_data.get(host)
        if not host_data:
            return None

        link_states = host_data.get("link_states", {})
        state = link_states.get(interface)

        if state is None:
            return None

        # Convert to dict if it's an object
        if hasattr(state, "to_dict"):
            return state.to_dict()
        if isinstance(state, dict):
            return state
        return None

    def _get_value(self, data: Any, key: str, default: Any = None) -> Any:
        """Get a value from dict or object."""
        if data is None:
            return default
        if isinstance(data, dict):
            return data.get(key, default)
        if hasattr(data, key):
            return getattr(data, key, default)
        if hasattr(data, "to_dict"):
            return data.to_dict().get(key, default)
        return default
