# ============================================================
# REFERENCE
#   仿造来源：openEMS octave 接口 WriteOpenEMS.m / InitFDTD.m /
#             SetBoundaryCond.m + 官方 python API 的 CSX 序列化样例
#             （tests/fixtures/openems/dipole_csx.xml，由 Write2XML 生成）
#   关键设计点：
#     - 完整 <openEMS> 文档 = <FDTD> 段（时间步/激励/边界）+
#       <ContinuousStructure>（网格/材料/端口原语），openEMS.exe 直接可跑
#     - LumpedPort 按官方展开为 4 个属性：LumpedElement(R) +
#       Excitation(Excite=-1·方向) + ProbeBox(ut, Weight=-1) +
#       ProbeBox(it, Type=1, Weight=+1)；电压探针沿端口方向，电流探针
#       位于端口中点的横截面
#     - 网格线必须显式给出（openEMS.exe 不做自动 smooth）——
#       grade_lines 从细网格向外几何级数过渡（ratio 1.4，上限 λ/10），
#       与官方 SmoothMeshLines 输出同构
# ============================================================

"""
openEMS simulation-XML writer.

Produces a complete, self-contained simulation file for ``openEMS.exe``
(the same document the octave interface generates via WriteOpenEMS).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


def grade_lines(
    start: float, end: float, first_step: float, max_step: float,
    ratio: float = 1.4,
) -> list[float]:
    """Geometrically graded mesh lines from `start` out to `end`.

    Steps grow by `ratio` per line, capped at `max_step`; the final line
    lands exactly on `end`. Direction follows the sign of end-start.
    """
    if end == start:
        return [start]
    sign = 1.0 if end > start else -1.0
    lines: list[float] = []
    pos = start
    step = first_step
    while (end - pos) * sign > max_step:
        pos += sign * step
        if (end - pos) * sign <= step * 0.5:
            break
        lines.append(pos)
        step = min(step * ratio, max_step)
    lines.append(end)
    return lines


def _fill_gap(
    a: float, b: float, step_a: float, step_b: float,
    max_step: float, ratio: float,
) -> list[float]:
    """Interior lines for the interval (a, b), graded from both ends.

    Steps start at `step_a`/`step_b`, grow by `ratio` toward the middle
    (capped at `max_step`) until the two fronts meet. A runt middle cell
    (< half the local step) is absorbed into its neighbor.
    """
    la, lb = [a], [b]
    sa = min(step_a, max_step)
    sb = min(step_b, max_step)
    while lb[-1] - la[-1] > max(sa, sb):
        if sa <= sb:
            la.append(la[-1] + sa)
            sa = min(sa * ratio, max_step)
        else:
            lb.append(lb[-1] - sb)
            sb = min(sb * ratio, max_step)
    if lb[-1] - la[-1] < 0.5 * min(sa, sb):
        if len(la) > 1 and (len(lb) == 1 or la[-1] - la[-2] >= lb[-2] - lb[-1]):
            la.pop()
        elif len(lb) > 1:
            lb.pop()
    return la[1:] + lb[:0:-1]


def smooth_lines(
    lines: list[float], max_step: float, ratio: float = 1.4,
) -> list[float]:
    """Fill gaps between fixed mesh lines with smoothly graded lines.

    Simplified port of the official ``SmoothMeshLines``: every input line
    is kept; each oversized gap is subdivided growing geometrically from
    both of its ends, seeded with the size of the neighboring interval so
    fine regions transition gradually into coarse ones.
    """
    pts = sorted(set(lines))
    if len(pts) < 2:
        return pts
    gaps = [b - a for a, b in zip(pts, pts[1:], strict=False)]
    out: list[float] = [pts[0]]
    for i, (a, b) in enumerate(zip(pts, pts[1:], strict=False)):
        gap = gaps[i]
        if gap > max_step * (1 + 1e-9):
            step_a = gaps[i - 1] if i > 0 else max_step
            step_b = gaps[i + 1] if i + 1 < len(gaps) else max_step
            out.extend(_fill_gap(a, b, step_a, step_b, max_step, ratio))
        out.append(b)
    return out


@dataclass
class LumpedPort:
    """Axis-aligned lumped port (resistor + excitation + u/i probes)."""

    number: int
    resistance: float
    start: tuple[float, float, float]
    stop: tuple[float, float, float]
    direction: int  # 0=x, 1=y, 2=z
    excite: bool = True


@dataclass
class OpenEMSXmlWriter:
    """Builds the full openEMS simulation document."""

    f0: float
    fc: float
    number_of_timesteps: int = 40000
    end_criteria: float = 1e-4
    boundary: tuple[str, str, str, str, str, str] = ("MUR",) * 6
    delta_unit: float = 1.0  # coordinates in meters

    x_lines: list[float] = field(default_factory=list)
    y_lines: list[float] = field(default_factory=list)
    z_lines: list[float] = field(default_factory=list)

    _property_id: int = 0

    def __post_init__(self) -> None:
        self._root = ET.Element("openEMS")
        fdtd = ET.SubElement(
            self._root, "FDTD",
            NumberOfTimesteps=str(self.number_of_timesteps),
            endCriteria=f"{self.end_criteria:g}",
            f_max=f"{self.f0 + self.fc:g}",
        )
        ET.SubElement(fdtd, "Excitation", Type="0",
                      f0=f"{self.f0:g}", fc=f"{self.fc:g}")
        bc = dict(zip(
            ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"),
            self.boundary, strict=True,
        ))
        ET.SubElement(fdtd, "BoundaryCond", bc)
        self._csx = ET.SubElement(self._root, "ContinuousStructure",
                                  CoordSystem="0")
        self._properties = ET.Element("Properties")  # attached in to_bytes

    def _next_id(self) -> str:
        pid = self._property_id
        self._property_id += 1
        return str(pid)

    @staticmethod
    def _add_box(parent: ET.Element, priority: int,
                 p1: tuple[float, float, float],
                 p2: tuple[float, float, float]) -> None:
        # %.12g — the SAME format the grid lines use, so a coordinate
        # that equals a mesh line as a double parses back identical and
        # degenerate boxes (ports, sheets) snap onto their line exactly.
        # (%.6e once truncated an irrational feed position 7.6e-11 m off
        # its line → openEMS found no excitation edges → zero energy.)
        prims = parent.find("Primitives")
        if prims is None:
            prims = ET.SubElement(parent, "Primitives")
        box = ET.SubElement(prims, "Box", Priority=str(priority))
        ET.SubElement(box, "P1", X=f"{p1[0]:.12g}", Y=f"{p1[1]:.12g}", Z=f"{p1[2]:.12g}")
        ET.SubElement(box, "P2", X=f"{p2[0]:.12g}", Y=f"{p2[1]:.12g}", Z=f"{p2[2]:.12g}")

    def add_metal_box(
        self, name: str,
        p1: tuple[float, float, float], p2: tuple[float, float, float],
        priority: int = 10,
    ) -> None:
        metal = ET.SubElement(self._properties, "Metal",
                              ID=self._next_id(), Name=name)
        self._add_box(metal, priority, p1, p2)

    def add_metal_cylinder(
        self,
        name: str,
        p1: tuple[float, float, float],
        p2: tuple[float, float, float],
        radius: float,
        priority: int = 10,
    ) -> None:
        """Add an arbitrary-axis finite-volume PEC cylinder."""

        if radius <= 0.0:
            raise ValueError("metal cylinder radius must be positive")
        metal = ET.SubElement(
            self._properties, "Metal", ID=self._next_id(), Name=name
        )
        primitives = ET.SubElement(metal, "Primitives")
        cylinder = ET.SubElement(
            primitives,
            "Cylinder",
            Priority=str(priority),
            Radius=f"{radius:.12g}",
        )
        ET.SubElement(
            cylinder,
            "P1",
            X=f"{p1[0]:.12g}",
            Y=f"{p1[1]:.12g}",
            Z=f"{p1[2]:.12g}",
        )
        ET.SubElement(
            cylinder,
            "P2",
            X=f"{p2[0]:.12g}",
            Y=f"{p2[1]:.12g}",
            Z=f"{p2[2]:.12g}",
        )

    def add_metal_wire(
        self,
        name: str,
        points: list[tuple[float, float, float]],
        radius: float,
        priority: int = 10,
    ) -> None:
        """Add a native CSXCAD finite-radius polygonal Wire primitive."""

        if len(points) < 2:
            raise ValueError("metal wire requires at least two points")
        if radius <= 0.0:
            raise ValueError("metal wire radius must be positive")
        metal = ET.SubElement(
            self._properties,
            "Metal",
            ID=self._next_id(),
            Name=name,
        )
        primitives = ET.SubElement(metal, "Primitives")
        wire = ET.SubElement(
            primitives,
            "Wire",
            Priority=str(priority),
            WireRadius=f"{radius:.12g}",
        )
        for point in points:
            ET.SubElement(
                wire,
                "Vertex",
                X=f"{point[0]:.12g}",
                Y=f"{point[1]:.12g}",
                Z=f"{point[2]:.12g}",
            )

    def add_material_box(
        self, name: str,
        p1: tuple[float, float, float], p2: tuple[float, float, float],
        epsilon: float = 1.0, kappa: float = 0.0,
        priority: int = 0,
    ) -> None:
        """Isotropic dielectric box (e.g. an antenna substrate)."""
        mat = ET.SubElement(self._properties, "Material",
                            ID=self._next_id(), Name=name, Isotropy="1")
        ET.SubElement(mat, "Property",
                      Epsilon=f"{epsilon:g}", Mue="1",
                      Kappa=f"{kappa:g}", Sigma="0")
        self._add_box(mat, priority, p1, p2)

    def add_lorentz_material_box(
        self, name: str,
        p1: tuple[float, float, float], p2: tuple[float, float, float],
        epsilon: float, kappa: float = 0.0,
        plasma_freq: float = 0.0, relax_time: float = 0.0,
        pole_freq: float = 0.0,
        priority: int = 0,
    ) -> None:
        """Drude/Lorentz dispersive dielectric box.

        eps_r(f) = epsilon·(1 − f_p²/(f² − f_pole² − j·f/(2π·τ)));
        pole_freq=0 gives the plain Drude model. Frequencies are plain
        Hz and τ is seconds — the engine applies 2π itself
        (operator_ext_lorentzmaterial.cpp, v0.0.36). Attribute names
        follow CSPropLorentzMaterial::ReadFromXML (first order = _1).
        """
        mat = ET.SubElement(self._properties, "LorentzMaterial",
                            ID=self._next_id(), Name=name, Isotropy="1")
        attrs = {
            "Epsilon": f"{epsilon:g}", "Mue": "1",
            "Kappa": f"{kappa:g}", "Sigma": "0",
            "EpsilonPlasmaFrequency_1": f"{plasma_freq:g}",
        }
        if relax_time > 0:
            attrs["EpsilonRelaxTime_1"] = f"{relax_time:g}"
        if pole_freq > 0:
            attrs["EpsilonLorPoleFrequency_1"] = f"{pole_freq:g}"
        ET.SubElement(mat, "Property", attrs)
        self._add_box(mat, priority, p1, p2)

    def add_lumped_port(self, port: LumpedPort) -> None:
        """Expand a lumped port exactly like the official AddLumpedPort."""
        n = port.number
        lumped = ET.SubElement(
            self._properties, "LumpedElement",
            ID=self._next_id(), Name=f"port_resist_{n}",
            Direction=str(port.direction), Caps="1",
            R=f"{port.resistance:.6e}",
        )
        self._add_box(lumped, 5, port.start, port.stop)

        if port.excite:
            vec = [0.0, 0.0, 0.0]
            vec[port.direction] = -1.0  # E = -V/d along the port axis
            exc = ET.SubElement(
                self._properties, "Excitation",
                ID=self._next_id(), Name=f"port_excite_{n}",
                Number="0", Type="0",
                Excite=",".join(f"{v:g}" for v in vec),
            )
            self._add_box(exc, 5, port.start, port.stop)
            ET.SubElement(exc, "Weight", X="1", Y="1", Z="1")

        midpoint = tuple(
            (start + stop) / 2.0
            for start, stop in zip(port.start, port.stop, strict=True)
        )
        voltage_start = list(midpoint)
        voltage_stop = list(midpoint)
        voltage_start[port.direction] = port.start[port.direction]
        voltage_stop[port.direction] = port.stop[port.direction]
        ut = ET.SubElement(
            self._properties, "ProbeBox",
            ID=self._next_id(), Name=f"port_ut_{n}",
            Number="0", Type="0", Weight="-1", NormDir="-1",
        )
        self._add_box(
            ut,
            0,
            (voltage_start[0], voltage_start[1], voltage_start[2]),
            (voltage_stop[0], voltage_stop[1], voltage_stop[2]),
        )

        current_start = list(port.start)
        current_stop = list(port.stop)
        current_start[port.direction] = midpoint[port.direction]
        current_stop[port.direction] = midpoint[port.direction]
        it = ET.SubElement(
            self._properties, "ProbeBox",
            ID=self._next_id(), Name=f"port_it_{n}",
            Number="0", Type="1", Weight="1", NormDir=str(port.direction),
        )
        self._add_box(
            it,
            0,
            (current_start[0], current_start[1], current_start[2]),
            (current_stop[0], current_stop[1], current_stop[2]),
        )

    def add_nf2ff_box(self, name: str = "nf2ff") -> None:
        """Add the E/H recording boxes for the NF2FF transform.

        Six-face dump pair exactly like the official CreateNF2FFBox
        (time-domain Et/Ht, HDF5 files ``<name>_E_0..5.h5``): the box
        sits 2 cells inside every boundary (the official default for
        MUR). Must be called after the mesh lines are final.
        """
        bounds: list[tuple[float, float]] = []
        for lines in (self.x_lines, self.y_lines, self.z_lines):
            uniq = sorted(set(lines))
            if len(uniq) < 6:
                raise ValueError("grid too small for an NF2FF recording box")
            bounds.append((uniq[2], uniq[-3]))
        start = (bounds[0][0], bounds[1][0], bounds[2][0])
        stop = (bounds[0][1], bounds[1][1], bounds[2][1])

        for suffix, dump_type in (("E", "0"), ("H", "1")):
            dump = ET.SubElement(
                self._properties, "DumpBox",
                ID=self._next_id(), Name=f"{name}_{suffix}",
                Number="0", Type="0", Weight="1", NormDir="-1",
                StartTime="0", StopTime="0",
                DumpType=dump_type, DumpMode="1", FileType="1",
                MultiGridLevel="0",
            )
            for ny in range(3):
                lo = list(start)
                hi = list(stop)
                hi[ny] = lo[ny]
                self._add_box(dump, 0, (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2]))
                lo = list(start)
                hi = list(stop)
                lo[ny] = hi[ny]
                self._add_box(dump, 0, (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2]))

    def to_bytes(self) -> bytes:
        grid = ET.Element("RectilinearGrid",
                          DeltaUnit=f"{self.delta_unit:g}", CoordSystem="0")
        for tag, lines in (("XLines", self.x_lines),
                           ("YLines", self.y_lines),
                           ("ZLines", self.z_lines)):
            uniq = sorted(set(lines))
            el = ET.SubElement(grid, tag, Qty=str(len(uniq)))
            el.text = ",".join(f"{v:.12g}" for v in uniq)

        # assemble in canonical order: grid, background, properties
        for child in list(self._csx):
            self._csx.remove(child)
        self._csx.append(grid)
        ET.SubElement(self._csx, "BackgroundMaterial",
                      Epsilon="1", Mue="1", Kappa="0", Sigma="0")
        self._csx.append(self._properties)

        ET.indent(self._root)
        return bytes(ET.tostring(self._root, encoding="utf-8",
                                 xml_declaration=True))
