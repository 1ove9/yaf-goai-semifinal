"""Tests for the assistant tool layer (function-calling bridge).

Schema/dispatch/summary logic is covered without any solver; the
end-to-end tool run is gated on a real solver being installed.
"""

import asyncio
import json
import uuid

import pytest

from yaf_api.routers.chat import merge_tool_call_delta
from yaf_api.routers.chat_tools import (
    _HANDLERS,
    TOOLS_SCHEMA,
    _summary,
    execute_tool,
)
from yaf_core.domain.simulation import SimulationResult, SParamResult


class TestToolsSchema:
    def test_schema_matches_handlers(self):
        names = {t["function"]["name"] for t in TOOLS_SCHEMA}
        assert names == set(_HANDLERS)

    def test_schema_is_json_serializable(self):
        parsed = json.loads(json.dumps(TOOLS_SCHEMA))
        for tool in parsed:
            assert tool["type"] == "function"
            assert "parameters" in tool["function"]
            assert tool["function"]["description"]


class TestExecuteTool:
    def test_unknown_tool(self):
        out = asyncio.run(execute_tool("melt_the_antenna", {}))
        assert "unknown tool" in out["error"]

    def test_invalid_arguments(self):
        out = asyncio.run(execute_tool("simulate_patch", {"width_mm": -5}))
        assert "invalid arguments" in out["error"]

    def test_band_order_rejected(self):
        out = asyncio.run(execute_tool("simulate_dipole", {
            "length_mm": 60, "f_min_ghz": 3.0, "f_max_ghz": 2.0,
        }))
        assert "error" in out


class TestSummary:
    @staticmethod
    def _result(mode: str) -> SimulationResult:
        freqs = [1e9, 1.5e9, 2e9, 2.5e9, 3e9]
        r = SimulationResult(
            job_id=uuid.uuid4(), solver_name="openems",
            solver_version="x", status="success",
            s_params=SParamResult(
                frequency=freqs,
                s_matrix=[[[0.9]], [[0.5]], [[0.05]], [[0.6]], [[0.9]]],
            ),
            vswr=1.2,
        )
        r.solver_metadata["solver_mode"] = mode
        return r

    def test_real_result_fields(self):
        out = _summary(self._result("subprocess"))
        assert out["solver_mode"] == "subprocess"
        assert out["resonance_ghz"] == pytest.approx(2.0)
        assert out["s11_min_db"] == pytest.approx(-26.02, abs=0.1)
        assert "warning" not in out
        assert all(len(p) == 2 for p in out["s11_db_curve"])

    def test_fallback_is_flagged_loudly(self):
        out = _summary(self._result("fallback_analytical"))
        assert "ANALYTICAL ESTIMATE" in out["warning"]


class TestToolCallDeltaMerge:
    def test_fragments_assemble(self):
        pending: dict[int, dict[str, str]] = {}
        merge_tool_call_delta(pending, [
            {"index": 0, "id": "call_1",
             "function": {"name": "simulate_patch", "arguments": ""}},
        ])
        merge_tool_call_delta(pending, [
            {"index": 0, "function": {"arguments": '{"width_'}},
        ])
        merge_tool_call_delta(pending, [
            {"index": 0, "function": {"arguments": 'mm": 40}'}},
        ])
        assert pending[0]["id"] == "call_1"
        assert pending[0]["name"] == "simulate_patch"
        assert json.loads(pending[0]["arguments"]) == {"width_mm": 40}

    def test_parallel_calls_by_index(self):
        pending: dict[int, dict[str, str]] = {}
        merge_tool_call_delta(pending, [
            {"index": 0, "id": "a", "function": {"name": "simulate_patch"}},
            {"index": 1, "id": "b", "function": {"name": "simulate_dipole"}},
        ])
        assert pending[0]["name"] == "simulate_patch"
        assert pending[1]["name"] == "simulate_dipole"


def _any_real_solver() -> bool:
    from yaf_solvers.nec2_adapter.adapter import NEC2Adapter
    from yaf_solvers.openems_adapter.adapter import OpenEMSAdapter

    return (
        OpenEMSAdapter()._resolve_executable() is not None
        or NEC2Adapter()._resolve_runner() is not None
    )


@pytest.mark.skipif(not _any_real_solver(), reason="no real solver installed")
class TestToolEndToEnd:
    def test_simulate_dipole_runs_real_solver(self):
        out = asyncio.run(execute_tool("simulate_dipole", {
            "length_mm": 500, "f_min_ghz": 0.1, "f_max_ghz": 0.5,
        }))
        assert "error" not in out
        assert out["solver_mode"] in ("subprocess", "native")
        # 0.5 m dipole: both real solvers put resonance at 270-290 MHz
        assert out["resonance_ghz"] == pytest.approx(0.28, abs=0.02)
        assert out["s11_min_db"] < -10
