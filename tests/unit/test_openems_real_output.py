"""Tests for the openEMS subprocess path against *real* solver output.

Fixtures under tests/fixtures/openems/ were produced by the official
openEMS v0.0.36 Python API:
- generate_reference.py: 0.5 m wire dipole in free space — the same
  antenna as the NEC2 fixtures, so the two real solvers can
  cross-validate each other.
- generate_patch_reference.py: the tutorial 32×40 mm microstrip patch
  (εr=3.38 substrate, probe feed) — reference S11 −17.8 dB @ 2.44 GHz,
  validating the self-built patch XML path.

End-to-end tests run openEMS.exe and are skipped when it is not
installed (official package expected at C:\\opt\\openEMS on Windows,
or set YAF_OPENEMS_EXE).
"""

import asyncio
import math
from pathlib import Path

import numpy as np
import pytest

from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationSpec
from yaf_core.geometry.parametric import ParametricGenerator
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
from yaf_solvers.openems_adapter.adapter import (
    OpenEMSAdapter,
    mask_to_boxes,
    rasterize_planar_mesh,
)
from yaf_solvers.openems_adapter.nf2ff import (
    read_result,
    resolve_nf2ff_executable,
    write_control_xml,
)
from yaf_solvers.openems_adapter.port_parser import (
    OpenEMSParseError,
    calc_port,
    read_probe,
)
from yaf_solvers.openems_adapter.xml_writer import grade_lines, smooth_lines

FIXTURES = Path(__file__).parent.parent / "fixtures" / "openems"

openems_missing = OpenEMSAdapter()._resolve_executable() is None
nec2c_missing = NEC2Adapter()._resolve_runner() is None


def _wire_dipole(length: float = 0.5) -> Geometry:
    return Geometry(
        name="dipole",
        representation="mesh",
        vertices=[[0.0, 0.0, -length / 2], [0.0, 0.0, length / 2]],
        faces=[[0, 1]],
    )


def _spec() -> SimulationSpec:
    return SimulationSpec(
        name="openems dipole", frequency_range=(100e6, 500e6),
        frequency_points=81,
    )


def _patch_geometry():
    # exactly the official tutorial patch used by generate_patch_reference.py
    return ParametricGenerator.rectangular_patch(
        width=40e-3, length=32e-3, substrate_thickness=1.524e-3,
        substrate_width=60e-3, substrate_length=60e-3,
        eps_r=3.38, loss_tangent=1e-3, feed_x=-6e-3,
    )


def _patch_spec() -> SimulationSpec:
    return SimulationSpec(
        name="openems patch", frequency_range=(1e9, 3e9),
        frequency_points=101,
    )


def _sheet_patch_geometry(pixel_size: float = 2e-3) -> Geometry:
    """The tutorial 32×40 mm patch as a RAW planar sheet (two triangles).

    Same substrate/feed as the parametric fixture, so the pixel-raster
    path must reproduce the known 2.44 GHz resonance — that one number
    validates the whole voxelization chain.
    """
    hx, hy = 16e-3, 20e-3
    return Geometry(
        name="sheet_patch", representation="mesh",
        vertices=[[-hx, -hy, 0.0], [hx, -hy, 0.0],
                  [hx, hy, 0.0], [-hx, hy, 0.0]],
        faces=[[0, 1, 2], [0, 2, 3]],
        metadata={
            "antenna_class": "pixel_patch",
            "substrate_thickness": 1.524e-3, "eps_r": 3.38,
            "loss_tangent": 1e-3,
            "substrate_length": 60e-3, "substrate_width": 60e-3,
            "feed_x": -6e-3, "feed_y": 0.0,
            "pixel_size": pixel_size,
        },
    )


@pytest.fixture(scope="module")
def official_reference():
    ref = np.genfromtxt(FIXTURES / "dipole_s11.csv", delimiter=",", skip_header=2)
    return {
        "freq": ref[:, 0],
        "s11": ref[:, 1] + 1j * ref[:, 2],
        "zin": ref[:, 3] + 1j * ref[:, 4],
    }


class TestPortParser:
    def test_probe_file_reads(self):
        # probes are decimated (every ~10th timestep); the file's own dt
        # still gives a Nyquist limit far above the 500 MHz band
        t, u = read_probe(FIXTURES / "port_ut_1")
        assert len(t) == len(u) > 200
        assert t[0] == 0.0

    def test_matches_official_api_s11(self, official_reference):
        freqs = official_reference["freq"].tolist()
        mine = calc_port(FIXTURES, 1, freqs)
        diff = np.max(np.abs(np.array(mine.s11) - official_reference["s11"]))
        # locked against openEMS.ports.Port.CalcPort on the same probes
        assert diff < 0.02

    def test_resonance_matches_official_api(self, official_reference):
        freqs = official_reference["freq"].tolist()
        mine = calc_port(FIXTURES, 1, freqs)
        zin = np.array(mine.z_in)
        i = int(np.argmin(np.abs(zin.imag)))
        assert freqs[i] == pytest.approx(275e6, abs=10e6)
        assert zin[i].real == pytest.approx(71.8, rel=0.05)

    def test_missing_probe_raises(self, tmp_path):
        with pytest.raises(OpenEMSParseError, match="missing"):
            calc_port(tmp_path, 1, [1e9])

    def test_all_zero_probe_raises(self, tmp_path):
        # a decoupled excitation yields all-zero probes; that must fail
        # loudly, not report a perfectly matched antenna (S11=0, VSWR=1)
        rows = "\n".join(f"{t*1e-12:.3e}\t0.0" for t in range(300))
        (tmp_path / "port_ut_1").write_text("% t\tvalue\n" + rows)
        (tmp_path / "port_it_1").write_text("% t\tvalue\n" + rows)
        with pytest.raises(OpenEMSParseError, match="all zeros"):
            calc_port(tmp_path, 1, [1e9])


class TestGradeLines:
    def test_reaches_end_exactly(self):
        lines = grade_lines(0.25, 1.5, 0.0125, 0.1)
        assert lines[-1] == 1.5
        assert all(b > a for a, b in zip(lines, lines[1:], strict=False))

    def test_steps_grow_capped(self):
        lines = [0.25, *grade_lines(0.25, 1.5, 0.0125, 0.1)]
        steps = np.diff(lines)
        assert steps.max() <= 0.1 + 1e-9

    def test_negative_direction(self):
        lines = grade_lines(-0.25, -1.5, 0.0125, 0.1)
        assert lines[-1] == -1.5


class TestSmoothLines:
    def test_keeps_fixed_lines(self):
        fixed = [-0.1, 0.0, 0.0004, 0.0008, 0.1]
        out = smooth_lines(fixed, 0.005)
        for v in fixed:
            assert v in out

    def test_monotonic_and_bounded(self):
        out = smooth_lines([-0.1, 0.0, 0.0004, 0.1], 0.005)
        steps = np.diff(out)
        assert (steps > 0).all()
        # runt-cell absorption may merge one cell up to 1.5× the cap
        assert steps.max() <= 0.005 * 1.5 + 1e-12

    def test_grades_away_from_fine_region(self):
        # fine 0.4 mm cells at zero must not jump straight to 5 mm cells
        out = np.array(smooth_lines([-0.05, 0.0, 0.0004, 0.05], 0.005))
        steps = np.diff(out)
        i = int(np.argmin(np.abs(out[:-1])))  # step starting at 0.0
        assert steps[i + 1] <= 0.0004 * 1.4 * 1.5

    def test_small_gaps_untouched(self):
        assert smooth_lines([0.0, 0.001, 0.002], 0.005) == [0.0, 0.001, 0.002]


def _read_farfield_fixture():
    lines = (FIXTURES / "patch_farfield.csv").read_text().splitlines()
    meta = dict(
        kv.split("=") for kv in lines[1].lstrip("# ").split(",") if "=" in kv
    )
    data = np.genfromtxt(FIXTURES / "patch_farfield.csv",
                         delimiter=",", skip_header=3)
    theta = np.unique(data[:, 0])
    phi = np.unique(data[:, 1])
    shape = (len(theta), len(phi))
    return {
        "f_res": float(meta["f_res_hz"]),
        "dmax": float(meta["Dmax"]),
        "prad": float(meta["Prad"]),
        "p_in": float(meta["P_in"]),
        "efficiency": float(meta["efficiency"]),
        "theta": theta,
        "phi": phi,
        "e_theta": (data[:, 2] + 1j * data[:, 3]).reshape(shape),
        "e_phi": (data[:, 4] + 1j * data[:, 5]).reshape(shape),
    }


class TestNf2ffControlXml:
    def test_written_format(self, tmp_path):
        import xml.etree.ElementTree as ET

        for n in (0, 3):
            (tmp_path / f"nf2ff_E_{n}.h5").touch()
            (tmp_path / f"nf2ff_H_{n}.h5").touch()
        control = write_control_xml(tmp_path, 2.44e9, [0.0, 90.0, 180.0],
                                    [0.0, 180.0])
        root = ET.parse(control).getroot()
        assert root.tag == "nf2ff"
        assert float(root.get("freq")) == pytest.approx(2.44e9)
        # numeric lists are comma-separated radians (nf2ff.cpp
        # SplitString2Float default delimiter)
        theta = [float(v) for v in root.find("theta").text.split(",")]
        assert theta == pytest.approx([0.0, np.pi / 2, np.pi])
        planes = root.findall("Planes")
        assert [p.get("E_Field") for p in planes] == \
            ["nf2ff_E_0.h5", "nf2ff_E_3.h5"]
        assert planes[0].get("H_Field") == "nf2ff_H_0.h5"

    def test_no_planes_raises(self, tmp_path):
        with pytest.raises(OpenEMSParseError, match="dump planes"):
            write_control_xml(tmp_path, 1e9, [0.0], [0.0])


class TestNf2ffResultParser:
    """Parses the *official* nf2ff result file, locked to the CSV dump."""

    @pytest.fixture(scope="class")
    def official(self):
        return _read_farfield_fixture()

    @pytest.fixture(scope="class")
    def parsed(self):
        return read_result(FIXTURES / "patch_nf2ff.h5")

    def test_metadata(self, parsed, official):
        assert parsed.frequency == pytest.approx(official["f_res"])
        assert parsed.dmax == pytest.approx(official["dmax"], rel=1e-6)
        assert parsed.prad == pytest.approx(official["prad"], rel=1e-6)

    def test_grid(self, parsed, official):
        assert parsed.theta_deg == pytest.approx(official["theta"])
        assert parsed.phi_deg == pytest.approx(official["phi"])

    def test_fields_match_official_reader(self, parsed, official):
        scale = np.max(np.abs(official["e_theta"]))
        assert np.max(np.abs(parsed.e_theta - official["e_theta"])) / scale < 1e-6
        assert np.max(np.abs(parsed.e_phi - official["e_phi"])) / scale < 1e-6

    def test_directivity_integral_matches_official_dmax(self, parsed, official):
        # cross-check: our FarFieldResult spherical integral vs the
        # Dmax computed inside the official nf2ff engine
        from yaf_core.domain.simulation import FarFieldResult

        ff = FarFieldResult(
            theta=parsed.theta_deg, phi=parsed.phi_deg,
            e_theta=[[complex(v) for v in row] for row in parsed.e_theta],
            e_phi=[[complex(v) for v in row] for row in parsed.e_phi],
            frequency=parsed.frequency,
        )
        d_db = np.max(ff.gain_dbi())
        assert d_db == pytest.approx(10 * np.log10(official["dmax"]), abs=0.3)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(OpenEMSParseError, match="missing"):
            read_result(tmp_path / "nope.h5")


class TestPatchSimXml:
    """Self-built patch XML structure (no solver binary needed)."""

    @pytest.fixture(scope="class")
    def xml_root(self):
        import xml.etree.ElementTree as ET

        adapter = OpenEMSAdapter()
        spec = _patch_spec()
        mesh = asyncio.run(adapter.mesh(_patch_geometry(), spec))
        xml_bytes, z0 = adapter._build_sim_xml(mesh, spec)
        assert z0 == 50.0
        return ET.fromstring(xml_bytes)

    def test_has_substrate_material(self, xml_root):
        mats = xml_root.findall(".//Material")
        assert len(mats) == 1
        prop = mats[0].find("Property")
        assert float(prop.get("Epsilon")) == pytest.approx(3.38)
        assert float(prop.get("Kappa")) > 0  # lossy substrate

    def test_has_patch_and_ground(self, xml_root):
        names = {m.get("Name") for m in xml_root.findall(".//Metal")}
        assert names == {"patch", "gnd"}

    def test_port_is_vertical_probe_at_feed(self, xml_root):
        lumped = xml_root.find(".//LumpedElement")
        assert lumped.get("Direction") == "2"  # z
        p1 = lumped.find(".//P1")
        assert float(p1.get("X")) == pytest.approx(-6e-3)
        assert float(p1.get("Y")) == pytest.approx(0.0)

    def test_mesh_lines_monotonic_with_substrate_cells(self, xml_root):
        grid = xml_root.find(".//RectilinearGrid")
        for tag in ("XLines", "YLines", "ZLines"):
            vals = np.array([float(v) for v in grid.find(tag).text.split(",")])
            assert (np.diff(vals) > 0).all()
        z = [float(v) for v in grid.find("ZLines").text.split(",")]
        for zl in np.linspace(0.0, 1.524e-3, 5):
            assert any(abs(v - zl) < 1e-9 for v in z)

    def test_no_nf2ff_dumps_unless_requested(self, xml_root):
        assert xml_root.findall(".//DumpBox") == []

    def test_nf2ff_dumps_when_requested(self):
        import xml.etree.ElementTree as ET

        adapter = OpenEMSAdapter()
        spec = _patch_spec()
        spec.far_field_request = {}
        mesh = asyncio.run(adapter.mesh(_patch_geometry(), spec))
        xml_bytes, _ = adapter._build_sim_xml(mesh, spec)
        root = ET.fromstring(xml_bytes)
        dumps = root.findall(".//DumpBox")
        assert {d.get("Name") for d in dumps} == {"nf2ff_E", "nf2ff_H"}
        assert {d.get("DumpType") for d in dumps} == {"0", "1"}
        for dump in dumps:
            assert len(dump.findall(".//Box")) == 6
        # recording box must sit 2 cells inside every boundary
        grid = root.find(".//RectilinearGrid")
        x = sorted({float(v) for v in grid.find("XLines").text.split(",")})
        xs = [float(p.get("X"))
              for p in dumps[0].findall(".//P1") + dumps[0].findall(".//P2")]
        assert min(xs) == pytest.approx(x[2])
        assert max(xs) == pytest.approx(x[-3])


def _lorentz_patch_geometry() -> Geometry:
    """Tutorial patch on a LORENTZ-dispersive substrate.

    eps_inf=2.5 with a 30 GHz pole tuned so eps(2.44 GHz) ≈ 3.38 — the
    same effective permittivity as the fixture patch. If the engine
    ignored the dispersion the substrate would act as eps=2.5 and the
    resonance would jump to ~2.8 GHz, so the fixture comparison
    discriminates hard.
    """
    eps_inf, eps_static = 2.5, 3.38
    pole = 30e9
    plasma = pole * math.sqrt(eps_static / eps_inf - 1)
    return ParametricGenerator.rectangular_patch(
        width=40e-3, length=32e-3, substrate_thickness=1.524e-3,
        substrate_width=60e-3, substrate_length=60e-3,
        eps_r=eps_inf, loss_tangent=1e-3, feed_x=-6e-3,
        substrate_dispersion={
            "model": "lorentz",
            "plasma_freq_hz": plasma,
            "pole_freq_hz": pole,
        },
    )


class TestDispersiveSubstrateXml:
    """Drude/Lorentz substrate serialization (no solver needed)."""

    @pytest.fixture(scope="class")
    def xml_root(self):
        import xml.etree.ElementTree as ET

        adapter = OpenEMSAdapter()
        spec = _patch_spec()
        mesh = asyncio.run(adapter.mesh(_lorentz_patch_geometry(), spec))
        xml_bytes, _ = adapter._build_sim_xml(mesh, spec)
        return ET.fromstring(xml_bytes)

    def test_lorentz_material_replaces_plain_substrate(self, xml_root):
        lor = xml_root.findall(".//LorentzMaterial")
        assert len(lor) == 1
        assert lor[0].get("Name") == "substrate"
        assert xml_root.find(".//Properties/Material") is None

    def test_pole_attributes_in_hz(self, xml_root):
        prop = xml_root.find(".//LorentzMaterial/Property")
        assert float(prop.get("Epsilon")) == pytest.approx(2.5)
        assert float(prop.get("EpsilonLorPoleFrequency_1")) == pytest.approx(30e9)
        plasma = float(prop.get("EpsilonPlasmaFrequency_1"))
        # tuned for eps_static = 2.5·(1 + (f_p/f_pole)²) = 3.38
        assert 2.5 * (1 + (plasma / 30e9) ** 2) == pytest.approx(3.38, rel=1e-6)

    def test_debye_is_refused_not_faked(self):
        from yaf_solvers.openems_adapter.adapter import _UnsupportedGeometryError

        geom = _lorentz_patch_geometry()
        geom.metadata["substrate_dispersion"] = {
            "model": "debye", "plasma_freq_hz": 1e9,
        }
        adapter = OpenEMSAdapter()
        spec = _patch_spec()
        mesh = asyncio.run(adapter.mesh(geom, spec))
        with pytest.raises(_UnsupportedGeometryError, match="[Dd]ebye"):
            adapter._build_sim_xml(mesh, spec)


@pytest.mark.skipif(openems_missing, reason="openEMS.exe not installed")
class TestLorentzPatchEndToEnd:
    """Known answer: the Lorentz substrate must act as eps≈3.38 in-band."""

    @pytest.fixture(scope="class")
    def result(self):
        adapter = OpenEMSAdapter()
        spec = _patch_spec()
        mesh = asyncio.run(adapter.mesh(_lorentz_patch_geometry(), spec))
        return asyncio.run(adapter.solve(mesh, spec))

    def test_dispersive_resonance_matches_reference(self, result):
        assert result.solver_metadata["solver_mode"] == "subprocess"
        ref = np.genfromtxt(FIXTURES / "patch_s11.csv", delimiter=",",
                            skip_header=2)
        ref_db = 20 * np.log10(np.abs(ref[:, 1] + 1j * ref[:, 2]))
        f_ref = ref[int(np.argmin(ref_db)), 0]
        freqs = np.array(result.s_params.frequency)
        s11_db = 20 * np.log10(
            np.abs([s[0][0] for s in result.s_params.s_matrix])
        )
        i = int(np.argmin(s11_db))
        # engine-ignored dispersion would land ~2.8 GHz (eps_inf=2.5)
        assert freqs[i] == pytest.approx(f_ref, rel=0.04)
        assert s11_db[i] < -10.0


class TestRasterizer:
    def test_rectangle_fills_completely(self):
        nodes = np.array([[-0.016, -0.02, 0], [0.016, -0.02, 0],
                          [0.016, 0.02, 0], [-0.016, 0.02, 0]])
        mask, x0, y0 = rasterize_planar_mesh(nodes, [[0, 1, 2], [0, 2, 3]], 2e-3)
        assert mask.shape == (16, 20)
        assert mask.all()
        assert x0 == pytest.approx(-0.016)
        assert y0 == pytest.approx(-0.02)

    def test_triangle_fills_half(self):
        nodes = np.array([[0, 0, 0], [0.032, 0, 0], [0, 0.032, 0]])
        mask, _, _ = rasterize_planar_mesh(nodes, [[0, 1, 2]], 1e-3)
        assert 0.4 < mask.mean() < 0.6

    def test_winding_direction_irrelevant(self):
        nodes = np.array([[0, 0, 0], [0.01, 0, 0], [0, 0.01, 0]])
        cw, _, _ = rasterize_planar_mesh(nodes, [[0, 2, 1]], 1e-3)
        ccw, _, _ = rasterize_planar_mesh(nodes, [[0, 1, 2]], 1e-3)
        assert (cw == ccw).all()

    def test_mask_to_boxes_rle(self):
        mask = np.array([[True, True, False, True],
                         [False, False, False, False],
                         [True, True, True, True]])
        assert mask_to_boxes(mask) == [(0, 0, 2), (0, 3, 4), (2, 0, 4)]


class TestPixelPatchSimXml:
    """Pixel-raster path XML structure (no solver binary needed)."""

    @pytest.fixture(scope="class")
    def xml_root(self):
        import xml.etree.ElementTree as ET

        adapter = OpenEMSAdapter()
        spec = _patch_spec()
        mesh = asyncio.run(adapter.mesh(_sheet_patch_geometry(), spec))
        xml_bytes, z0 = adapter._build_sim_xml(mesh, spec)
        assert z0 == 50.0
        return ET.fromstring(xml_bytes)

    def test_solid_sheet_merges_to_one_box_per_column(self, xml_root):
        metals = [m for m in xml_root.findall(".//Metal")
                  if m.get("Name", "").startswith("px_")]
        assert len(metals) == 16  # 32 mm / 2 mm columns, RLE-merged rows

    def test_pixels_sit_on_substrate_top(self, xml_root):
        px = next(m for m in xml_root.findall(".//Metal")
                  if m.get("Name", "").startswith("px_"))
        z1 = float(px.find(".//P1").get("Z"))
        z2 = float(px.find(".//P2").get("Z"))
        assert z1 == z2 == pytest.approx(1.524e-3)

    def test_has_ground_substrate_and_snapped_probe(self, xml_root):
        names = {m.get("Name") for m in xml_root.findall(".//Metal")}
        assert "gnd" in names
        assert xml_root.find(".//Material") is not None
        lumped = xml_root.find(".//LumpedElement")
        assert lumped.get("Direction") == "2"
        assert float(lumped.find(".//P1").get("X")) == pytest.approx(-6e-3)

    def test_pixel_boxes_lie_on_mesh_lines(self, xml_root):
        grid = xml_root.find(".//RectilinearGrid")
        x_lines = set(grid.find("XLines").text.split(","))
        for px in xml_root.findall(".//Metal"):
            if not px.get("Name", "").startswith("px_"):
                continue
            for pt in (*px.findall(".//P1"), *px.findall(".//P2")):
                assert pt.get("X") in x_lines  # identical %.12g strings

    def test_non_planar_sheet_rejected(self):
        geom = _sheet_patch_geometry()
        geom.vertices[2][2] = 0.02  # bend one corner far out of plane
        adapter = OpenEMSAdapter()
        spec = _patch_spec()
        mesh = asyncio.run(adapter.mesh(geom, spec))
        from yaf_solvers.openems_adapter.adapter import _UnsupportedGeometryError

        with pytest.raises(_UnsupportedGeometryError, match="planar"):
            adapter._build_sim_xml(mesh, spec)


@pytest.mark.skipif(openems_missing, reason="openEMS.exe not installed")
class TestPixelPatchEndToEnd:
    """Known answer: the tutorial patch fed through the RASTER path must
    reproduce the parametric/official resonance (quantization ±4%)."""

    @pytest.fixture(scope="class")
    def result(self):
        adapter = OpenEMSAdapter()
        spec = _patch_spec()
        mesh = asyncio.run(adapter.mesh(_sheet_patch_geometry(), spec))
        return asyncio.run(adapter.solve(mesh, spec))

    def test_ran_real_solver(self, result):
        assert result.solver_metadata["solver_mode"] == "subprocess"

    def test_rasterized_patch_reproduces_reference(self, result):
        ref = np.genfromtxt(FIXTURES / "patch_s11.csv", delimiter=",",
                            skip_header=2)
        ref_db = 20 * np.log10(np.abs(ref[:, 1] + 1j * ref[:, 2]))
        f_ref = ref[int(np.argmin(ref_db)), 0]
        freqs = np.array(result.s_params.frequency)
        s11_db = 20 * np.log10(
            np.abs([s[0][0] for s in result.s_params.s_matrix])
        )
        i = int(np.argmin(s11_db))
        assert freqs[i] == pytest.approx(f_ref, rel=0.04)
        assert s11_db[i] < -10.0


@pytest.mark.skipif(openems_missing, reason="openEMS.exe not installed")
class TestEndToEndRealFDTD:
    """Full adapter.solve() through the real openEMS.exe binary."""

    @pytest.fixture(scope="class")
    def result(self):
        adapter = OpenEMSAdapter()
        spec = _spec()
        mesh = asyncio.run(adapter.mesh(_wire_dipole(), spec))
        return asyncio.run(adapter.solve(mesh, spec))

    def test_ran_real_solver(self, result):
        assert result.solver_metadata["solver_mode"] == "subprocess"
        assert "warning" not in result.solver_metadata
        assert result.status == "success"

    def test_dipole_resonance_physics(self, result):
        freqs = np.array(result.s_params.frequency)
        s11 = np.array([s[0][0] for s in result.s_params.s_matrix])
        s11_db = 20 * np.log10(np.abs(s11))
        i = int(np.argmin(s11_db))
        # official API reference: −15.2 dB @ 270–275 MHz
        assert s11_db[i] < -10.0
        assert freqs[i] == pytest.approx(272.5e6, rel=0.08)

    def test_no_fake_far_field(self, result):
        # far field not requested → honestly absent, not filled with a
        # fabricated pattern (NF2FF runs only on far_field_request)
        assert result.far_field is None
        assert result.gain_dbi is None


@pytest.mark.skipif(
    openems_missing or nec2c_missing,
    reason="needs BOTH real solvers (nec2c + openEMS.exe)",
)
class TestCrossSolverValidation:
    """MoM (NEC2) vs FDTD (openEMS) on the same 0.5 m dipole.

    Two independent numerical methods, two independent codebases —
    agreement here is the strongest physics evidence the repo has.
    """

    @pytest.fixture(scope="class")
    def both(self):
        geom = _wire_dipole()
        spec = _spec()
        results = {}
        for name, adapter in (("nec2", NEC2Adapter()), ("openems", OpenEMSAdapter())):
            mesh = asyncio.run(adapter.mesh(geom, spec))
            results[name] = asyncio.run(adapter.solve(mesh, spec))
        return results

    @staticmethod
    def _resonance(result):
        freqs = np.array(result.s_params.frequency)
        s11 = np.array([abs(s[0][0]) for s in result.s_params.s_matrix])
        i = int(np.argmin(20 * np.log10(s11)))
        return freqs[i], s11[i]

    def test_both_real(self, both):
        assert both["nec2"].solver_metadata["solver_mode"] == "subprocess"
        assert both["openems"].solver_metadata["solver_mode"] == "subprocess"

    def test_resonant_frequency_agreement(self, both):
        f_mom, _ = self._resonance(both["nec2"])
        f_fdtd, _ = self._resonance(both["openems"])
        # thin-wire MoM vs thick-effective-radius FDTD: expect a small
        # physical offset, but the two must agree within 10%
        assert abs(f_mom - f_fdtd) / f_mom < 0.10

    def test_both_match_at_resonance(self, both):
        for result in both.values():
            _, s11_min = self._resonance(result)
            assert 20 * math.log10(s11_min) < -10.0


@pytest.mark.skipif(openems_missing, reason="openEMS.exe not installed")
class TestPatchEndToEndRealFDTD:
    """Self-built patch XML through the real openEMS.exe binary.

    Reference: official Python API on the identical antenna
    (patch_s11.csv) — S11 min −17.8 dB @ 2.440 GHz.
    """

    @pytest.fixture(scope="class")
    def result(self):
        adapter = OpenEMSAdapter()
        spec = _patch_spec()
        mesh = asyncio.run(adapter.mesh(_patch_geometry(), spec))
        return asyncio.run(adapter.solve(mesh, spec))

    @pytest.fixture(scope="class")
    def official_patch(self):
        ref = np.genfromtxt(FIXTURES / "patch_s11.csv", delimiter=",", skip_header=2)
        return {"freq": ref[:, 0], "s11": ref[:, 1] + 1j * ref[:, 2]}

    def test_ran_real_solver(self, result):
        assert result.solver_metadata["solver_mode"] == "subprocess"
        assert "warning" not in result.solver_metadata
        assert result.status == "success"

    def test_patch_resonance_physics(self, result, official_patch):
        freqs = np.array(result.s_params.frequency)
        s11_db = 20 * np.log10(
            np.abs([s[0][0] for s in result.s_params.s_matrix])
        )
        i = int(np.argmin(s11_db))
        ref_db = 20 * np.log10(np.abs(official_patch["s11"]))
        j = int(np.argmin(ref_db))
        # resonant frequency must agree with the official API run to 3 %
        assert freqs[i] == pytest.approx(official_patch["freq"][j], rel=0.03)
        assert s11_db[i] < -10.0

    def test_matched_band_agrees_with_official(self, result, official_patch):
        # same 101-point grid → compare |S11| pointwise; meshes differ
        # slightly (own SmoothMeshLines port), so allow a loose envelope
        s11 = np.abs([s[0][0] for s in result.s_params.s_matrix])
        diff = np.max(np.abs(s11 - np.abs(official_patch["s11"])))
        assert diff < 0.15

    def test_no_fake_far_field(self, result):
        assert result.far_field is None
        assert result.gain_dbi is None


nf2ff_missing = resolve_nf2ff_executable(
    OpenEMSAdapter()._resolve_executable()
) is None


@pytest.mark.skipif(openems_missing or nf2ff_missing,
                    reason="openEMS.exe / nf2ff.exe not installed")
class TestPatchFarFieldEndToEnd:
    """Full patch run with NF2FF requested, against the real binaries.

    Reference: official Python API on the identical antenna
    (patch_farfield.csv) — Dmax 6.82 dBi, efficiency 0.949,
    gain 6.60 dBi @ 2.440 GHz.
    """

    @pytest.fixture(scope="class")
    def result(self):
        adapter = OpenEMSAdapter()
        spec = _patch_spec()
        spec.far_field_request = {}
        mesh = asyncio.run(adapter.mesh(_patch_geometry(), spec))
        return asyncio.run(adapter.solve(mesh, spec))

    @pytest.fixture(scope="class")
    def official(self):
        return _read_farfield_fixture()

    def test_ran_real_solver_with_nf2ff(self, result):
        assert result.solver_metadata["solver_mode"] == "subprocess"
        assert "nf2ff_warning" not in result.solver_metadata
        assert result.far_field is not None

    def test_transform_frequency_is_resonance(self, result, official):
        assert result.far_field.frequency == \
            pytest.approx(official["f_res"], rel=0.03)

    def test_gain_and_efficiency(self, result, official):
        gain_ref = 10 * np.log10(official["dmax"] * official["efficiency"])
        assert result.gain_dbi == pytest.approx(gain_ref, abs=0.5)
        assert result.efficiency == \
            pytest.approx(official["efficiency"], abs=0.05)

    def test_pattern_shape_matches_official(self, result, official):
        # normalized radiation pattern: boresight max, agrees with the
        # official pattern to a few percent despite the mesh differences
        e_t = np.array(result.far_field.e_theta)
        e_p = np.array(result.far_field.e_phi)
        mine = np.sqrt(np.abs(e_t) ** 2 + np.abs(e_p) ** 2)
        ref = np.sqrt(np.abs(official["e_theta"]) ** 2
                      + np.abs(official["e_phi"]) ** 2)
        assert mine.shape == ref.shape
        it, _ = np.unravel_index(int(np.argmax(mine)), mine.shape)
        assert result.far_field.theta[it] <= 30.0  # boresight ≈ +z
        assert np.max(np.abs(mine / mine.max() - ref / ref.max())) < 0.12

    def test_directivity_integral_consistent(self, result, official):
        d_db = np.max(result.far_field.gain_dbi())
        assert d_db == pytest.approx(10 * np.log10(official["dmax"]), abs=0.5)
