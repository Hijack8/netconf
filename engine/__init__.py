"""
Engine module - Topology inference and validation

Contains:
- infer: Topology inference from collected data
- validate: Topology validation and health checks
"""

from .infer import TopologyInferrer, Topology, Link, Port
from .validate import TopologyValidator, ValidationIssue

__all__ = [
    'TopologyInferrer',
    'Topology',
    'Link',
    'Port',
    'TopologyValidator',
    'ValidationIssue',
]
