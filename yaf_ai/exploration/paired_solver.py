"""Real NEC2 callable for the frozen paired-state target bands."""

from __future__ import annotations

import math
from typing import Any

from yaf_ai.exploration.paired_meander import (
    STATE_A_FREQUENCIES_HZ,
    STATE_B_FREQUENCIES_HZ,
    HardwareSpec,
    PairedMeanderError,
    SearchCurve,
    StateControl,
    StateLabel,
    build_state_geometry,
    state_geometry_hash,
)
from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter

NEC2_SEGMENTS_PER_WAVELENGTH = 20


class PairedSolverError(PairedMeanderError):
    """Raised before evidence can contain a non-frozen paired solve."""


def _integer_feature(features: dict[str, Any], name: str) -> int:
    value = features.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PairedSolverError(f"geometry design feature {name!r} is missing or not integer")
    return value


def _reconstruct_identity(
    geometry: Geometry,
    state_label: StateLabel,
) -> tuple[HardwareSpec, StateControl]:
    raw_features = geometry.metadata.get("design_features")
    if not isinstance(raw_features, dict):
        raise PairedSolverError("geometry design_features metadata is missing")
    features = dict(raw_features)
    hardware = HardwareSpec(
        turn_count=_integer_feature(features, "turn_count"),
        feed_gap_ratio_ppm=_integer_feature(features, "feed_gap_ratio_ppm"),
        terminal_ratio_ppm=_integer_feature(features, "terminal_ratio_ppm"),
    )
    state = StateControl(
        state=state_label,
        total_wire_length_um=_integer_feature(features, "total_wire_length_um"),
        span_ratio_ppm=_integer_feature(features, "span_ratio_ppm"),
    )
    rebuilt = build_state_geometry(hardware, state)
    rebuilt_hash = state_geometry_hash(hardware, state, rebuilt)
    supplied_hash = state_geometry_hash(hardware, state, geometry)
    if rebuilt_hash != supplied_hash:
        raise PairedSolverError("supplied geometry differs from its frozen quantized identity")
    return hardware, state


def _expected_frequencies(state: StateLabel) -> tuple[float, ...]:
    return STATE_A_FREQUENCIES_HZ if state == "A" else STATE_B_FREQUENCIES_HZ


class PairedNEC2Solver:
    """Validate one paired endpoint and return one real target-band NEC2 curve."""

    def __init__(self, adapter: NEC2Adapter | None = None) -> None:
        self._adapter = NEC2Adapter() if adapter is None else adapter

    async def __call__(
        self,
        geometry: Geometry,
        state: StateLabel,
        frequency_hz: tuple[float, ...],
    ) -> SearchCurve:
        expected = _expected_frequencies(state)
        if frequency_hz != expected:
            raise PairedSolverError(f"state {state} frequency table changed")
        hardware, _state = _reconstruct_identity(geometry, state)
        expected_radius = hardware.wire_radius_um * 1e-6
        radius = geometry.metadata.get("wire_radius_m")
        if not isinstance(radius, (int, float)) or isinstance(radius, bool):
            raise PairedSolverError("geometry wire_radius_m metadata is missing")
        if float(radius) != expected_radius:
            raise PairedSolverError("geometry wire radius differs from HardwareSpec")

        spec = SimulationSpec(
            name=f"semifinal-paired-{state.lower()}",
            frequency_range=(expected[0], expected[-1]),
            frequency_points=len(expected),
            solver_settings={
                "nec2_segments_per_wavelength": NEC2_SEGMENTS_PER_WAVELENGTH,
            },
            far_field_request=None,
        )
        mesh = await self._adapter.mesh(geometry, spec)
        mesh_radius = mesh.metadata.get("wire_radius_m")
        if not isinstance(mesh_radius, (int, float)) or isinstance(mesh_radius, bool):
            raise PairedSolverError("NEC2 mesh silently lost wire_radius_m")
        if float(mesh_radius) != expected_radius:
            raise PairedSolverError("NEC2 mesh wire radius differs from HardwareSpec")
        result = await self._adapter.solve(mesh, spec)
        solver_mode = str(result.solver_metadata.get("solver_mode", ""))
        if solver_mode != "subprocess":
            raise PairedSolverError(f"paired NEC2 requires subprocess mode, got {solver_mode!r}")
        if result.status != "success" or result.s_params is None:
            raise PairedSolverError("real NEC2 returned no successful S-parameter result")
        actual_frequencies = tuple(float(value) for value in result.s_params.frequency)
        if len(actual_frequencies) != len(expected) or any(
            not math.isclose(actual, frozen, rel_tol=0.0, abs_tol=0.5)
            for actual, frozen in zip(actual_frequencies, expected, strict=True)
        ):
            raise PairedSolverError("NEC2 output frequency table changed")
        if len(result.s_params.s_matrix) != len(expected):
            raise PairedSolverError("NEC2 S-parameter row count changed")
        s11_db: list[float] = []
        for matrix in result.s_params.s_matrix:
            try:
                magnitude = abs(complex(matrix[0][0]))
            except (IndexError, TypeError, ValueError) as error:
                raise PairedSolverError("NEC2 returned malformed S11 data") from error
            s11_db.append(-300.0 if magnitude == 0.0 else 20.0 * math.log10(magnitude))
        return SearchCurve(
            solver_name="nec2",
            solver_mode="subprocess",
            frequency_hz=expected,
            s11_db=tuple(s11_db),
            realized_gain_dbi=None,
        )
