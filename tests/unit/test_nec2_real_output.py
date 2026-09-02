"""Tests for the NEC2 output parser against *real* nec2c output.

The fixtures under tests/fixtures/nec2/ were produced by Debian nec2c
from the checked-in .nec decks (regenerate: ``nec2c -i x.nec -o x.out``).
These tests pin the parser to the actual output format — the previous
parser grepped for "INPUT IMPEDANCE" / "MAX GAIN", strings nec2c never
prints, and silently returned hardcoded textbook values instead.

The end-to-end tests at the bottom run the real solver and are skipped
when nec2c is not installed (they run in CI, where it is).
"""

import asyncio
import math
import os
from pathlib import Path

import pytest

from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.nec2_adapter.output_parser import (
    NEC2ParseError,
    parse_nec2_output,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "nec2"

# Real solver reachable natively or through the Windows→WSL bridge
nec2c_missing = NEC2Adapter()._resolve_runner() is None


@pytest.fixture(scope="module")
def dipole_blocks():
    return parse_nec2_output((FIXTURES / "dipole_sweep.out").read_text())


@pytest.fixture(scope="module")
def yagi_blocks():
    return parse_nec2_output((FIXTURES / "yagi_3el.out").read_text())


class TestParserDipole:
    def test_one_block_per_frequency(self, dipole_blocks):
        assert len(dipole_blocks) == 11
        freqs = [b.frequency_hz for b in dipole_blocks]
        assert freqs[0] == pytest.approx(250e6)
        assert freqs[-1] == pytest.approx(350e6)

    def test_impedance_is_frequency_dependent(self, dipole_blocks):
        impedances = {b.impedance for b in dipole_blocks}
        assert len(impedances) == 11  # a faked sweep would repeat one value

    def test_resonance_near_290mhz(self, dipole_blocks):
        # L=0.5m, a=0.1mm dipole: nec2c gives Z = 71.96 - j0.21 at 290 MHz
        by_freq = {round(b.frequency_hz / 1e6): b for b in dipole_blocks}
        z = by_freq[290].impedance
        assert z.real == pytest.approx(71.96, rel=0.01)
        assert abs(z.imag) < 5.0  # resonant: reactance crosses zero here

    def test_gain_matches_textbook_dipole(self, dipole_blocks):
        by_freq = {round(b.frequency_hz / 1e6): b for b in dipole_blocks}
        # Half-wave dipole directivity is 2.15 dBi
        assert by_freq[290].max_gain_dbi() == pytest.approx(2.15, abs=0.1)

    def test_lossless_wire_efficiency_is_one(self, dipole_blocks):
        assert dipole_blocks[0].efficiency == pytest.approx(1.0)
        assert dipole_blocks[0].input_power_w == pytest.approx(
            dipole_blocks[0].radiated_power_w
        )

    def test_pattern_peak_is_broadside(self, dipole_blocks):
        best = max(dipole_blocks[5].pattern, key=lambda p: p.gain_total_db)
        assert best.theta_deg == pytest.approx(90.0)


class TestParserYagi:
    def test_gain_depends_on_geometry(self, yagi_blocks):
        # 3-element Yagi: ~8.6 dBi — must NOT be the dipole's 2.15
        gain = yagi_blocks[0].max_gain_dbi()
        assert 7.0 < gain < 10.0

    def test_beam_points_at_director(self, yagi_blocks):
        best = max(yagi_blocks[0].pattern, key=lambda p: p.gain_total_db)
        assert best.theta_deg == pytest.approx(90.0)
        assert best.phi_deg == pytest.approx(0.0)  # +x, toward the director

    def test_front_to_back_ratio(self, yagi_blocks):
        rows = {(p.theta_deg, p.phi_deg): p.gain_total_db
                for p in yagi_blocks[0].pattern}
        front = rows[(90.0, 0.0)]
        back = rows[(90.0, 180.0)]
        assert front - back > 5.0  # a real Yagi is directional


class TestParserFailsLoudly:
    def test_empty_output_raises(self):
        with pytest.raises(NEC2ParseError):
            parse_nec2_output("")

    def test_garbage_output_raises(self):
        with pytest.raises(NEC2ParseError):
            parse_nec2_output("SEGMENT FAULT\ncore dumped\n")

    def test_block_without_impedance_raises(self):
        with pytest.raises(NEC2ParseError, match="ANTENNA INPUT PARAMETERS"):
            parse_nec2_output("FREQUENCY : 3.0000E+02 MHz\n")


class TestAdapterFromRealOutput:
    """Adapter-level result built from a real nec2c output file."""

    @pytest.fixture(scope="class")
    def result(self):
        raw = (FIXTURES / "dipole_sweep.out").read_bytes()
        return asyncio.run(NEC2Adapter().from_native_result(raw))

    def test_labeled_subprocess(self, result):
        assert result.solver_metadata["solver_mode"] == "subprocess"
        assert "warning" not in result.solver_metadata

    def test_s11_sweep_is_real(self, result):
        freqs = result.s_params.frequency
        s11_db = [20 * math.log10(abs(s[0][0])) for s in result.s_params.s_matrix]
        best = min(zip(s11_db, freqs, strict=True))
        # 72 Ω vs 50 Ω at resonance → |Γ|=0.18 → S11 ≈ −14.9 dB near 290 MHz
        assert best[0] == pytest.approx(-14.9, abs=1.0)
        assert best[1] == pytest.approx(290e6, abs=10e6)

    def test_gain_and_efficiency_from_output(self, result):
        assert result.gain_dbi == pytest.approx(2.15, abs=0.15)
        assert result.efficiency == pytest.approx(1.0)

    def test_far_field_grid(self, result):
        ff = result.far_field
        assert len(ff.theta) == 37
        assert len(ff.e_theta) == 37
        assert len(ff.e_theta[0]) == len(ff.phi)

    def test_directivity_integration_matches_nec_gain(self, result):
        # Independent cross-check: integrating the E-field pattern
        # (FarFieldResult.gain_dbi) must reproduce the power gain nec2c
        # itself reports — both should give a half-wave dipole's ~2.15 dBi
        pattern = result.far_field.gain_dbi()
        peak = max(max(row) for row in pattern)
        assert peak == pytest.approx(result.gain_dbi, abs=0.2)


class TestWSLPathTranslation:
    @pytest.mark.skipif(os.name != "nt", reason="WSL bridge only exists on Windows")
    def test_windows_path_for_wsl_runner(self):
        p = Path("C:/Users/pra/AppData/Local/Temp/nec2_x/simulation.nec")
        out = NEC2Adapter._solver_path(p, ["wsl", "--", "nec2c"])
        assert out == "/mnt/c/Users/pra/AppData/Local/Temp/nec2_x/simulation.nec"

    def test_native_runner_keeps_path(self):
        p = Path("C:/tmp/simulation.nec")
        assert NEC2Adapter._solver_path(p, ["nec2c"]) == str(p)


@pytest.mark.skipif(nec2c_missing, reason="nec2c not reachable (PATH or WSL)")
class TestEndToEndRealSolver:
    """Full adapter.solve() through the real nec2c binary."""

    @pytest.fixture(scope="class")
    def result(self):
        # z-oriented 0.5 m wire dipole as a 2-node wire geometry
        geom = Geometry(
            vertices=[[0.0, 0.0, -0.25], [0.0, 0.0, 0.25]],
            faces=[[0, 1]],
        )
        spec = SimulationSpec(
            name="e2e dipole",
            frequency_range=(250e6, 350e6),
            frequency_points=11,
        )
        adapter = NEC2Adapter()
        mesh = asyncio.run(adapter.mesh(geom, spec))
        return asyncio.run(adapter.solve(mesh, spec))

    def test_ran_real_solver(self, result):
        assert result.solver_metadata["solver_mode"] == "subprocess"
        assert result.status == "success"

    def test_physical_dipole_behavior(self, result):
        # 1 mm wire radius shifts resonance slightly vs the fixture — keep
        # tolerances physical, not cosmetic
        assert result.gain_dbi == pytest.approx(2.15, abs=0.3)
        s11_db = [20 * math.log10(abs(s[0][0])) for s in result.s_params.s_matrix]
        assert min(s11_db) < -10.0

    def test_health_check_true_when_installed(self):
        assert asyncio.run(NEC2Adapter().health_check()) is True
