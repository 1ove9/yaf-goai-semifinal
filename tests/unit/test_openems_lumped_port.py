"""Pure XML tests for the official openEMS lumped-port probe geometry."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET

import pytest

from yaf_solvers.openems_adapter.xml_writer import (
    LumpedPort,
    OpenEMSXmlWriter,
)

LINE_PORT_XML_SHA256 = "cdf8e5b6aca418878bd043d6a164ee3a7fc78635380d355783bbe08ee1952b0d"
ROD_RADIUS_M = 5e-5


class _LegacyProbeWriter(OpenEMSXmlWriter):
    """Frozen pre-repair probe geometry used only as a byte oracle."""

    def add_lumped_port(self, port: LumpedPort) -> None:
        n = port.number
        lumped = ET.SubElement(
            self._properties,
            "LumpedElement",
            ID=self._next_id(),
            Name=f"port_resist_{n}",
            Direction=str(port.direction),
            Caps="1",
            R=f"{port.resistance:.6e}",
        )
        self._add_box(lumped, 5, port.start, port.stop)
        if port.excite:
            vector = [0.0, 0.0, 0.0]
            vector[port.direction] = -1.0
            excitation = ET.SubElement(
                self._properties,
                "Excitation",
                ID=self._next_id(),
                Name=f"port_excite_{n}",
                Number="0",
                Type="0",
                Excite=",".join(f"{value:g}" for value in vector),
            )
            self._add_box(excitation, 5, port.start, port.stop)
            ET.SubElement(excitation, "Weight", X="1", Y="1", Z="1")
        voltage = ET.SubElement(
            self._properties,
            "ProbeBox",
            ID=self._next_id(),
            Name=f"port_ut_{n}",
            Number="0",
            Type="0",
            Weight="-1",
            NormDir="-1",
        )
        self._add_box(voltage, 0, port.start, port.stop)
        midpoint = (
            (port.start[0] + port.stop[0]) / 2.0,
            (port.start[1] + port.stop[1]) / 2.0,
            (port.start[2] + port.stop[2]) / 2.0,
        )
        current = ET.SubElement(
            self._properties,
            "ProbeBox",
            ID=self._next_id(),
            Name=f"port_it_{n}",
            Number="0",
            Type="1",
            Weight="1",
            NormDir=str(port.direction),
        )
        self._add_box(current, 0, midpoint, midpoint)


def _writer() -> OpenEMSXmlWriter:
    writer = OpenEMSXmlWriter(
        f0=5.8e9,
        fc=0.7e9,
        number_of_timesteps=10,
    )
    writer.x_lines = [-1.0, 0.0, 1.0]
    writer.y_lines = [-1.0, 0.0, 1.0]
    writer.z_lines = [-1.0, 0.0, 1.0]
    return writer


def _legacy_xml_bytes(port: LumpedPort) -> bytes:
    writer = _LegacyProbeWriter(f0=5.8e9, fc=0.7e9, number_of_timesteps=10)
    writer.x_lines = writer.y_lines = writer.z_lines = [-1.0, 0.0, 1.0]
    writer.add_lumped_port(port)
    return writer.to_bytes()


def _xml_bytes(port: LumpedPort) -> bytes:
    writer = _writer()
    writer.add_lumped_port(port)
    return writer.to_bytes()


def _root(port: LumpedPort) -> ET.Element:
    return ET.fromstring(_xml_bytes(port))


def _point(element: ET.Element) -> tuple[float, float, float]:
    return (
        float(element.attrib["X"]),
        float(element.attrib["Y"]),
        float(element.attrib["Z"]),
    )


def _box_bounds(
    root: ET.Element,
    xpath: str,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    box = root.find(xpath)
    assert box is not None
    p1 = box.find("P1")
    p2 = box.find("P2")
    assert p1 is not None and p2 is not None
    return _point(p1), _point(p2)


def _official_probe_bounds(
    port: LumpedPort,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    midpoint = tuple(
        (start + stop) / 2.0 for start, stop in zip(port.start, port.stop, strict=True)
    )
    voltage_start = list(midpoint)
    voltage_stop = list(midpoint)
    voltage_start[port.direction] = port.start[port.direction]
    voltage_stop[port.direction] = port.stop[port.direction]
    current_start = list(port.start)
    current_stop = list(port.stop)
    current_start[port.direction] = midpoint[port.direction]
    current_stop[port.direction] = midpoint[port.direction]
    return (
        (voltage_start[0], voltage_start[1], voltage_start[2]),
        (voltage_stop[0], voltage_stop[1], voltage_stop[2]),
        (current_start[0], current_start[1], current_start[2]),
        (current_stop[0], current_stop[1], current_stop[2]),
    )


def _assert_bounds_equal(
    actual: tuple[tuple[float, float, float], tuple[float, float, float]],
    expected: tuple[tuple[float, float, float], tuple[float, float, float]],
) -> None:
    assert actual[0] == pytest.approx(expected[0], rel=0.0, abs=1e-15)
    assert actual[1] == pytest.approx(expected[1], rel=0.0, abs=1e-15)


@pytest.mark.parametrize("direction", [0, 1, 2])
def test_finite_area_probe_bounds_follow_official_formula(direction: int) -> None:
    port = LumpedPort(
        number=7,
        resistance=73.0,
        start=(-0.00031, -0.00022, -0.00013),
        stop=(0.00037, 0.00026, 0.00019),
        direction=direction,
    )
    root = _root(port)
    expected_u_start, expected_u_stop, expected_i_start, expected_i_stop = _official_probe_bounds(
        port
    )
    _assert_bounds_equal(
        _box_bounds(root, ".//ProbeBox[@Name='port_ut_7']/Primitives/Box"),
        (expected_u_start, expected_u_stop),
    )
    _assert_bounds_equal(
        _box_bounds(root, ".//ProbeBox[@Name='port_it_7']/Primitives/Box"),
        (expected_i_start, expected_i_stop),
    )


def test_rod_y_port_has_exact_frozen_probe_bounds() -> None:
    port = LumpedPort(
        number=1,
        resistance=50.0,
        start=(-ROD_RADIUS_M, -0.0003, -ROD_RADIUS_M),
        stop=(ROD_RADIUS_M, 0.0003, ROD_RADIUS_M),
        direction=1,
    )
    root = _root(port)
    assert _box_bounds(
        root,
        ".//ProbeBox[@Name='port_ut_1']/Primitives/Box",
    ) == ((0.0, -0.0003, 0.0), (0.0, 0.0003, 0.0))
    assert _box_bounds(
        root,
        ".//ProbeBox[@Name='port_it_1']/Primitives/Box",
    ) == (
        (-ROD_RADIUS_M, 0.0, -ROD_RADIUS_M),
        (ROD_RADIUS_M, 0.0, ROD_RADIUS_M),
    )


def test_finite_area_port_keeps_lumped_element_and_excitation_unchanged() -> None:
    port = LumpedPort(
        number=3,
        resistance=50.0,
        start=(-0.00005, -0.0003, -0.00005),
        stop=(0.00005, 0.0003, 0.00005),
        direction=1,
    )
    root = _root(port)
    lumped = root.find(".//LumpedElement[@Name='port_resist_3']")
    excitation = root.find(".//Excitation[@Name='port_excite_3']")
    assert lumped is not None and excitation is not None
    assert lumped.attrib == {
        "ID": "0",
        "Name": "port_resist_3",
        "Direction": "1",
        "Caps": "1",
        "R": "5.000000e+01",
    }
    assert excitation.attrib == {
        "ID": "1",
        "Name": "port_excite_3",
        "Number": "0",
        "Type": "0",
        "Excite": "0,-1,0",
    }
    assert _box_bounds(
        root,
        ".//LumpedElement[@Name='port_resist_3']/Primitives/Box",
    ) == (port.start, port.stop)
    assert _box_bounds(
        root,
        ".//Excitation[@Name='port_excite_3']/Primitives/Box",
    ) == (port.start, port.stop)
    lumped_box = lumped.find("./Primitives/Box")
    excitation_box = excitation.find("./Primitives/Box")
    weight = excitation.find("Weight")
    assert lumped_box is not None and lumped_box.attrib == {"Priority": "5"}
    assert excitation_box is not None and excitation_box.attrib == {"Priority": "5"}
    assert weight is not None and weight.attrib == {"X": "1", "Y": "1", "Z": "1"}


@pytest.mark.parametrize(
    ("direction", "start", "stop"),
    [
        (0, (-0.0003, 0.0, 0.0), (0.0003, 0.0, 0.0)),
        (1, (0.0, -0.0003, 0.0), (0.0, 0.0003, 0.0)),
        (2, (0.0, 0.0, -0.0003), (0.0, 0.0, 0.0003)),
    ],
)
def test_line_port_degenerates_to_legacy_probe_bounds(
    direction: int,
    start: tuple[float, float, float],
    stop: tuple[float, float, float],
) -> None:
    port = LumpedPort(1, 50.0, start, stop, direction)
    root = _root(port)
    midpoint = tuple((left + right) / 2.0 for left, right in zip(start, stop, strict=True))
    assert _box_bounds(
        root,
        ".//ProbeBox[@Name='port_ut_1']/Primitives/Box",
    ) == (start, stop)
    assert _box_bounds(
        root,
        ".//ProbeBox[@Name='port_it_1']/Primitives/Box",
    ) == (midpoint, midpoint)


def test_frozen_y_line_port_xml_is_byte_identical() -> None:
    xml_bytes = _xml_bytes(
        LumpedPort(
            1,
            50.0,
            start=(0.0, -0.0003, 0.0),
            stop=(0.0, 0.0003, 0.0),
            direction=1,
        )
    )
    assert hashlib.sha256(xml_bytes).hexdigest() == LINE_PORT_XML_SHA256


@pytest.mark.parametrize(
    ("direction", "start", "stop"),
    [
        (0, (-0.0003, 0.0, 0.0), (0.0003, 0.0, 0.0)),
        (1, (0.0, -0.0003, 0.0), (0.0, 0.0003, 0.0)),
        (2, (0.0, 0.0, -0.0003), (0.0, 0.0, 0.0003)),
    ],
)
def test_line_port_xml_remains_byte_identical_to_legacy(
    direction: int,
    start: tuple[float, float, float],
    stop: tuple[float, float, float],
) -> None:
    port = LumpedPort(1, 50.0, start, stop, direction)
    assert _xml_bytes(port) == _legacy_xml_bytes(port)
