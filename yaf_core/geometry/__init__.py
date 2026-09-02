"""Geometry APIs with optional heavy implementations loaded on demand."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yaf_core.geometry.implicit import SIRENGeometry
    from yaf_core.geometry.kernel import GeometryKernel
    from yaf_core.geometry.parametric import ParametricGenerator
    from yaf_core.geometry.topology import TopologyField

__all__ = ["GeometryKernel", "ParametricGenerator", "SIRENGeometry", "TopologyField"]

_LAZY_IMPORTS = {
    "GeometryKernel": ("yaf_core.geometry.kernel", "GeometryKernel"),
    "ParametricGenerator": ("yaf_core.geometry.parametric", "ParametricGenerator"),
    "SIRENGeometry": ("yaf_core.geometry.implicit", "SIRENGeometry"),
    "TopologyField": ("yaf_core.geometry.topology", "TopologyField"),
}


def __getattr__(name: str) -> Any:
    """Load optional geometry backends only when their public API is used."""
    target = _LAZY_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
