"""Unit tests for solver adapters."""

import asyncio

from yaf_core.domain.geometry import Geometry
from yaf_core.domain.simulation import SimulationSpec
from yaf_solvers.nec2_adapter.card_writer import NEC2CardWriter


class TestNEC2CardWriter:
    def test_dipole_card(self):
        writer = NEC2CardWriter()
        writer.add_dipole(length=0.0625, tag=1)
        writer.cards.append(writer.ge_card(0))
        writer.cards.append(writer.gn_card(0))
        writer.cards.append(writer.ex_card(0, 1, 11))
        writer.cards.append(writer.fr_card(2400.0))
        writer.cards.append(writer.rp_card())
        deck = writer.generate()
        assert "GW" in deck
        assert "GE" in deck
        assert "EX" in deck
        assert "FR" in deck
        assert "RP" in deck
        assert "EN" in deck

    def test_loop_card(self):
        writer = NEC2CardWriter()
        writer.add_loop(radius=0.05, segments=8)
        deck = writer.generate()
        assert "GW" in deck

    def test_yagi_card(self):
        writer = NEC2CardWriter()
        writer.add_yagi(n_elements=3, freq=2.4e9)
        deck = writer.generate()
        assert "GW" in deck


class TestOpenEMSAdapter:
    def test_capabilities(self):
        from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter
        adapter = OpenEMSAdapter()
        caps = asyncio.run(adapter.capabilities())
        assert "fdtd" in caps["methods"]
        assert caps["name"] == "openems"

    def test_to_native_format(self):
        from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter
        adapter = OpenEMSAdapter()
        geom = Geometry(vertices=[[0,0,0],[1,0,0],[0,1,0]], faces=[[0,1,2]])
        xml = adapter.to_native_format(geom)
        assert b"ContinuousStructure" in xml


class TestNEC2Adapter:
    def test_capabilities(self):
        from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
        adapter = NEC2Adapter()
        caps = asyncio.run(adapter.capabilities())
        assert "mom" in caps["methods"]

    def test_to_native_format(self):
        from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
        adapter = NEC2Adapter()
        geom = Geometry()
        nec_bytes = adapter.to_native_format(geom)
        assert b"GW" in nec_bytes

    def test_analytical_solve(self):
        from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
        adapter = NEC2Adapter()
        geom = Geometry()
        spec = SimulationSpec(frequency_range=(1e9, 2e9))
        mesh = asyncio.run(adapter.mesh(geom, spec))
        result = asyncio.run(adapter.solve(mesh, spec))
        assert result.status == "success"
        assert result.gain_dbi is not None
