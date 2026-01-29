# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Multi-host network topology discovery tool for lab/testbed environments. Discovers network interfaces, link states, and neighbor relationships across multiple hosts via SSH to automatically build a network topology map.

**Primary use case**: Network research testbeds (DPDK, RDMA, programmable networks) with direct host-to-host connections.

## Architecture

```
Control Node (this code)
    │
    └── SSH (root) ──┬── Host 0 ──── collector modules
                     ├── Host 1
                     └── Host N
```

### Core Modules

- **`collector/`** - Data collection from remote hosts via SSH
  - `interfaces.py` - Network interface info (MAC, IP, MTU, speed, driver)
  - `link_state.py` - Physical link state (carrier, operstate, statistics)
  - `neighbor.py` - Neighbor discovery (LLDP, ARP, active probing)

- **`inventory/hosts.yaml`** - Host list and SSH configuration
  - Supports key or password auth
  - Interface exclusion patterns (regex)

### Data Flow

1. SSH client connects to each host
2. Collectors execute Linux commands (`ip`, `ethtool`, `lldpcli`, `arping`)
3. Output parsed into dataclasses (`InterfaceInfo`, `LinkState`, `NeighborInfo`)
4. Topology engine (not yet implemented) fuses data from all hosts

### Key Data Structures

- `InterfaceInfo` - MAC, state, MTU, speed, duplex, driver, IPs
- `LinkState` - carrier, operstate, link_detected, stats (rx/tx bytes/packets/errors)
- `NeighborInfo` - discovery_method (lldp/arp/probe), remote MAC/host/interface/IP

## Dependencies

All collectors require an SSH client object with an `execute(cmd: str) -> str` method. Linux commands used on remote hosts:
- `ip link show`, `ip addr show`, `ip neigh show`
- `ethtool`, `ethtool -i`
- `/sys/class/net/*/` filesystem reads
- `lldpcli show neighbors` (optional)
- `arping` (for active probing)

## Build & Test

```bash
# Install in development mode
pip install -e .

# Install dependencies
pip install -r requirements.txt

# Run all tests
pytest

# Run a single test file
pytest tests/test_interfaces.py

# Run with coverage
pytest --cov=collector
```

## Configuration

Edit `inventory/hosts.yaml` to configure:
- SSH connection settings (port, username, auth type, key file, timeout)
- Host list with IP addresses
- Interface exclusion patterns (e.g., `^lo$`, `^docker.*`, `^veth.*`)
