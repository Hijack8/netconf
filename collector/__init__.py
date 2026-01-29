"""
Collector module - 网络信息采集模块

包含：
- interfaces: 网口信息采集
- link_state: 链路状态采集
- neighbor: 邻居发现
"""

from .interfaces import InterfaceCollector
from .link_state import LinkStateCollector
from .neighbor import NeighborDiscovery

__all__ = ['InterfaceCollector', 'LinkStateCollector', 'NeighborDiscovery']
