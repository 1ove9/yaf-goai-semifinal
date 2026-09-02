"""Known-answer physics tests + solver honesty contract.

These tests pin solver behavior to values from the literature rather than
"status == success" structural assertions (see docs/HONEST_STATUS.md §5).

- Half-wave dipole input impedance: 73.1 + j42.5 Ω
  (Balanis, Antenna Theory 4th ed., §8.4, induced EMF method)
- Analytical fallback results MUST be labeled solver_mode="fallback_analytical"
  and carry a warning.
- YAF_NO_FALLBACK=1 must turn a missing solver into SolverUnavailableError
  instead of silently degrading.
"""

from __future__ import annotations

import pytest

from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.base import FALLBACK_WARNING, SolverUnavailableError
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

C0 = 299792458.0


def _dipole_geometry(length: float) -> Geometry:
    # A single 2-node wire edge — NEC2 is a wire-grid solver and now
    # rejects surface meshes instead of mangling them into bogus wires
    return Geometry(
        name="dipole",
        representation="mesh",
        vertices=[
            [0.0, 0.0, -length / 2],
            [0.0, 0.0, length / 2],
        ],
        faces=[[0, 1]],
    )


def _ribbon_geometry(length: float) -> Geometry:
    # Thin triangulated ribbon — a *surface* geometry for the openEMS
    # (FDTD volume solver) tests; NEC2 would rightly reject it
    return Geometry(
        name="dipole-ribbon",
        representation="mesh",
        vertices=[
            [-length / 2, 0.0, 0.0],
            [length / 2, 0.0, 0.0],
            [-length / 2, 0.001, 0.0],
            [length / 2, 0.001, 0.0],
        ],
        faces=[[0, 1, 2], [1, 2, 3]],
    )


def _spec() -> SimulationSpec:
    return SimulationSpec(
        name="known-answer sweep",
        frequency_range=(2.4e9, 2.5e9),
        frequency_points=11,
    )


class TestDipoleKnownAnswers:
    """Balanis §8.4: thin half-wave dipole, induced EMF method."""

    def test_halfwave_impedance_matches_textbook(self) -> None:
        f = 2.45e9
        wavelength = C0 / f
        z = NEC2Adapter.dipole_impedance_induced_emf(f, wavelength / 2)
        assert z.real == pytest.approx(73.1, rel=0.02)
        assert z.imag == pytest.approx(42.5, rel=0.02)

    def test_short_dipole_is_capacitive(self) -> None:
        """A dipole well below resonance must show negative (capacitive) reactance."""
        f = 2.45e9
        wavelength = C0 / f
        z = NEC2Adapter.dipole_impedance_induced_emf(f, 0.3 * wavelength)
        assert z.imag < 0
        assert 0 < z.real < 73.1

    def test_resistance_increases_with_length_toward_resonance(self) -> None:
        f = 2.45e9
        wavelength = C0 / f
        r_short = NEC2Adapter.dipole_impedance_induced_emf(f, 0.35 * wavelength).real
        r_half = NEC2Adapter.dipole_impedance_induced_emf(f, 0.5 * wavelength).real
        assert r_short < r_half


class TestSolverHonesty:
    """Fallback results must be labeled; strict mode must refuse to fake physics."""

    async def test_nec2_fallback_is_labeled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("YAF_NO_FALLBACK", raising=False)
        adapter = NEC2Adapter(executable="nec2c-definitely-not-installed")
        spec = _spec()
        mesh = await adapter.mesh(_dipole_geometry(C0 / 2.45e9 / 2), spec)
        result = await adapter.solve(mesh, spec)
        assert result.solver_metadata["solver_mode"] == "fallback_analytical"
        assert result.solver_metadata["warning"] == FALLBACK_WARNING

    async def test_nec2_no_fallback_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YAF_NO_FALLBACK", "1")
        adapter = NEC2Adapter(executable="nec2c-definitely-not-installed")
        spec = _spec()
        mesh = await adapter.mesh(_dipole_geometry(C0 / 2.45e9 / 2), spec)
        with pytest.raises(SolverUnavailableError):
            await adapter.solve(mesh, spec)

    async def test_openems_fallback_is_labeled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("YAF_NO_FALLBACK", raising=False)
        adapter = OpenEMSAdapter()
        # force the no-solver situation even on machines that have one
        adapter._openems_available = False
        monkeypatch.setattr(adapter, "_resolve_executable", lambda: None)
        spec = _spec()
        mesh = await adapter.mesh(_ribbon_geometry(C0 / 2.45e9 / 2), spec)
        result = await adapter.solve(mesh, spec)
        assert result.solver_metadata["solver_mode"] == "fallback_analytical"
        assert "warning" in result.solver_metadata

    async def test_openems_no_fallback_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("YAF_NO_FALLBACK", "1")
        adapter = OpenEMSAdapter()
        adapter._openems_available = False
        monkeypatch.setattr(adapter, "_resolve_executable", lambda: None)
        spec = _spec()
        mesh = await adapter.mesh(_ribbon_geometry(C0 / 2.45e9 / 2), spec)
        with pytest.raises(SolverUnavailableError):
            await adapter.solve(mesh, spec)

    async def test_fallback_s11_reflects_impedance_mismatch(self) -> None:
        """The dipole fallback must derive S11 from the actual impedance model,
        not return a canned curve: |S11| for 73+j42.5 Ω on 50 Ω is ~0.454."""
        adapter = NEC2Adapter(executable="nec2c-definitely-not-installed")
        f = 2.45e9
        z = NEC2Adapter.dipole_impedance_induced_emf(f, C0 / f / 2)
        gamma_expected = abs((z - 50) / (z + 50))
        spec = SimulationSpec(
            name="s11 check", frequency_range=(f, f + 1e6), frequency_points=2
        )
        mesh = await adapter.mesh(_dipole_geometry(C0 / f / 2), spec)
        result = await adapter.solve(mesh, spec)
        assert result.s_params is not None
        s11 = abs(result.s_params.s_matrix[0][0][0])
        assert s11 == pytest.approx(gamma_expected, rel=0.05)
