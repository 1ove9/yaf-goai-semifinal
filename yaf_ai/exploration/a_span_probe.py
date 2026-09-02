"""Frozen finite-set causal probe for extending the state-A span support.

This module is intentionally self-contained.  It imports the frozen geometry,
scoring, solver, and persistence primitives without modifying their original
contracts.  Positive-dose rows are diagnostic counterfactuals and can never
enter the original B-completion candidate pool.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, NoReturn, Protocol, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yaf_ai.analysis.paired_b_completion import (
    L_REQUIRED,
    Agent,
    BCompletionRecordRef,
    ParentId,
    record_ref,
)
from yaf_ai.exploration.paired_b_completion_coordinates import get_frozen_parent
from yaf_ai.exploration.paired_b_completion_gates import (
    canonical_curve_sha256,
)
from yaf_ai.exploration.paired_feasible_gates import (  # noqa: PLC2701
    StageAGateError,
    _git,
    _git_blob,
    _manifest_entries,
    _manifest_index,
    _require_ancestor,
    _sha256,
)
from yaf_ai.exploration.paired_meander import (
    BOX_SIZE_UM,
    MINIMUM_PITCH_M,
    MINIMUM_SEGMENT_M,
    STATE_A_FREQUENCIES_HZ,
    STATE_B_FREQUENCIES_HZ,
    TRAJECTORY_POINT_COUNT,
    HardwareSpec,
    PairedMeanderError,
    SearchCurve,
    StateControl,
    _build_quantized_geometry,  # noqa: PLC2701
    _interpolate_integer,  # noqa: PLC2701
    build_state_geometry,
    minimum_nonadjacent_clearance,
    score_state_curve,
    state_geometry_hash,
)
from yaf_ai.exploration.paired_runner import (  # noqa: PLC2701
    PairedEvaluationRecord,
    _append_jsonl,
    _write_json,
)
from yaf_ai.exploration.paired_solver import (
    NEC2_SEGMENTS_PER_WAVELENGTH,
    PairedNEC2Solver,
)
from yaf_core.domain.geometry import Geometry, Mesh
from yaf_core.domain.simulation import SimulationResult, SimulationSpec
from yaf_solvers.nec2_adapter.adapter import NEC2Adapter

STUDY_ID = "semifinal-a-span-support-causal-probe-v1"
RUN_ID = STUDY_ID
SOURCE_COMMIT = "e5f36fd971a7266531a6d124f553f121379ad889"
SOURCE_EVIDENCE_COMMIT = SOURCE_COMMIT
PREREGISTRATION_COMMIT = "5a6e778f57d37511be7b442ef890024079d81f63"
PREREGISTRATION_DOCUMENT_SHA256 = (
    "7be7d9c1537f52be335c0ad4eec88e32ae5f61d821e9074cba2d9b7dbf13dfaa"
)
SOURCE_MANIFEST_ENTRY_COUNT = 254
SOURCE_MANIFEST_SHA256 = (
    "9f205ae20da00e383750e3fd84acd9b75b824aa9f27e83e002960d93a89204b5"
)
SOURCE_APPENDIX_SHA256 = (
    "9eb3786fd016e7e314e4c266b13e3d6a03513db5d5e00b202b8732fd3e93aa24"
)
SOURCE_REPORT_SHA256 = (
    "1d1900d1e1841930e7110dd16363cec470be56e764fb2f0d6f2740cacf9230da"
)
SOURCE_ACCEPTED_COUNT = 6_000
SOURCE_H1_COUNT = 702
SOURCE_H2_COUNT = 0
SOURCE_P01_H1_COUNT = 267
SOURCE_P02_H1_COUNT = 435
SOURCE_ES_H1_COUNTS = (16, 3, 97, 83, 66, 82, 56, 81, 125, 88)
T_REF = L_REQUIRED

MANIFEST_PATH = Path("artifacts/runs/manifest.json")
SOURCE_APPENDIX_PATH = Path(
    "artifacts/analysis/semifinal-paired-b-completion-v1/appendix.json"
)
SOURCE_REPORT_PATH = Path(
    "artifacts/analysis/semifinal-paired-b-completion-v1/report.md"
)
PREREGISTRATION_PATH = Path(
    "docs/semifinal-a-span-support-causal-probe-preregistration.md"
)
IMPLEMENTATION_PATH = Path("yaf_ai/exploration/a_span_probe.py")
RUNS_ROOT = Path("runs")
RUN_DIRECTORY = RUNS_ROOT / RUN_ID
LOG_FILENAME = "log.jsonl"
SUMMARY_FILENAME = "summary.json"
TERMINAL_FAILURE_FILENAME = "terminal_failure.json"

RUNTIME_PATH_BLOBS: dict[Path, str] = {
    Path("yaf_ai/exploration/paired_meander.py"): (
        "98fd67154d5f6a512fdf46b99da1fc273ba8eced"
    ),
    Path("yaf_ai/exploration/paired_solver.py"): (
        "96efa9fe3e755fbca9b31315d96a330bef7291b9"
    ),
    Path("yaf_ai/exploration/paired_runner.py"): (
        "d2ece9096be6daa86de6b281bb64a8b1150c782e"
    ),
    Path("yaf_ai/exploration/paired_b_completion_coordinates.py"): (
        "a1679885fbc01b33e41de7d769dd1c9cdd3b60df"
    ),
    Path("yaf_ai/exploration/paired_b_completion_gates.py"): (
        "54fe49c9825f9e1df8147a28b2be7a128a7bfd5f"
    ),
    Path("yaf_ai/analysis/paired_b_completion.py"): (
        "19d30cd88730ed1354abbdebed9c0ea397fec406"
    ),
    Path("scripts/archive_run.py"): "b532036632d9603c500313fb2a481a009da2c6e7",
}

DosePPM = Literal[0, 50_000, 100_000]
DOSES_PPM: tuple[DosePPM, DosePPM, DosePPM] = (0, 50_000, 100_000)
PARENTS: tuple[ParentId, ParentId] = ("p01", "p02")
SEEDS = (101, 202, 303, 404, 505)
PLANNED_CALLS = 32
PLANNED_B_REPLAYS = 2
PLANNED_A_SOLVES = 30
PLANNED_GEOMETRIES = 630
MAX_DIAGNOSTIC_SPAN_PPM = 1_100_000
EXPECTED_B_CURVE_SHA256: dict[ParentId, str] = {
    "p01": "399b85ea2b8d63faa60743e8534450949bbc9846908c8cdbe995a81794c42181",
    "p02": "f4be9ba23a08b745a1e5f48a0a7bf075eb656a43df0a625a046933886b23b949",
}

Endpoint = Literal[
    "span_support_sufficient_in_frozen_counterfactuals",
    "span_support_contributor_not_sufficient",
    "span_support_association_not_supported",
    "span_support_inconclusive",
]


class ASpanProbeError(RuntimeError):
    """Base error for a frozen probe invariant failure."""


class ASpanProbeSourceGateError(ASpanProbeError):
    """Raised before a solver object exists when source evidence changed."""


class ASpanProbeGeometryError(ASpanProbeError):
    """Raised before a solver object exists when diagnostic geometry changed."""


class ASpanProbeExecutionError(ASpanProbeError):
    """Raised for a terminal numerical or persistence failure."""


class FrozenSourceUnit(BaseModel):
    """One byte-addressed source-selected ES H1 block."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_id: ParentId
    seed: int
    source_run_id: str
    source_step_index: int = Field(ge=0)
    source_proposal_index: int = Field(ge=0)
    raw_line_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_line_bytes: int = Field(gt=0)
    source_pair_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    hardware_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_a_geometry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_b_geometry_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_a_curve_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_a_total_wire_length_um: int = Field(ge=50_000, le=100_000)
    state_a_span_ratio_ppm: int = Field(ge=760_000, le=1_000_000)
    state_a_loss: float = Field(ge=0.0)
    frozen_b_loss: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_source_identity(self) -> Self:
        expected_run_id = (
            f"semifinal-paired-b-completion-{self.parent_id}-es-s{self.seed}"
        )
        if self.seed not in SEEDS or self.source_run_id != expected_run_id:
            raise ValueError("frozen source-unit run identity changed")
        if self.source_step_index != self.source_proposal_index:
            raise ValueError("frozen source-unit step/proposal identity changed")
        return self

    @property
    def source_pair_sha256(self) -> str:
        """Compatibility name used by solver-free evidence tests."""

        return self.source_pair_hash

    @property
    def state_a_length_um(self) -> int:
        """Return the frozen state-A wire length."""

        return self.state_a_total_wire_length_um

    @property
    def source_a_loss(self) -> float:
        """Return the frozen source state-A reflected-power loss."""

        return self.state_a_loss


FROZEN_SOURCE_UNITS: tuple[FrozenSourceUnit, ...] = (
    FrozenSourceUnit(
        parent_id="p01",
        seed=101,
        source_run_id="semifinal-paired-b-completion-p01-es-s101",
        source_step_index=286,
        source_proposal_index=286,
        raw_line_sha256="5aee8bfb95879ae3d335a323ebc9265845a1737a98d9cee4de7ff52772a844bb",
        raw_line_bytes=10239,
        source_pair_hash="fb98e3539cb47e05d15fd42c16ddbb8a9f6ecf55c51f4b3ea942bbd295835bf3",
        hardware_hash="52cc0dfe93a241643f2089bbd67f4d674edede0dfd38617983d9841a530a302b",
        state_a_geometry_sha256="fef0cd270b8ccf986346b3e3f1fc2933798b57f13b130720bcc6d0b5af845dba",
        state_b_geometry_sha256="c9b3f991597ee1bb7082b5f2fe5ffb41f78bf0b8723bac8d6d57bb1eff9a4ee1",
        state_a_curve_sha256="5deabecbaf9b431ced0490b76a6818def3b8eaf0fed8f487afbfb8b0cbd5467f",
        state_a_total_wire_length_um=71001,
        state_a_span_ratio_ppm=981858,
        state_a_loss=0.24551036781205307,
        frozen_b_loss=0.025679054646815754,
    ),
    FrozenSourceUnit(
        parent_id="p01",
        seed=202,
        source_run_id="semifinal-paired-b-completion-p01-es-s202",
        source_step_index=24,
        source_proposal_index=24,
        raw_line_sha256="c5c181ed9506904d323344007a90fc8b83aa2d8e0e89dfd52b43e4dc45ea7852",
        raw_line_bytes=10239,
        source_pair_hash="cc678757386ca5cbe25c34b818a151e4556b40a12e4a7ff1f7a4ff02638b40b9",
        hardware_hash="52cc0dfe93a241643f2089bbd67f4d674edede0dfd38617983d9841a530a302b",
        state_a_geometry_sha256="4afe28853419dd393a94063657422b07818ea60c3144e66868c2e0d06b0a0e04",
        state_b_geometry_sha256="c9b3f991597ee1bb7082b5f2fe5ffb41f78bf0b8723bac8d6d57bb1eff9a4ee1",
        state_a_curve_sha256="053e2469dde625bcd1024a7718c2e6c7751c2caf87b6c51fbd2309b2f38b8cf6",
        state_a_total_wire_length_um=70973,
        state_a_span_ratio_ppm=992531,
        state_a_loss=0.23755180106137028,
        frozen_b_loss=0.025679054646815754,
    ),
    FrozenSourceUnit(
        parent_id="p01",
        seed=303,
        source_run_id="semifinal-paired-b-completion-p01-es-s303",
        source_step_index=265,
        source_proposal_index=265,
        raw_line_sha256="8bc6bd0dbd80c6b31c8d83649669be58eacc01230793c3881eca3285659a1a93",
        raw_line_bytes=10241,
        source_pair_hash="59a7e7df8fe7b8c3e6a07333e84ef12099886c5971a9815891ef63e1d041f259",
        hardware_hash="52cc0dfe93a241643f2089bbd67f4d674edede0dfd38617983d9841a530a302b",
        state_a_geometry_sha256="cddd86ca4e23f96f01e1a1292fd099d2d5ce7f495289c73cf7091bb145fb7ec7",
        state_b_geometry_sha256="c9b3f991597ee1bb7082b5f2fe5ffb41f78bf0b8723bac8d6d57bb1eff9a4ee1",
        state_a_curve_sha256="a858d2416cc3771fc200799cf1e9a95dff0b5ef79469068a7d74eba2718b218a",
        state_a_total_wire_length_um=70775,
        state_a_span_ratio_ppm=999881,
        state_a_loss=0.23010531242953516,
        frozen_b_loss=0.025679054646815754,
    ),
    FrozenSourceUnit(
        parent_id="p01",
        seed=404,
        source_run_id="semifinal-paired-b-completion-p01-es-s404",
        source_step_index=209,
        source_proposal_index=209,
        raw_line_sha256="dd4c2d12291d2b6d4caa4740e0cf30cfcc4401354e2c2982169b4c26e7789826",
        raw_line_bytes=10229,
        source_pair_hash="d9aa2b8bad62c71b6da2cc988c131de1415333ddbcf2085d53f65c004d551e96",
        hardware_hash="52cc0dfe93a241643f2089bbd67f4d674edede0dfd38617983d9841a530a302b",
        state_a_geometry_sha256="aba93a41c412b6257f3b44096dacfdb7ca1cbd2fe3b08f628fe6815de4a2b490",
        state_b_geometry_sha256="c9b3f991597ee1bb7082b5f2fe5ffb41f78bf0b8723bac8d6d57bb1eff9a4ee1",
        state_a_curve_sha256="d38e519e1414c66becc32e75b64a9f6d848e72dffc23922c0ba4ed43f71f11b0",
        state_a_total_wire_length_um=70816,
        state_a_span_ratio_ppm=999368,
        state_a_loss=0.23092841432431088,
        frozen_b_loss=0.025679054646815754,
    ),
    FrozenSourceUnit(
        parent_id="p01",
        seed=505,
        source_run_id="semifinal-paired-b-completion-p01-es-s505",
        source_step_index=109,
        source_proposal_index=109,
        raw_line_sha256="be938be87c91fa65f27cfa7027e3c81c9c66133666b0a1ae32eba21439f33ab4",
        raw_line_bytes=10236,
        source_pair_hash="6ace3129ef9005e3d3d2ea804e4799f41145a7bda2719f470dcf9f7fe5b1009b",
        hardware_hash="52cc0dfe93a241643f2089bbd67f4d674edede0dfd38617983d9841a530a302b",
        state_a_geometry_sha256="d5f600cecc82b9d1517ad6a7271630757fb81f5a2b312af6102ad486fb96695e",
        state_b_geometry_sha256="c9b3f991597ee1bb7082b5f2fe5ffb41f78bf0b8723bac8d6d57bb1eff9a4ee1",
        state_a_curve_sha256="a94c3a3e7b8ab79bef292edcac7e29b4fd6088630251e559fc4a51ff0e120beb",
        state_a_total_wire_length_um=70856,
        state_a_span_ratio_ppm=999628,
        state_a_loss=0.2312005376616786,
        frozen_b_loss=0.025679054646815754,
    ),
    FrozenSourceUnit(
        parent_id="p02",
        seed=101,
        source_run_id="semifinal-paired-b-completion-p02-es-s101",
        source_step_index=164,
        source_proposal_index=164,
        raw_line_sha256="407a9eba164c40fbae4a10f5f72af73591d09f080e9de359395dfc329aebf459",
        raw_line_bytes=10184,
        source_pair_hash="754e66368ce1de867994b541a21aa5cbb07d6ef65b13536c2a00cd345d64a8c8",
        hardware_hash="2c2283aa418160650b84e8849574531cb7816f8845874952b1a0ba2c4a1b65f1",
        state_a_geometry_sha256="43679b4090d0d59e0bf2171588155c6c32d7580eab8ee1835cc30392c51dc7fb",
        state_b_geometry_sha256="dea79fb9a94126ec2406840ff973973c66bec9c1230badf438c3db8f781c4d7d",
        state_a_curve_sha256="805782847f91ec42638a8316bed7710e092ea06f5071ae99845b52943c79272f",
        state_a_total_wire_length_um=70860,
        state_a_span_ratio_ppm=999705,
        state_a_loss=0.23269669380050187,
        frozen_b_loss=0.019354919667848212,
    ),
    FrozenSourceUnit(
        parent_id="p02",
        seed=202,
        source_run_id="semifinal-paired-b-completion-p02-es-s202",
        source_step_index=283,
        source_proposal_index=283,
        raw_line_sha256="3c0fe62da3b78a57d8ef4eca0e886b98f4a07303c9a551b846ae9e2939577ca5",
        raw_line_bytes=10186,
        source_pair_hash="efa222ede3e10524564cf438b57c4a45e2def304836db7476aefde8d2f03aece",
        hardware_hash="2c2283aa418160650b84e8849574531cb7816f8845874952b1a0ba2c4a1b65f1",
        state_a_geometry_sha256="a1558e68649e27950c05fb3f41332f300b67f7f134492f98c35c64d0c4dfbcb3",
        state_b_geometry_sha256="dea79fb9a94126ec2406840ff973973c66bec9c1230badf438c3db8f781c4d7d",
        state_a_curve_sha256="bda073a94fc92d875a3e48edc98fe1dee5a58cf7b84df2f997aaa774ba0aaebd",
        state_a_total_wire_length_um=70825,
        state_a_span_ratio_ppm=999581,
        state_a_loss=0.23237516833229716,
        frozen_b_loss=0.019354919667848212,
    ),
    FrozenSourceUnit(
        parent_id="p02",
        seed=303,
        source_run_id="semifinal-paired-b-completion-p02-es-s303",
        source_step_index=204,
        source_proposal_index=204,
        raw_line_sha256="c8aaa0376ee72bd9c34b74f207242db4753f31028fb847a2955bac40cf4b57ed",
        raw_line_bytes=10185,
        source_pair_hash="5f68b76c738956d271dc194022591a1a157a552416d9fde997a6f3273f72e239",
        hardware_hash="2c2283aa418160650b84e8849574531cb7816f8845874952b1a0ba2c4a1b65f1",
        state_a_geometry_sha256="15da164a9f0fac0e5ffa995b955a6215e00a2e833aabb2c7821be76f6d530407",
        state_b_geometry_sha256="dea79fb9a94126ec2406840ff973973c66bec9c1230badf438c3db8f781c4d7d",
        state_a_curve_sha256="0384ce62f601672ea9df75bbef11f03bb8ac3c5802e880dd9c4d6f85dd298ddb",
        state_a_total_wire_length_um=70788,
        state_a_span_ratio_ppm=999102,
        state_a_loss=0.23229511875494777,
        frozen_b_loss=0.019354919667848212,
    ),
    FrozenSourceUnit(
        parent_id="p02",
        seed=404,
        source_run_id="semifinal-paired-b-completion-p02-es-s404",
        source_step_index=268,
        source_proposal_index=268,
        raw_line_sha256="a007053e3b3fed1fbcfc6ab5d01e2bfc058453f40519bd0c77a622b8d58ce408",
        raw_line_bytes=10188,
        source_pair_hash="9666760505ce32f0aa3ce7138f449931895ece5ac252bd089d5a9c2e47131733",
        hardware_hash="2c2283aa418160650b84e8849574531cb7816f8845874952b1a0ba2c4a1b65f1",
        state_a_geometry_sha256="d470860cb532733b9817b21e533ee74558fa182cc3d0088929bdc6cded9ddf70",
        state_b_geometry_sha256="dea79fb9a94126ec2406840ff973973c66bec9c1230badf438c3db8f781c4d7d",
        state_a_curve_sha256="0508ff13f26d14415f3fe502d6ab09d051edd2c122fd452c633f06f3ef314ec6",
        state_a_total_wire_length_um=70824,
        state_a_span_ratio_ppm=999816,
        state_a_loss=0.23219805776354677,
        frozen_b_loss=0.019354919667848212,
    ),
    FrozenSourceUnit(
        parent_id="p02",
        seed=505,
        source_run_id="semifinal-paired-b-completion-p02-es-s505",
        source_step_index=293,
        source_proposal_index=293,
        raw_line_sha256="5d03e51ab951bc11407e343e3ba67ac223fe70493d013ae6e308170071937178",
        raw_line_bytes=10185,
        source_pair_hash="0216ff4394e6ec4f42e26189aa50b86985c681cde410b4b4b499276a289995fc",
        hardware_hash="2c2283aa418160650b84e8849574531cb7816f8845874952b1a0ba2c4a1b65f1",
        state_a_geometry_sha256="49438c55dcc750a309c2234a3b5150861209a07e684e1c86d636e00339fe6137",
        state_b_geometry_sha256="dea79fb9a94126ec2406840ff973973c66bec9c1230badf438c3db8f781c4d7d",
        state_a_curve_sha256="a994685754903bda798eb3103a2202f5fb6e679e5f08d11040af0d2e2f9fecda",
        state_a_total_wire_length_um=70833,
        state_a_span_ratio_ppm=999921,
        state_a_loss=0.23223486715570588,
        frozen_b_loss=0.019354919667848212,
    ),
)


class DiagnosticAControl(BaseModel):
    """Diagnostic-only state-A control that may exceed production support."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: Literal["A"] = "A"
    total_wire_length_um: int = Field(ge=50_000, le=100_000)
    span_ratio_ppm: int = Field(ge=760_000, le=MAX_DIAGNOSTIC_SPAN_PPM)


class DiagnosticProposal(BaseModel):
    """One diagnostic-only intervention outside production StateControl."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_unit: FrozenSourceUnit
    hardware: HardwareSpec
    state_b: StateControl
    state_a_total_wire_length_um: int
    source_state_a_span_ratio_ppm: int
    dose_ppm: DosePPM
    effective_a_span_ratio_ppm: int

    @model_validator(mode="after")
    def validate_isolated_intervention(self) -> Self:
        expected = self.source_state_a_span_ratio_ppm + self.dose_ppm
        if self.effective_a_span_ratio_ppm != expected:
            raise ValueError("diagnostic A-span intervention is not additive")
        if self.effective_a_span_ratio_ppm > MAX_DIAGNOSTIC_SPAN_PPM:
            raise ValueError("diagnostic A span exceeds its frozen support")
        if self.state_a_total_wire_length_um != self.source_unit.state_a_total_wire_length_um:
            raise ValueError("diagnostic intervention changed state-A length")
        if self.source_state_a_span_ratio_ppm != self.source_unit.state_a_span_ratio_ppm:
            raise ValueError("diagnostic intervention changed source A span")
        return self

    @property
    def state_a(self) -> DiagnosticAControl:
        """Expose the treated A control without mutating production StateControl."""

        return DiagnosticAControl(
            total_wire_length_um=self.state_a_total_wire_length_um,
            span_ratio_ppm=self.effective_a_span_ratio_ppm,
        )


def _require_dose(value: int) -> DosePPM:
    if value == 0:
        return 0
    if value == 50_000:
        return 50_000
    if value == 100_000:
        return 100_000
    raise ASpanProbeGeometryError(f"dose {value} is outside the frozen dose set")


def build_diagnostic_proposal(
    unit: FrozenSourceUnit,
    dose_ppm: int,
) -> DiagnosticProposal:
    """Change only the source unit's A-span control by one frozen additive dose."""

    dose = _require_dose(dose_ppm)
    parent = get_frozen_parent(unit.parent_id)
    if parent.expected_hardware_hash != unit.hardware_hash:
        raise ASpanProbeGeometryError("source unit hardware differs from frozen parent")
    if parent.expected_state_b_geometry_hash != unit.state_b_geometry_sha256:
        raise ASpanProbeGeometryError("source unit state B differs from frozen parent")
    return DiagnosticProposal(
        source_unit=unit,
        hardware=parent.hardware,
        state_b=parent.state_b,
        state_a_total_wire_length_um=unit.state_a_total_wire_length_um,
        source_state_a_span_ratio_ppm=unit.state_a_span_ratio_ppm,
        dose_ppm=dose,
        effective_a_span_ratio_ppm=unit.state_a_span_ratio_ppm + dose,
    )


class SolverPlanItem(BaseModel):
    """One position in the exact 32-call subprocess plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_index: int = Field(ge=0, lt=PLANNED_CALLS)
    event_kind: Literal["b_replay", "a_probe"]
    parent_id: ParentId
    unit_index: int | None = Field(default=None, ge=0, lt=len(FROZEN_SOURCE_UNITS))
    dose_ppm: DosePPM | None = None

    @model_validator(mode="after")
    def validate_plan_item(self) -> Self:
        if self.event_kind == "b_replay":
            if self.unit_index is not None or self.dose_ppm is not None:
                raise ValueError("B replay cannot name an A intervention")
        elif self.unit_index is None or self.dose_ppm is None:
            raise ValueError("A probe must name its source unit and dose")
        elif FROZEN_SOURCE_UNITS[self.unit_index].parent_id != self.parent_id:
            raise ValueError("A probe plan parent differs from source unit")
        return self

    @property
    def state(self) -> Literal["A", "B"]:
        """Return the physical state represented by this call."""

        return "B" if self.event_kind == "b_replay" else "A"

    @property
    def source_unit_index(self) -> int | None:
        """Return the frozen source-unit position for A calls."""

        return self.unit_index


def build_solver_plan() -> tuple[SolverPlanItem, ...]:
    """Return B replays, all controls, +50k, then +100k in frozen table order."""

    plan: list[SolverPlanItem] = [
        SolverPlanItem(call_index=0, event_kind="b_replay", parent_id="p01"),
        SolverPlanItem(call_index=1, event_kind="b_replay", parent_id="p02"),
    ]
    for dose in DOSES_PPM:
        for unit_index, unit in enumerate(FROZEN_SOURCE_UNITS):
            plan.append(
                SolverPlanItem(
                    call_index=len(plan),
                    event_kind="a_probe",
                    parent_id=unit.parent_id,
                    unit_index=unit_index,
                    dose_ppm=dose,
                )
            )
    if len(plan) != PLANNED_CALLS:
        raise ASpanProbeExecutionError("solver plan does not contain exactly 32 calls")
    return tuple(plan)


class DiagnosticTrajectoryAudit(BaseModel):
    """Physical checks for one 21-point diagnostic trajectory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    point_count: int = TRAJECTORY_POINT_COUNT
    valid: bool
    minimum_clearance_m: float = Field(ge=MINIMUM_SEGMENT_M)
    minimum_pitch_m: float = Field(ge=MINIMUM_PITCH_M)
    minimum_height_m: float = Field(gt=0.0)
    maximum_adjacent_node_displacement_m: float = Field(ge=0.0)
    actual_full_width_m: float = Field(gt=0.0, le=BOX_SIZE_UM * 1e-6)
    geometry_sha256: tuple[str, ...]

    @model_validator(mode="after")
    def validate_complete_audit(self) -> Self:
        if not self.valid or len(self.geometry_sha256) != TRAJECTORY_POINT_COUNT:
            raise ValueError("diagnostic trajectory is not a complete physical pass")
        return self


class DiagnosticTrajectory(BaseModel):
    """One source unit, one dose, and all solver-free trajectory geometries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal: DiagnosticProposal
    geometries: tuple[Geometry, ...]
    audit: DiagnosticTrajectoryAudit

    @model_validator(mode="after")
    def validate_geometry_count(self) -> Self:
        if len(self.geometries) != TRAJECTORY_POINT_COUNT:
            raise ValueError("diagnostic trajectory does not contain 21 geometries")
        return self


def _canonical_sha256(payload: object) -> str:
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ASpanProbeError(f"cannot canonicalize diagnostic evidence: {error}") from error
    return hashlib.sha256(encoded).hexdigest()


def _diagnostic_geometry_sha256(
    proposal: DiagnosticProposal,
    trajectory_index: int,
    length_um: int,
    span_ppm: int,
    geometry: Geometry,
) -> str:
    return _canonical_sha256(
        {
            "schema_version": 1,
            "study_id": STUDY_ID,
            "hardware": proposal.hardware.model_dump(mode="json"),
            "trajectory_index": trajectory_index,
            "total_wire_length_um": length_um,
            "span_ratio_ppm": span_ppm,
            "vertices": geometry.vertices,
            "faces": geometry.faces,
        }
    )


def _full_width_m(geometry: Geometry) -> float:
    x_values = [vertex[0] for vertex in geometry.vertices]
    if not x_values:
        raise ASpanProbeGeometryError("diagnostic geometry is empty")
    return max(x_values) - min(x_values)


def build_diagnostic_trajectory(
    unit: FrozenSourceUnit,
    dose_ppm: int,
) -> DiagnosticTrajectory:
    """Build and audit the unchanged 21-point integer interpolation."""

    proposal = build_diagnostic_proposal(unit, dose_ppm)
    geometries: list[Geometry] = []
    hashes: list[str] = []
    minimum_clearance = math.inf
    minimum_pitch = math.inf
    minimum_height = math.inf
    maximum_displacement = 0.0
    previous: Geometry | None = None
    try:
        for index in range(TRAJECTORY_POINT_COUNT):
            length_um = _interpolate_integer(
                proposal.state_a_total_wire_length_um,
                proposal.state_b.total_wire_length_um,
                index,
            )
            span_ppm = _interpolate_integer(
                proposal.effective_a_span_ratio_ppm,
                proposal.state_b.span_ratio_ppm,
                index,
            )
            geometry = _build_quantized_geometry(
                proposal.hardware,
                length_um,
                span_ppm,
                f"a_span_probe_{unit.parent_id}_{unit.seed}_{dose_ppm}_{index:02d}",
            )
            geometries.append(geometry)
            minimum_clearance = min(
                minimum_clearance,
                minimum_nonadjacent_clearance(geometry),
            )
            minimum_pitch = min(
                minimum_pitch,
                float(geometry.metadata["minimum_pitch_m"]),
            )
            minimum_height = min(
                minimum_height,
                float(geometry.metadata["derived_height_m"]),
            )
            hashes.append(
                _diagnostic_geometry_sha256(
                    proposal,
                    index,
                    length_um,
                    span_ppm,
                    geometry,
                )
            )
            if previous is not None:
                if len(previous.vertices) != len(geometry.vertices):
                    raise ASpanProbeGeometryError("diagnostic trajectory topology changed")
                maximum_displacement = max(
                    maximum_displacement,
                    max(
                        math.dist(left, right)
                        for left, right in zip(
                            previous.vertices,
                            geometry.vertices,
                            strict=True,
                        )
                    ),
                )
            previous = geometry
    except (KeyError, PairedMeanderError, ValueError) as error:
        raise ASpanProbeGeometryError(
            f"diagnostic geometry failed for {unit.parent_id}/s{unit.seed}/d{dose_ppm}: "
            f"{error}"
        ) from error
    if len(geometries) != TRAJECTORY_POINT_COUNT:
        raise ASpanProbeGeometryError("diagnostic trajectory ended before 21 points")
    endpoint_geometry = geometries[0]
    if dose_ppm == 0:
        source_state = StateControl(
            state="A",
            total_wire_length_um=unit.state_a_total_wire_length_um,
            span_ratio_ppm=unit.state_a_span_ratio_ppm,
        )
        source_geometry = build_state_geometry(proposal.hardware, source_state)
        if (
            endpoint_geometry.vertices != source_geometry.vertices
            or endpoint_geometry.faces != source_geometry.faces
            or state_geometry_hash(proposal.hardware, source_state, endpoint_geometry)
            != unit.state_a_geometry_sha256
        ):
            raise ASpanProbeGeometryError("dose-zero A geometry differs from source identity")
    audit = DiagnosticTrajectoryAudit(
        valid=True,
        minimum_clearance_m=minimum_clearance,
        minimum_pitch_m=minimum_pitch,
        minimum_height_m=minimum_height,
        maximum_adjacent_node_displacement_m=maximum_displacement,
        actual_full_width_m=_full_width_m(endpoint_geometry),
        geometry_sha256=tuple(hashes),
    )
    return DiagnosticTrajectory(
        proposal=proposal,
        geometries=tuple(geometries),
        audit=audit,
    )


class DoseWidthRange(BaseModel):
    """Observed endpoint width range for one frozen dose."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dose_ppm: DosePPM
    minimum_mm: float = Field(gt=0.0)
    maximum_mm: float = Field(gt=0.0)


class GeometryReleaseAudit(BaseModel):
    """All thirty trajectories and their solver-free aggregate gate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["passed"] = "passed"
    trajectory_count: int = 30
    geometry_count: int = PLANNED_GEOMETRIES
    trajectories: tuple[DiagnosticTrajectory, ...]
    dose_width_ranges: tuple[DoseWidthRange, ...]
    minimum_pitch_mm: float = Field(ge=MINIMUM_PITCH_M * 1_000.0)
    minimum_clearance_mm: float = Field(ge=MINIMUM_SEGMENT_M * 1_000.0)

    @model_validator(mode="after")
    def validate_release_counts(self) -> Self:
        if len(self.trajectories) != 30 or len(self.dose_width_ranges) != 3:
            raise ValueError("geometry release does not contain the frozen matrix")
        if sum(len(item.geometries) for item in self.trajectories) != PLANNED_GEOMETRIES:
            raise ValueError("geometry release does not contain exactly 630 geometries")
        return self


def audit_geometry_release() -> GeometryReleaseAudit:
    """Build all 630 geometries and enforce the preregistered known answers."""

    trajectories = tuple(
        build_diagnostic_trajectory(unit, dose)
        for dose in DOSES_PPM
        for unit in FROZEN_SOURCE_UNITS
    )
    width_ranges = tuple(
        DoseWidthRange(
            dose_ppm=dose,
            minimum_mm=min(
                item.audit.actual_full_width_m * 1_000.0
                for item in trajectories
                if item.proposal.dose_ppm == dose
            ),
            maximum_mm=max(
                item.audit.actual_full_width_m * 1_000.0
                for item in trajectories
                if item.proposal.dose_ppm == dose
            ),
        )
        for dose in DOSES_PPM
    )
    minimum_pitch_mm = min(item.audit.minimum_pitch_m for item in trajectories) * 1_000.0
    minimum_clearance_mm = (
        min(item.audit.minimum_clearance_m for item in trajectories) * 1_000.0
    )
    expected_widths = (
        (29.945750, 30.486440),
        (31.445750, 31.986440),
        (32.945750, 33.486440),
    )
    actual_widths = tuple(
        (round(item.minimum_mm, 6), round(item.maximum_mm, 6))
        for item in width_ranges
    )
    if actual_widths != expected_widths:
        raise ASpanProbeGeometryError(
            f"diagnostic endpoint width ranges changed: {actual_widths!r}"
        )
    if round(minimum_pitch_mm, 6) != 3.612745:
        raise ASpanProbeGeometryError("diagnostic minimum pitch changed")
    if round(minimum_clearance_mm, 6) != 0.203343:
        raise ASpanProbeGeometryError("diagnostic minimum clearance changed")
    return GeometryReleaseAudit(
        trajectories=trajectories,
        dose_width_ranges=width_ranges,
        minimum_pitch_mm=minimum_pitch_mm,
        minimum_clearance_mm=minimum_clearance_mm,
    )


def classify_endpoint(
    high_dose_improvements: int,
    monotonic_responses: int,
    p01_crossings: int,
    p02_crossings: int,
) -> Endpoint:
    """Apply the four mutually exclusive preregistered endpoint rules."""

    counts = (high_dose_improvements, monotonic_responses)
    parent_counts = (p01_crossings, p02_crossings)
    if any(isinstance(value, bool) or not 0 <= value <= 10 for value in counts):
        raise ValueError("probe response count lies outside [0,10]")
    if any(isinstance(value, bool) or not 0 <= value <= 5 for value in parent_counts):
        raise ValueError("probe parent crossing count lies outside [0,5]")
    total_crossings = p01_crossings + p02_crossings
    if (
        high_dose_improvements >= 9
        and monotonic_responses >= 8
        and total_crossings >= 5
        and p01_crossings >= 2
        and p02_crossings >= 2
    ):
        return "span_support_sufficient_in_frozen_counterfactuals"
    if high_dose_improvements >= 9 and monotonic_responses >= 8:
        return "span_support_contributor_not_sufficient"
    if high_dose_improvements <= 5 and total_crossings == 0:
        return "span_support_association_not_supported"
    return "span_support_inconclusive"


_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SOURCE_AGENTS: tuple[Agent, Agent] = (
    "random-b-completion",
    "es-b-completion",
)


class SourceGateInputs(BaseModel):
    """Immutable evidence proven before geometry release or solver construction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    preregistration_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    execution_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_manifest_entry_count: int
    accepted_record_count: int
    h1_count: int
    h2_count: int
    p01_h1_count: int
    p02_h1_count: int
    es_h1_counts: tuple[int, ...]
    source_units: tuple[FrozenSourceUnit, ...]
    runtime_path_blobs: dict[str, str]
    implementation_blob: str = Field(pattern=r"^[0-9a-f]{40}$")

    @model_validator(mode="after")
    def validate_frozen_gate_answers(self) -> Self:
        expected = (
            self.source_commit == SOURCE_COMMIT,
            self.preregistration_commit == PREREGISTRATION_COMMIT,
            self.source_manifest_sha256 == SOURCE_MANIFEST_SHA256,
            self.source_manifest_entry_count == SOURCE_MANIFEST_ENTRY_COUNT,
            self.accepted_record_count == SOURCE_ACCEPTED_COUNT,
            self.h1_count == SOURCE_H1_COUNT,
            self.h2_count == SOURCE_H2_COUNT,
            self.p01_h1_count == SOURCE_P01_H1_COUNT,
            self.p02_h1_count == SOURCE_P02_H1_COUNT,
            self.es_h1_counts == SOURCE_ES_H1_COUNTS,
            self.source_units == FROZEN_SOURCE_UNITS,
            self.runtime_path_blobs
            == {path.as_posix(): blob for path, blob in RUNTIME_PATH_BLOBS.items()},
        )
        if not all(expected):
            raise ValueError("source-gate aggregate differs from preregistration")
        return self


class _SourceReplayRow(BaseModel):
    """One independently revalidated source log row plus its exact LF bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    record: PairedEvaluationRecord
    reference: BCompletionRecordRef
    raw_line_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_line_bytes: int = Field(gt=0)


def _source_gate_error(
    message: str,
    error: Exception | None = None,
) -> NoReturn:
    if error is None:
        raise ASpanProbeSourceGateError(message)
    raise ASpanProbeSourceGateError(message) from error


def _resolve_commit(repo_root: Path, value: str, label: str) -> str:
    if _FULL_COMMIT.fullmatch(value) is None:
        _source_gate_error(f"{label} must be a full lowercase commit")
    try:
        resolved = _git(repo_root, "rev-parse", f"{value}^{{commit}}").decode(
            "ascii"
        ).strip()
    except (StageAGateError, UnicodeDecodeError) as error:
        _source_gate_error(f"cannot resolve {label}", error)
    if resolved != value:
        _source_gate_error(f"{label} does not resolve to its frozen full commit")
    return resolved


def _git_object_id(repo_root: Path, commit: str, path: Path) -> str:
    try:
        value = _git(
            repo_root,
            "rev-parse",
            f"{commit}:{path.as_posix()}",
        ).decode("ascii").strip()
    except (StageAGateError, UnicodeDecodeError) as error:
        _source_gate_error(f"cannot resolve Git blob for {path.as_posix()}", error)
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        _source_gate_error(f"invalid Git blob identity for {path.as_posix()}")
    return value


def _filtered_worktree_blob(repo_root: Path, path: Path) -> str:
    """Identify text worktree content through Git''s configured clean filter."""

    try:
        value = _git(
            repo_root,
            "hash-object",
            f"--path={path.as_posix()}",
            "--",
            path.as_posix(),
        ).decode("ascii").strip()
    except (StageAGateError, UnicodeDecodeError) as error:
        _source_gate_error(
            f"cannot hash filtered worktree path {path.as_posix()}",
            error,
        )
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        _source_gate_error(
            f"invalid filtered worktree identity for {path.as_posix()}"
        )
    return value


def _workspace_bytes(repo_root: Path, path: Path, label: str) -> bytes:
    try:
        return (repo_root / path).read_bytes()
    except OSError as error:
        _source_gate_error(f"cannot read {label}", error)


def _json_object(payload: bytes, label: str) -> dict[str, object]:
    try:
        value: object = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _source_gate_error(f"cannot parse {label}", error)
    if not isinstance(value, dict):
        _source_gate_error(f"{label} is not a JSON object")
    return cast(dict[str, object], value)


def _manifest_hashes(entry: dict[str, object], run_id: str) -> dict[str, str]:
    value = entry.get("sha256")
    if not isinstance(value, dict):
        _source_gate_error(f"source manifest SHA map is invalid: {run_id}")
    output: dict[str, str] = {}
    for filename in (LOG_FILENAME, SUMMARY_FILENAME):
        digest = value.get(filename)
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            _source_gate_error(
                f"source manifest {filename} SHA is invalid: {run_id}"
            )
        output[filename] = digest
    return output


def _strict_lf_lines(payload: bytes, label: str) -> tuple[bytes, ...]:
    if not payload or not payload.endswith(b"\n") or b"\r" in payload:
        _source_gate_error(f"{label} is not non-empty LF-only JSONL")
    lines = tuple(payload.splitlines(keepends=True))
    if any(not line.endswith(b"\n") for line in lines):
        _source_gate_error(f"{label} contains an unterminated line")
    return lines


def _source_run_id(parent_id: ParentId, agent: Agent, seed: int) -> str:
    slug = "random" if agent == "random-b-completion" else "es"
    return f"semifinal-paired-b-completion-{parent_id}-{slug}-s{seed}"


def _validate_source_summary(
    payload: bytes,
    entry: dict[str, object],
    run_id: str,
    seed: int,
) -> None:
    summary = _json_object(payload, f"source summary {run_id}")
    expected = (
        summary.get("run_id") == run_id,
        summary.get("seed") == seed,
        summary.get("status") == "completed",
        summary.get("steps_completed") == 300,
        summary.get("evaluation_budget") == 300,
        summary.get("proposal_attempts") == 300,
        summary.get("rejected_proposals") == 0,
        summary.get("solver_mode_counts") == {"subprocess": 600},
        entry.get("run_id") == run_id,
        entry.get("seed") == seed,
        entry.get("steps_completed") == 300,
        entry.get("solver_mode_counts") == {"subprocess": 600},
        entry.get("overwritten") is False,
    )
    if not all(expected):
        _source_gate_error(f"source summary or manifest terminal changed: {run_id}")


def _read_source_artifact(
    repo_root: Path,
    implementation_commit: str,
    execution_commit: str,
    path: Path,
    expected_sha256: str,
    label: str,
) -> bytes:
    try:
        source = _git_blob(repo_root, SOURCE_COMMIT, path)
        implementation = _git_blob(repo_root, implementation_commit, path)
        execution = _git_blob(repo_root, execution_commit, path)
    except StageAGateError as error:
        _source_gate_error(f"cannot read committed {label}", error)
    workspace = _workspace_bytes(repo_root, path, label)
    if not (
        source == implementation == execution == workspace
        and _sha256(source) == expected_sha256
    ):
        _source_gate_error(f"{label} differs from frozen source bytes")
    return source


def _source_replay_row(
    raw_line: bytes,
    parent_id: ParentId,
    agent: Agent,
    seed: int,
    run_id: str,
    row_index: int,
) -> _SourceReplayRow:
    try:
        record = PairedEvaluationRecord.model_validate_json(raw_line)
        reference = record_ref(record, parent_id, agent, seed)
    except (ValueError, PairedMeanderError) as error:
        _source_gate_error(
            f"source replay failed at {run_id} row {row_index}",
            error,
        )
    if (
        record.run_id != run_id
        or record.step_index != row_index
        or record.proposal_index != row_index
    ):
        _source_gate_error(f"source row order changed: {run_id} row {row_index}")
    return _SourceReplayRow(
        record=record,
        reference=reference,
        raw_line_sha256=_sha256(raw_line),
        raw_line_bytes=len(raw_line),
    )


def _validate_selected_source_unit(
    unit: FrozenSourceUnit,
    selected: _SourceReplayRow,
) -> None:
    reference = selected.reference
    record = selected.record
    parent = get_frozen_parent(unit.parent_id)
    state_a_metrics = record.evaluation.metrics.state_a
    state_b_metrics = record.evaluation.metrics.state_b
    curve_hash = canonical_curve_sha256(
        record.evaluation.state_a_curve.model_dump(mode="json")
    )
    checks = (
        reference.parent_id == unit.parent_id,
        reference.agent == "es-b-completion",
        reference.seed == unit.seed,
        reference.run_id == unit.source_run_id,
        reference.step_index == unit.source_step_index,
        reference.proposal_index == unit.source_proposal_index,
        reference.pair_hash == unit.source_pair_hash,
        reference.hardware_hash == unit.hardware_hash,
        reference.state_a_geometry_hash == unit.state_a_geometry_sha256,
        reference.state_b_geometry_hash == unit.state_b_geometry_sha256,
        reference.proposal.hardware == parent.hardware,
        reference.proposal.state_b == parent.state_b,
        reference.proposal.state_a.total_wire_length_um
        == unit.state_a_total_wire_length_um,
        reference.proposal.state_a.span_ratio_ppm == unit.state_a_span_ratio_ppm,
        selected.raw_line_sha256 == unit.raw_line_sha256,
        selected.raw_line_bytes == unit.raw_line_bytes,
        curve_hash == unit.state_a_curve_sha256,
        state_a_metrics.reflected_power_fraction == unit.state_a_loss,
        state_b_metrics.reflected_power_fraction == unit.frozen_b_loss,
        record.evaluation.state_b_geometry_hash == unit.state_b_geometry_sha256,
        canonical_curve_sha256(
            record.evaluation.state_b_curve.model_dump(mode="json")
        )
        == EXPECTED_B_CURVE_SHA256[unit.parent_id],
    )
    if not all(checks):
        _source_gate_error(
            f"frozen source unit changed: {unit.parent_id}/s{unit.seed}"
        )


def validate_source_gates(
    repo_root: Path,
    implementation_commit: str,
    execution_commit: str | None = None,
) -> SourceGateInputs:
    """Replay all frozen bytes before any adapter or solver object may exist."""

    root = repo_root.resolve()
    implementation = _resolve_commit(
        root,
        implementation_commit,
        "implementation commit",
    )
    execution = _resolve_commit(
        root,
        implementation if execution_commit is None else execution_commit,
        "execution commit",
    )
    source = _resolve_commit(root, SOURCE_COMMIT, "source commit")
    preregistration = _resolve_commit(
        root,
        PREREGISTRATION_COMMIT,
        "preregistration commit",
    )
    try:
        head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
        _require_ancestor(root, source, preregistration)
        _require_ancestor(root, source, implementation)
        _require_ancestor(root, preregistration, implementation)
        _require_ancestor(root, implementation, execution)
    except (StageAGateError, UnicodeDecodeError) as error:
        _source_gate_error("source commit ancestry gate failed", error)
    if head != execution:
        _source_gate_error("execution commit is not the current HEAD")

    try:
        source_manifest = _git_blob(root, source, MANIFEST_PATH)
        implementation_manifest = _git_blob(root, implementation, MANIFEST_PATH)
        execution_manifest = _git_blob(root, execution, MANIFEST_PATH)
    except StageAGateError as error:
        _source_gate_error("cannot read committed source manifest", error)
    workspace_manifest = _workspace_bytes(root, MANIFEST_PATH, "source manifest")
    if not (
        source_manifest
        == implementation_manifest
        == execution_manifest
        == workspace_manifest
        and _sha256(source_manifest) == SOURCE_MANIFEST_SHA256
    ):
        _source_gate_error("source manifest bytes changed")
    try:
        manifest_entries = _manifest_entries(source_manifest, "source manifest")
        manifest_index = _manifest_index(manifest_entries, "source manifest")
    except StageAGateError as error:
        _source_gate_error("cannot validate source manifest", error)
    if len(manifest_entries) != SOURCE_MANIFEST_ENTRY_COUNT:
        _source_gate_error("source manifest entry count changed")
    if RUN_ID in manifest_index:
        _source_gate_error("probe run ID already exists in source manifest")

    preregistration_blob = _git_blob(root, preregistration, PREREGISTRATION_PATH)
    if (
        _sha256(preregistration_blob) != PREREGISTRATION_DOCUMENT_SHA256
        or _workspace_bytes(root, PREREGISTRATION_PATH, "preregistration")
        != preregistration_blob
        or _git_blob(root, execution, PREREGISTRATION_PATH) != preregistration_blob
    ):
        _source_gate_error("preregistration document bytes changed")
    _read_source_artifact(
        root,
        implementation,
        execution,
        SOURCE_APPENDIX_PATH,
        SOURCE_APPENDIX_SHA256,
        "source appendix",
    )
    _read_source_artifact(
        root,
        implementation,
        execution,
        SOURCE_REPORT_PATH,
        SOURCE_REPORT_SHA256,
        "source report",
    )

    runtime_blobs: dict[str, str] = {}
    for path, expected_blob in RUNTIME_PATH_BLOBS.items():
        identities = tuple(
            _git_object_id(root, commit, path)
            for commit in (source, implementation, execution)
        )
        if (
            identities != (expected_blob, expected_blob, expected_blob)
            or _filtered_worktree_blob(root, path) != expected_blob
        ):
            _source_gate_error(f"frozen runtime path changed: {path.as_posix()}")
        runtime_blobs[path.as_posix()] = expected_blob

    try:
        implementation_bytes = _git_blob(root, implementation, IMPLEMENTATION_PATH)
        execution_bytes = _git_blob(root, execution, IMPLEMENTATION_PATH)
    except StageAGateError as error:
        _source_gate_error("cannot read committed probe implementation", error)
    if not (
        implementation_bytes == execution_bytes
        and _workspace_bytes(root, IMPLEMENTATION_PATH, "probe implementation")
        == implementation_bytes
    ):
        _source_gate_error("probe implementation differs from committed bytes")
    implementation_blob = _git_object_id(root, implementation, IMPLEMENTATION_PATH)

    accepted = 0
    h1 = 0
    h2 = 0
    parent_h1: dict[ParentId, int] = {"p01": 0, "p02": 0}
    es_counts: dict[tuple[ParentId, int], int] = {}
    es_candidates: dict[tuple[ParentId, int], list[_SourceReplayRow]] = {}
    for parent_id in PARENTS:
        for agent in _SOURCE_AGENTS:
            for seed in SEEDS:
                run_id = _source_run_id(parent_id, agent, seed)
                entry = manifest_index.get(run_id)
                if entry is None:
                    _source_gate_error(f"source manifest entry is missing: {run_id}")
                hashes = _manifest_hashes(entry, run_id)
                run_root = Path("artifacts/runs") / run_id
                log_path = run_root / LOG_FILENAME
                summary_path = run_root / SUMMARY_FILENAME
                log_payload = _read_source_artifact(
                    root,
                    implementation,
                    execution,
                    log_path,
                    hashes[LOG_FILENAME],
                    f"source log {run_id}",
                )
                summary_payload = _read_source_artifact(
                    root,
                    implementation,
                    execution,
                    summary_path,
                    hashes[SUMMARY_FILENAME],
                    f"source summary {run_id}",
                )
                _validate_source_summary(summary_payload, entry, run_id, seed)
                lines = _strict_lf_lines(log_payload, f"source log {run_id}")
                if len(lines) != 300:
                    _source_gate_error(
                        f"source log does not contain 300 rows: {run_id}"
                    )
                cell_h1 = 0
                for row_index, raw_line in enumerate(lines):
                    replay = _source_replay_row(
                        raw_line,
                        parent_id,
                        agent,
                        seed,
                        run_id,
                        row_index,
                    )
                    accepted += 1
                    if replay.reference.h1:
                        h1 += 1
                        cell_h1 += 1
                        parent_h1[parent_id] += 1
                        if agent == "es-b-completion":
                            es_candidates.setdefault(
                                (parent_id, seed),
                                [],
                            ).append(replay)
                    if replay.reference.h2:
                        h2 += 1
                if agent == "es-b-completion":
                    es_counts[(parent_id, seed)] = cell_h1

    aggregate = (
        accepted,
        h1,
        h2,
        parent_h1["p01"],
        parent_h1["p02"],
    )
    if aggregate != (
        SOURCE_ACCEPTED_COUNT,
        SOURCE_H1_COUNT,
        SOURCE_H2_COUNT,
        SOURCE_P01_H1_COUNT,
        SOURCE_P02_H1_COUNT,
    ):
        _source_gate_error(f"source replay aggregate changed: {aggregate!r}")
    ordered_es_counts = tuple(
        es_counts[(parent_id, seed)]
        for parent_id in PARENTS
        for seed in SEEDS
    )
    if ordered_es_counts != SOURCE_ES_H1_COUNTS:
        _source_gate_error("source ES H1 cell counts changed")
    for unit in FROZEN_SOURCE_UNITS:
        candidates = es_candidates.get((unit.parent_id, unit.seed), [])
        if not candidates:
            _source_gate_error(
                f"source ES H1 cohort is empty: {unit.parent_id}/s{unit.seed}"
            )
        selected = min(
            candidates,
            key=lambda row: (
                row.reference.worst_reflected_power_fraction,
                row.reference.pair_hash,
                row.reference.run_id,
                row.reference.step_index,
                row.reference.proposal_index,
            ),
        )
        _validate_selected_source_unit(unit, selected)

    return SourceGateInputs(
        source_commit=source,
        preregistration_commit=preregistration,
        implementation_commit=implementation,
        execution_commit=execution,
        source_manifest_sha256=SOURCE_MANIFEST_SHA256,
        source_manifest_entry_count=SOURCE_MANIFEST_ENTRY_COUNT,
        accepted_record_count=accepted,
        h1_count=h1,
        h2_count=h2,
        p01_h1_count=parent_h1["p01"],
        p02_h1_count=parent_h1["p02"],
        es_h1_counts=ordered_es_counts,
        source_units=FROZEN_SOURCE_UNITS,
        runtime_path_blobs=runtime_blobs,
        implementation_blob=implementation_blob,
    )


class ProbeRunConfig(BaseModel):
    """Exact numerical configuration hashed into the terminal run summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    study_id: str = STUDY_ID
    run_id: str = RUN_ID
    seed: int = 0
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    preregistration_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    implementation_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    execution_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    implementation_blob: str = Field(pattern=r"^[0-9a-f]{40}$")
    source_manifest_entry_count: int
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preregistration_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_appendix_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_path_blobs: dict[str, str]
    source_units: tuple[FrozenSourceUnit, ...]
    doses_ppm: tuple[DosePPM, DosePPM, DosePPM] = DOSES_PPM
    planned_solver_calls: int = PLANNED_CALLS
    planned_b_replays: int = PLANNED_B_REPLAYS
    planned_a_solves: int = PLANNED_A_SOLVES
    planned_geometry_count: int = PLANNED_GEOMETRIES
    state_a_frequency_hz: tuple[float, ...] = STATE_A_FREQUENCIES_HZ
    state_b_frequency_hz: tuple[float, ...] = STATE_B_FREQUENCIES_HZ
    nec2_segments_per_wavelength: int = NEC2_SEGMENTS_PER_WAVELENGTH
    no_fallback: Literal[True] = True
    far_field_requested: Literal[False] = False
    openems_cross_check_authorized: Literal[False] = False
    verdict_ceiling: Literal["insufficient_evidence"] = "insufficient_evidence"

    @model_validator(mode="after")
    def validate_frozen_config(self) -> Self:
        expected = (
            self.study_id == STUDY_ID,
            self.run_id == RUN_ID,
            self.seed == 0,
            self.source_commit == SOURCE_COMMIT,
            self.preregistration_commit == PREREGISTRATION_COMMIT,
            self.source_manifest_entry_count == SOURCE_MANIFEST_ENTRY_COUNT,
            self.source_manifest_sha256 == SOURCE_MANIFEST_SHA256,
            self.preregistration_document_sha256
            == PREREGISTRATION_DOCUMENT_SHA256,
            self.source_appendix_sha256 == SOURCE_APPENDIX_SHA256,
            self.source_report_sha256 == SOURCE_REPORT_SHA256,
            self.runtime_path_blobs
            == {path.as_posix(): blob for path, blob in RUNTIME_PATH_BLOBS.items()},
            self.source_units == FROZEN_SOURCE_UNITS,
            self.doses_ppm == DOSES_PPM,
            self.planned_solver_calls == PLANNED_CALLS,
            self.planned_b_replays == PLANNED_B_REPLAYS,
            self.planned_a_solves == PLANNED_A_SOLVES,
            self.planned_geometry_count == PLANNED_GEOMETRIES,
            self.state_a_frequency_hz == STATE_A_FREQUENCIES_HZ,
            self.state_b_frequency_hz == STATE_B_FREQUENCIES_HZ,
            self.nec2_segments_per_wavelength
            == NEC2_SEGMENTS_PER_WAVELENGTH,
        )
        if not all(expected):
            raise ValueError("probe numerical configuration changed")
        return self


class ProbeBReplayEvent(BaseModel):
    """One of the first two frozen B replay calls."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal["a_span_probe_b_replay"] = "a_span_probe_b_replay"
    call_index: int = Field(ge=0, le=1)
    solver_mode: Literal["subprocess"] = "subprocess"
    parent_id: ParentId
    canonical_curve_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_b_curve: SearchCurve
    timestamp: str | None = None


class ProbeAEvaluationEvent(BaseModel):
    """One fresh state-A call with the exact analysis-facing evidence schema."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: Literal["a_span_probe_a_evaluation"] = (
        "a_span_probe_a_evaluation"
    )
    call_index: int = Field(ge=2, lt=PLANNED_CALLS)
    solver_mode: Literal["subprocess"] = "subprocess"
    parent_id: ParentId
    seed: int
    source_pair_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_run_id: str
    source_step_index: int = Field(ge=0)
    source_proposal_index: int = Field(ge=0)
    dose_ppm: DosePPM
    effective_a_span_ratio_ppm: int = Field(
        ge=760_000,
        le=MAX_DIAGNOSTIC_SPAN_PPM,
    )
    state_a_curve: SearchCurve
    canonical_curve_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_b_loss: float = Field(ge=0.0)
    trajectory_valid: bool
    actual_full_width_mm: float = Field(gt=0.0, lt=40.0)
    minimum_clearance_mm: float = Field(ge=MINIMUM_SEGMENT_M * 1_000.0)
    state_a_selected_index: int = Field(ge=0, lt=len(STATE_A_FREQUENCIES_HZ))
    state_a_selected_frequency_hz: float
    state_a_selected_s11_db: float
    state_a_loss: float = Field(ge=0.0)
    state_a_valid: bool
    hybrid_loss: float = Field(ge=0.0)
    diagnostic_pair_valid: bool
    diagnostic_reference_crossing: bool
    source_box_size_um: int = BOX_SIZE_UM
    counterfactual_only: bool
    outside_original_span_support: bool
    physical_40mm_trajectory_valid: bool
    eligible_for_original_candidate_pool: Literal[False] = False
    eligible_for_original_h1_h2: Literal[False] = False
    eligible_for_original_agent_comparison: Literal[False] = False
    timestamp: str | None = None


ProbeEvent = ProbeBReplayEvent | ProbeAEvaluationEvent


class ProbeEndpointAggregate(BaseModel):
    """Complete ten-block endpoint sufficient for the terminal summary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    high_dose_improvements: int = Field(ge=0, le=10)
    monotonic_responses: int = Field(ge=0, le=10)
    p01_crossings: int = Field(ge=0, le=5)
    p02_crossings: int = Field(ge=0, le=5)
    endpoint: Endpoint

    @model_validator(mode="after")
    def validate_endpoint(self) -> Self:
        if self.endpoint != classify_endpoint(
            self.high_dose_improvements,
            self.monotonic_responses,
            self.p01_crossings,
            self.p02_crossings,
        ):
            raise ValueError("probe endpoint aggregate does not classify")
        return self


class ProbeRunSummary(BaseModel):
    """Archive-compatible terminal summary consumed by strict analysis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    study_id: str = STUDY_ID
    run_id: str = RUN_ID
    status: Literal["completed"] = "completed"
    started_at: datetime
    finished_at: datetime
    seed: int = 0
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    config: ProbeRunConfig
    steps_completed: int = PLANNED_CALLS
    solver_calls_completed: int = PLANNED_CALLS
    solver_mode_counts: dict[str, int]
    b_replay_calls: int = PLANNED_B_REPLAYS
    a_solver_calls: int = PLANNED_A_SOLVES
    endpoint: Endpoint
    high_dose_improvements: int = Field(ge=0, le=10)
    monotonic_responses: int = Field(ge=0, le=10)
    p01_crossings: int = Field(ge=0, le=5)
    p02_crossings: int = Field(ge=0, le=5)
    verdict_ceiling: Literal["insufficient_evidence"] = "insufficient_evidence"
    openems_calls: int = 0
    log_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    termination_reason: str = "frozen 32-call NEC2 probe completed"

    @model_validator(mode="after")
    def validate_complete_summary(self) -> Self:
        aggregate = ProbeEndpointAggregate(
            high_dose_improvements=self.high_dose_improvements,
            monotonic_responses=self.monotonic_responses,
            p01_crossings=self.p01_crossings,
            p02_crossings=self.p02_crossings,
            endpoint=self.endpoint,
        )
        expected = (
            self.study_id == STUDY_ID,
            self.run_id == RUN_ID,
            self.seed == 0,
            self.config_hash
            == _canonical_sha256(self.config.model_dump(mode="json")),
            self.steps_completed == PLANNED_CALLS,
            self.solver_calls_completed == PLANNED_CALLS,
            self.solver_mode_counts == {"subprocess": PLANNED_CALLS},
            self.b_replay_calls == PLANNED_B_REPLAYS,
            self.a_solver_calls == PLANNED_A_SOLVES,
            self.openems_calls == 0,
            aggregate.endpoint == self.endpoint,
        )
        if not all(expected):
            raise ValueError("probe run summary differs from frozen completion")
        return self


class ProbeTerminalFailure(BaseModel):
    """Atomic marker that permanently forbids a numerical retry for v1."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    study_id: str = STUDY_ID
    run_id: str = RUN_ID
    status: Literal["terminal_failure"] = "terminal_failure"
    failed_at: datetime
    call_index: int = Field(ge=0, le=PLANNED_CALLS)
    exception_type: str
    exception_message: str
    config_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    log_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    log_lines: int = Field(ge=0)
    solver_calls_recorded: int = Field(ge=0, le=PLANNED_CALLS)
    retry_forbidden: Literal[True] = True


class NEC2Like(Protocol):
    """Narrow adapter protocol used by deterministic tests and real NEC2."""

    async def mesh(self, geometry: Geometry, spec: SimulationSpec) -> Mesh:
        """Create the exact wire mesh."""

    async def solve(self, mesh: Mesh, spec: SimulationSpec) -> SimulationResult:
        """Execute one real numerical solve."""


AdapterFactory = Callable[[], NEC2Like]


def _default_adapter_factory() -> NEC2Like:
    return NEC2Adapter()


def _validate_result_curve(
    result: SimulationResult,
    expected_frequencies: tuple[float, ...],
) -> SearchCurve:
    if result.solver_name.lower() != "nec2":
        raise ASpanProbeExecutionError("diagnostic result is not from NEC2")
    solver_mode = str(result.solver_metadata.get("solver_mode", ""))
    if solver_mode != "subprocess":
        raise ASpanProbeExecutionError(
            f"diagnostic NEC2 requires subprocess mode, got {solver_mode!r}"
        )
    if result.status != "success" or result.s_params is None:
        raise ASpanProbeExecutionError(
            "real diagnostic NEC2 returned no successful S-parameter result"
        )
    actual_frequencies = tuple(float(value) for value in result.s_params.frequency)
    if len(actual_frequencies) != len(expected_frequencies) or any(
        not math.isclose(actual, frozen, rel_tol=0.0, abs_tol=0.5)
        for actual, frozen in zip(
            actual_frequencies,
            expected_frequencies,
            strict=True,
        )
    ):
        raise ASpanProbeExecutionError("diagnostic NEC2 frequency table changed")
    if len(result.s_params.s_matrix) != len(expected_frequencies):
        raise ASpanProbeExecutionError("diagnostic NEC2 S-parameter rows changed")
    s11_db: list[float] = []
    for matrix in result.s_params.s_matrix:
        try:
            magnitude = abs(complex(matrix[0][0]))
        except (IndexError, TypeError, ValueError) as error:
            raise ASpanProbeExecutionError(
                "diagnostic NEC2 returned malformed S11 data"
            ) from error
        if not math.isfinite(magnitude):
            raise ASpanProbeExecutionError("diagnostic NEC2 returned non-finite S11")
        s11_db.append(
            -300.0 if magnitude == 0.0 else 20.0 * math.log10(magnitude)
        )
    return SearchCurve(
        solver_name="nec2",
        solver_mode="subprocess",
        frequency_hz=expected_frequencies,
        s11_db=tuple(s11_db),
        realized_gain_dbi=None,
    )


async def _solve_diagnostic_a(
    adapter: NEC2Like,
    trajectory: DiagnosticTrajectory,
) -> SearchCurve:
    """Bypass StateControl reconstruction only for the >1M diagnostic A span."""

    geometry = trajectory.geometries[0]
    expected_radius = trajectory.proposal.hardware.wire_radius_um * 1e-6
    radius = geometry.metadata.get("wire_radius_m")
    if (
        not isinstance(radius, (int, float))
        or isinstance(radius, bool)
        or float(radius) != expected_radius
    ):
        raise ASpanProbeExecutionError("diagnostic geometry wire radius changed")
    spec = SimulationSpec(
        name="semifinal-a-span-support-causal-probe-a",
        frequency_range=(
            STATE_A_FREQUENCIES_HZ[0],
            STATE_A_FREQUENCIES_HZ[-1],
        ),
        frequency_points=len(STATE_A_FREQUENCIES_HZ),
        solver_settings={
            "nec2_segments_per_wavelength": NEC2_SEGMENTS_PER_WAVELENGTH,
        },
        far_field_request=None,
    )
    mesh = await adapter.mesh(geometry, spec)
    mesh_radius = mesh.metadata.get("wire_radius_m")
    if (
        mesh.geometry_id != geometry.id
        or mesh.solver_name.lower() != "nec2"
        or mesh.nodes != geometry.vertices
        or mesh.elements != geometry.faces
        or not isinstance(mesh_radius, (int, float))
        or isinstance(mesh_radius, bool)
        or float(mesh_radius) != expected_radius
    ):
        raise ASpanProbeExecutionError("diagnostic NEC2 mesh changed geometry identity")
    result = await adapter.solve(mesh, spec)
    return _validate_result_curve(result, STATE_A_FREQUENCIES_HZ)


async def _solve_b_replay(
    adapter: NEC2Like,
    parent_id: ParentId,
) -> SearchCurve:
    parent = get_frozen_parent(parent_id)
    geometry = build_state_geometry(parent.hardware, parent.state_b)
    solver = PairedNEC2Solver(cast(NEC2Adapter, adapter))
    curve = await solver(geometry, "B", STATE_B_FREQUENCIES_HZ)
    if canonical_curve_sha256(curve.model_dump(mode="json")) != (
        EXPECTED_B_CURVE_SHA256[parent_id]
    ):
        raise ASpanProbeExecutionError(f"frozen B replay changed for {parent_id}")
    return curve


def _parse_probe_event(raw_line: bytes, line_number: int) -> ProbeEvent:
    try:
        value = json.loads(raw_line)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ASpanProbeExecutionError(
            f"cannot parse probe log line {line_number}"
        ) from error
    if not isinstance(value, dict):
        raise ASpanProbeExecutionError(
            f"probe log line {line_number} is not an object"
        )
    try:
        if value.get("event_type") == "a_span_probe_b_replay":
            return ProbeBReplayEvent.model_validate(value)
        if value.get("event_type") == "a_span_probe_a_evaluation":
            return ProbeAEvaluationEvent.model_validate(value)
    except ValueError as error:
        raise ASpanProbeExecutionError(
            f"probe log line {line_number} violates its schema"
        ) from error
    raise ASpanProbeExecutionError(
        f"probe log line {line_number} has an unknown event type"
    )


def _same_float(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-13, abs_tol=1e-15)


def _validate_b_event(event: ProbeBReplayEvent, plan: SolverPlanItem) -> None:
    if (
        plan.event_kind != "b_replay"
        or event.call_index != plan.call_index
        or event.parent_id != plan.parent_id
        or event.solver_mode != "subprocess"
        or event.state_b_curve.solver_mode != "subprocess"
        or event.state_b_curve.realized_gain_dbi is not None
    ):
        raise ASpanProbeExecutionError("persisted B replay differs from plan")
    digest = canonical_curve_sha256(event.state_b_curve.model_dump(mode="json"))
    metric = score_state_curve(event.state_b_curve, "B")
    expected_loss = next(
        unit.frozen_b_loss
        for unit in FROZEN_SOURCE_UNITS
        if unit.parent_id == event.parent_id
    )
    if (
        digest != event.canonical_curve_sha256
        or digest != EXPECTED_B_CURVE_SHA256[event.parent_id]
        or not metric.valid_search
        or not _same_float(metric.reflected_power_fraction, expected_loss)
    ):
        raise ASpanProbeExecutionError("persisted B replay does not recompute")


def _validate_a_event(event: ProbeAEvaluationEvent, plan: SolverPlanItem) -> None:
    if plan.event_kind != "a_probe" or plan.unit_index is None or plan.dose_ppm is None:
        raise ASpanProbeExecutionError("persisted A row occupies a B plan position")
    unit = FROZEN_SOURCE_UNITS[plan.unit_index]
    identity = (
        event.call_index,
        event.parent_id,
        event.seed,
        event.source_pair_hash,
        event.source_run_id,
        event.source_step_index,
        event.source_proposal_index,
        event.dose_ppm,
        event.effective_a_span_ratio_ppm,
    )
    expected_identity = (
        plan.call_index,
        unit.parent_id,
        unit.seed,
        unit.source_pair_hash,
        unit.source_run_id,
        unit.source_step_index,
        unit.source_proposal_index,
        plan.dose_ppm,
        unit.state_a_span_ratio_ppm + plan.dose_ppm,
    )
    trajectory = build_diagnostic_trajectory(unit, plan.dose_ppm)
    metric = score_state_curve(event.state_a_curve, "A")
    digest = canonical_curve_sha256(event.state_a_curve.model_dump(mode="json"))
    hybrid = max(metric.reflected_power_fraction, unit.frozen_b_loss)
    valid = trajectory.audit.valid and metric.valid_search
    positive = plan.dose_ppm > 0
    values = (
        identity == expected_identity,
        event.solver_mode == "subprocess",
        event.state_a_curve.solver_mode == "subprocess",
        event.state_a_curve.realized_gain_dbi is None,
        digest == event.canonical_curve_sha256,
        _same_float(event.frozen_b_loss, unit.frozen_b_loss),
        event.trajectory_valid == trajectory.audit.valid,
        _same_float(
            event.actual_full_width_mm,
            trajectory.audit.actual_full_width_m * 1_000.0,
        ),
        _same_float(
            event.minimum_clearance_mm,
            trajectory.audit.minimum_clearance_m * 1_000.0,
        ),
        event.state_a_selected_index == metric.selected_index,
        _same_float(
            event.state_a_selected_frequency_hz,
            metric.selected_frequency_hz,
        ),
        _same_float(event.state_a_selected_s11_db, metric.selected_s11_db),
        _same_float(event.state_a_loss, metric.reflected_power_fraction),
        event.state_a_valid == metric.valid_search,
        _same_float(event.hybrid_loss, hybrid),
        event.diagnostic_pair_valid == valid,
        event.diagnostic_reference_crossing == (valid and hybrid <= T_REF),
        event.source_box_size_um == BOX_SIZE_UM,
        event.counterfactual_only == positive,
        event.outside_original_span_support == positive,
        event.physical_40mm_trajectory_valid == trajectory.audit.valid,
        not event.eligible_for_original_candidate_pool,
        not event.eligible_for_original_h1_h2,
        not event.eligible_for_original_agent_comparison,
    )
    if not all(values):
        raise ASpanProbeExecutionError("persisted A row does not recompute")
    if plan.dose_ppm == 0 and (
        digest != unit.state_a_curve_sha256
        or not _same_float(metric.reflected_power_fraction, unit.state_a_loss)
    ):
        raise ASpanProbeExecutionError("dose-zero persisted control changed")


def validate_probe_prefix(events: Sequence[ProbeEvent]) -> None:
    """Require a strict, recomputable prefix of the frozen 0..31 call plan."""

    if len(events) > PLANNED_CALLS:
        raise ASpanProbeExecutionError("probe log exceeds the 32-call ceiling")
    plan = build_solver_plan()
    for index, event in enumerate(events):
        if event.call_index != index:
            raise ASpanProbeExecutionError("probe log call indices are not contiguous")
        item = plan[index]
        if isinstance(event, ProbeBReplayEvent):
            _validate_b_event(event, item)
        else:
            _validate_a_event(event, item)


def load_probe_events(path: Path) -> tuple[ProbeEvent, ...]:
    """Load an absent log as empty or a strict LF-only validated prefix."""

    if not path.exists():
        return ()
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise ASpanProbeExecutionError(f"cannot read probe log: {error}") from error
    if not payload or not payload.endswith(b"\n") or b"\r" in payload:
        raise ASpanProbeExecutionError(
            "probe log must be non-empty, newline-terminated LF-only JSONL"
        )
    events = tuple(
        _parse_probe_event(raw_line, line_number)
        for line_number, raw_line in enumerate(
            payload.splitlines(keepends=True),
            start=1,
        )
    )
    validate_probe_prefix(events)
    return events


def aggregate_probe_endpoint(
    events: Sequence[ProbeEvent],
) -> ProbeEndpointAggregate:
    """Aggregate only a complete, independently recomputed 32-call log."""

    validate_probe_prefix(events)
    if len(events) != PLANNED_CALLS:
        raise ASpanProbeExecutionError("endpoint requires a complete 32-call log")
    a_events = tuple(
        event for event in events if isinstance(event, ProbeAEvaluationEvent)
    )
    if len(a_events) != PLANNED_A_SOLVES:
        raise ASpanProbeExecutionError("endpoint does not contain thirty A rows")
    high_dose_improvements = 0
    monotonic_responses = 0
    crossings: dict[ParentId, int] = {"p01": 0, "p02": 0}
    for unit_index, unit in enumerate(FROZEN_SOURCE_UNITS):
        rows = tuple(a_events[dose_index * 10 + unit_index] for dose_index in range(3))
        if tuple(row.dose_ppm for row in rows) != DOSES_PPM:
            raise ASpanProbeExecutionError("endpoint block dose order changed")
        low, middle, high = rows
        if high.state_a_loss < low.state_a_loss:
            high_dose_improvements += 1
        if low.state_a_loss >= middle.state_a_loss >= high.state_a_loss:
            monotonic_responses += 1
        if any(row.diagnostic_reference_crossing for row in rows[1:]):
            crossings[unit.parent_id] += 1
    return ProbeEndpointAggregate(
        high_dose_improvements=high_dose_improvements,
        monotonic_responses=monotonic_responses,
        p01_crossings=crossings["p01"],
        p02_crossings=crossings["p02"],
        endpoint=classify_endpoint(
            high_dose_improvements,
            monotonic_responses,
            crossings["p01"],
            crossings["p02"],
        ),
    )


def _build_run_config(gates: SourceGateInputs) -> ProbeRunConfig:
    return ProbeRunConfig(
        source_commit=gates.source_commit,
        preregistration_commit=gates.preregistration_commit,
        implementation_commit=gates.implementation_commit,
        execution_commit=gates.execution_commit,
        implementation_blob=gates.implementation_blob,
        source_manifest_entry_count=gates.source_manifest_entry_count,
        source_manifest_sha256=gates.source_manifest_sha256,
        preregistration_document_sha256=PREREGISTRATION_DOCUMENT_SHA256,
        source_appendix_sha256=SOURCE_APPENDIX_SHA256,
        source_report_sha256=SOURCE_REPORT_SHA256,
        runtime_path_blobs=gates.runtime_path_blobs,
        source_units=gates.source_units,
    )


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _probe_log_fingerprint(path: Path) -> tuple[str | None, int]:
    if not path.exists():
        return None, 0
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise ASpanProbeExecutionError(
            f"cannot fingerprint partial probe log: {error}"
        ) from error
    return _sha256(payload), payload.count(b"\n")


def load_probe_terminal_failure(path: Path) -> ProbeTerminalFailure | None:
    """Load a permanent failure marker, rejecting malformed collision evidence."""

    if not path.exists():
        return None
    try:
        return ProbeTerminalFailure.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as error:
        raise ASpanProbeExecutionError(
            f"cannot validate terminal failure marker: {error}"
        ) from error


def write_probe_terminal_failure(
    run_directory: Path,
    error: Exception,
    call_index: int,
    config_hash: str | None,
) -> ProbeTerminalFailure:
    """Atomically create the no-retry marker without overwriting an old marker."""

    marker_path = run_directory / TERMINAL_FAILURE_FILENAME
    if marker_path.exists():
        raise ASpanProbeExecutionError(
            "terminal failure marker already exists; numerical retry is forbidden"
        )
    log_sha256, log_lines = _probe_log_fingerprint(
        run_directory / LOG_FILENAME
    )
    marker = ProbeTerminalFailure(
        failed_at=datetime.now(UTC),
        call_index=call_index,
        exception_type=type(error).__name__,
        exception_message=str(error),
        config_hash=config_hash,
        log_sha256=log_sha256,
        log_lines=log_lines,
        solver_calls_recorded=log_lines,
    )
    try:
        _write_json(marker_path, marker.model_dump(mode="json"))
    except OSError as write_error:
        raise ASpanProbeExecutionError(
            "terminal numerical failure occurred and its marker could not be written"
        ) from write_error
    return marker


def _b_event(
    call_index: int,
    parent_id: ParentId,
    curve: SearchCurve,
) -> ProbeBReplayEvent:
    event = ProbeBReplayEvent(
        call_index=call_index,
        parent_id=parent_id,
        canonical_curve_sha256=canonical_curve_sha256(
            curve.model_dump(mode="json")
        ),
        state_b_curve=curve,
        timestamp=_timestamp(),
    )
    _validate_b_event(event, build_solver_plan()[call_index])
    return event


def _a_event(
    item: SolverPlanItem,
    trajectory: DiagnosticTrajectory,
    curve: SearchCurve,
) -> ProbeAEvaluationEvent:
    if item.unit_index is None or item.dose_ppm is None:
        raise ASpanProbeExecutionError("A event builder received a B plan item")
    unit = FROZEN_SOURCE_UNITS[item.unit_index]
    metric = score_state_curve(curve, "A")
    digest = canonical_curve_sha256(curve.model_dump(mode="json"))
    if item.dose_ppm == 0 and (
        digest != unit.state_a_curve_sha256
        or not _same_float(metric.reflected_power_fraction, unit.state_a_loss)
    ):
        raise ASpanProbeExecutionError(
            f"dose-zero A replay changed for {unit.parent_id}/s{unit.seed}"
        )
    hybrid = max(metric.reflected_power_fraction, unit.frozen_b_loss)
    valid = trajectory.audit.valid and metric.valid_search
    positive = item.dose_ppm > 0
    event = ProbeAEvaluationEvent(
        call_index=item.call_index,
        parent_id=unit.parent_id,
        seed=unit.seed,
        source_pair_hash=unit.source_pair_hash,
        source_run_id=unit.source_run_id,
        source_step_index=unit.source_step_index,
        source_proposal_index=unit.source_proposal_index,
        dose_ppm=item.dose_ppm,
        effective_a_span_ratio_ppm=(
            unit.state_a_span_ratio_ppm + item.dose_ppm
        ),
        state_a_curve=curve,
        canonical_curve_sha256=digest,
        frozen_b_loss=unit.frozen_b_loss,
        trajectory_valid=trajectory.audit.valid,
        actual_full_width_mm=trajectory.audit.actual_full_width_m * 1_000.0,
        minimum_clearance_mm=trajectory.audit.minimum_clearance_m * 1_000.0,
        state_a_selected_index=metric.selected_index,
        state_a_selected_frequency_hz=metric.selected_frequency_hz,
        state_a_selected_s11_db=metric.selected_s11_db,
        state_a_loss=metric.reflected_power_fraction,
        state_a_valid=metric.valid_search,
        hybrid_loss=hybrid,
        diagnostic_pair_valid=valid,
        diagnostic_reference_crossing=valid and hybrid <= T_REF,
        source_box_size_um=BOX_SIZE_UM,
        counterfactual_only=positive,
        outside_original_span_support=positive,
        physical_40mm_trajectory_valid=trajectory.audit.valid,
        eligible_for_original_candidate_pool=False,
        eligible_for_original_h1_h2=False,
        eligible_for_original_agent_comparison=False,
        timestamp=_timestamp(),
    )
    _validate_a_event(event, item)
    return event


def _validate_completed_summary(
    summary: ProbeRunSummary,
    config: ProbeRunConfig,
    events: Sequence[ProbeEvent],
    log_path: Path,
) -> None:
    aggregate = aggregate_probe_endpoint(events)
    log_sha256, log_lines = _probe_log_fingerprint(log_path)
    if (
        summary.config != config
        or summary.config_hash
        != _canonical_sha256(config.model_dump(mode="json"))
        or log_sha256 is None
        or summary.log_sha256 != log_sha256
        or log_lines != PLANNED_CALLS
        or summary.high_dose_improvements
        != aggregate.high_dose_improvements
        or summary.monotonic_responses != aggregate.monotonic_responses
        or summary.p01_crossings != aggregate.p01_crossings
        or summary.p02_crossings != aggregate.p02_crossings
        or summary.endpoint != aggregate.endpoint
    ):
        raise ASpanProbeExecutionError(
            "persisted completed summary differs from its log or config"
        )


def _load_completed_summary(
    path: Path,
    config: ProbeRunConfig,
    events: Sequence[ProbeEvent],
    log_path: Path,
) -> ProbeRunSummary | None:
    if not path.exists():
        return None
    try:
        summary = ProbeRunSummary.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as error:
        raise ASpanProbeExecutionError(
            f"cannot validate completed probe summary: {error}"
        ) from error
    _validate_completed_summary(summary, config, events, log_path)
    return summary


async def run_a_span_probe(
    repo_root: Path,
    implementation_commit: str,
    execution_commit: str | None = None,
    *,
    adapter_factory: AdapterFactory = _default_adapter_factory,
) -> ProbeRunSummary:
    """Execute or strictly resume the sole preregistered 32-call NEC2 sequence."""

    root = repo_root.resolve()
    run_directory = root / RUN_DIRECTORY
    log_path = run_directory / LOG_FILENAME
    summary_path = run_directory / SUMMARY_FILENAME
    failure_path = run_directory / TERMINAL_FAILURE_FILENAME
    if load_probe_terminal_failure(failure_path) is not None:
        raise ASpanProbeExecutionError(
            "terminal failure marker exists; numerical retry is forbidden"
        )

    config: ProbeRunConfig | None = None
    config_hash: str | None = None
    try:
        gates = validate_source_gates(
            root,
            implementation_commit,
            execution_commit,
        )
        geometry_release = audit_geometry_release()
        if (
            geometry_release.trajectory_count != PLANNED_A_SOLVES
            or geometry_release.geometry_count != PLANNED_GEOMETRIES
        ):
            raise ASpanProbeGeometryError(
                "geometry release does not match the frozen numerical plan"
            )
        config = _build_run_config(gates)
        config_hash = _canonical_sha256(config.model_dump(mode="json"))
        events = list(load_probe_events(log_path))
        completed = _load_completed_summary(
            summary_path,
            config,
            events,
            log_path,
        )
        if completed is not None:
            return completed
    except Exception as error:  # noqa: BLE001 - every preflight mismatch is terminal
        try:
            write_probe_terminal_failure(
                run_directory,
                error,
                0,
                config_hash,
            )
        except ASpanProbeExecutionError as marker_error:
            raise ASpanProbeExecutionError(
                f"probe preflight failed and marker write failed: {error}"
            ) from marker_error
        raise ASpanProbeExecutionError(
            f"probe preflight failed before solver construction: {error}"
        ) from error

    if config is None or config_hash is None:
        raise ASpanProbeExecutionError("probe preflight did not construct a config")
    started_at = datetime.now(UTC)
    plan = build_solver_plan()
    trajectories = {
        (dose, unit_index): geometry_release.trajectories[
            dose_index * len(FROZEN_SOURCE_UNITS) + unit_index
        ]
        for dose_index, dose in enumerate(DOSES_PPM)
        for unit_index in range(len(FROZEN_SOURCE_UNITS))
    }
    previous_no_fallback = os.environ.get("YAF_NO_FALLBACK")
    os.environ["YAF_NO_FALLBACK"] = "1"
    try:
        adapter = adapter_factory()
        for item in plan[len(events) :]:
            if item.event_kind == "b_replay":
                curve = await _solve_b_replay(adapter, item.parent_id)
                event: ProbeEvent = _b_event(
                    item.call_index,
                    item.parent_id,
                    curve,
                )
            else:
                if item.unit_index is None or item.dose_ppm is None:
                    raise ASpanProbeExecutionError(
                        "A plan item lacks source-unit intervention"
                    )
                trajectory = trajectories[(item.dose_ppm, item.unit_index)]
                curve = await _solve_diagnostic_a(adapter, trajectory)
                event = _a_event(item, trajectory, curve)
            _append_jsonl(log_path, event.model_dump(mode="json"))
            events.append(event)

        validate_probe_prefix(events)
        aggregate = aggregate_probe_endpoint(events)
        log_sha256, log_lines = _probe_log_fingerprint(log_path)
        if log_sha256 is None or log_lines != PLANNED_CALLS:
            raise ASpanProbeExecutionError(
                "completed numerical sequence lacks exactly 32 LF log rows"
            )
        summary = ProbeRunSummary(
            started_at=started_at,
            finished_at=datetime.now(UTC),
            config_hash=config_hash,
            config=config,
            solver_mode_counts={"subprocess": PLANNED_CALLS},
            endpoint=aggregate.endpoint,
            high_dose_improvements=aggregate.high_dose_improvements,
            monotonic_responses=aggregate.monotonic_responses,
            p01_crossings=aggregate.p01_crossings,
            p02_crossings=aggregate.p02_crossings,
            log_sha256=log_sha256,
        )
        _write_json(summary_path, summary.model_dump(mode="json"))
        loaded = _load_completed_summary(
            summary_path,
            config,
            events,
            log_path,
        )
        if loaded is None:
            raise ASpanProbeExecutionError(
                "atomic completed summary write produced no evidence"
            )
        return loaded
    except Exception as error:  # noqa: BLE001 - every numerical error forbids retry
        try:
            write_probe_terminal_failure(
                run_directory,
                error,
                len(events),
                config_hash,
            )
        except ASpanProbeExecutionError as marker_error:
            raise ASpanProbeExecutionError(
                f"probe execution failed and marker write failed: {error}"
            ) from marker_error
        raise ASpanProbeExecutionError(
            f"probe execution terminated permanently: {error}"
        ) from error
    finally:
        if previous_no_fallback is None:
            os.environ.pop("YAF_NO_FALLBACK", None)
        else:
            os.environ["YAF_NO_FALLBACK"] = previous_no_fallback


async def execute_probe(
    repo_root: Path,
    implementation_commit: str,
    execution_commit: str | None = None,
    *,
    adapter_factory: AdapterFactory = _default_adapter_factory,
) -> ProbeRunSummary:
    """Compatibility alias for the sole asynchronous probe entry point."""

    return await run_a_span_probe(
        repo_root,
        implementation_commit,
        execution_commit,
        adapter_factory=adapter_factory,
    )


ASpanProbeRunConfig = ProbeRunConfig
ASpanProbeRunSummary = ProbeRunSummary
ASpanProbeBReplayEvent = ProbeBReplayEvent
ASpanProbeAEvaluationEvent = ProbeAEvaluationEvent
