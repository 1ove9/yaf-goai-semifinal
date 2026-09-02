"""Version-controlled addendum for the Day 5-2 patch mesh audit."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from yaf_ai.exploration.cross_check import CrossCheckError
from yaf_ai.exploration.patch_final_convergence import _read_model
from yaf_ai.exploration.patch_mesh_audit import (
    MESH_AUDIT_RUN_ID,
    PatchMeshAuditSummary,
    PatchMeshStatistics,
)
from yaf_ai.exploration.patch_mesh_recheck import (
    MESH_RECHECK_RUN_ID,
    PatchMeshRecheckSummary,
)

ANALYSIS_DIRECTORY = "day5-patch-final"


class PatchMeshAddendum(BaseModel):
    """Machine-readable correction and restored claim from immutable evidence."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = 1
    analysis_id: Literal["day5-patch-final-mesh-addendum"] = (
        "day5-patch-final-mesh-addendum"
    )
    pre_fix_audit: PatchMeshAuditSummary
    repaired_recheck: PatchMeshRecheckSummary
    root_cause: str
    final_self_convergence_claim: Literal[
        "established_after_refinement_repair",
        "self_convergence_not_established",
    ]
    final_cross_solver_verdict: Literal["DIVERGENT"] = "DIVERGENT"
    historical_artifacts_modified: Literal[False] = False


def build_patch_mesh_addendum(repo_root: Path) -> PatchMeshAddendum:
    """Load only archived audit/recheck evidence and state the final scoped result."""

    runs = repo_root / "artifacts" / "runs"
    audit = _read_model(
        runs / MESH_AUDIT_RUN_ID / "summary.json", PatchMeshAuditSummary
    )
    recheck = _read_model(
        runs / MESH_RECHECK_RUN_ID / "summary.json", PatchMeshRecheckSummary
    )
    if not recheck.refinement_1x_xml_unchanged:
        raise CrossCheckError("mesh addendum cannot prove unchanged 1x XML")
    if recheck.pre_fix_audit_run_id != audit.run_id:
        raise CrossCheckError("mesh addendum evidence chain is disconnected")
    return PatchMeshAddendum(
        pre_fix_audit=audit,
        repaired_recheck=recheck,
        root_cause=(
            "The parametric patch XML builder did not read "
            "openems_mesh_refinement; both archived diagnostic settings therefore "
            "produced the same XML. The repair scales only the non-default patch bulk "
            "and metal-edge resolution by the requested refinement."
        ),
        final_self_convergence_claim=recheck.claim_status,
    )


def _millimetres(values: tuple[float, float, float]) -> str:
    return " / ".join(f"{value * 1e3:.6f}" for value in values)


def _row(stage: str, mesh: PatchMeshStatistics) -> str:
    line_counts = f"{mesh.x.line_count}/{mesh.y.line_count}/{mesh.z.line_count}"
    cell_counts = f"{mesh.x.cell_count}/{mesh.y.cell_count}/{mesh.z.cell_count}"
    minima = _millimetres(
        (
            mesh.x.minimum_cell_size_m,
            mesh.y.minimum_cell_size_m,
            mesh.z.minimum_cell_size_m,
        )
    )
    maxima = _millimetres(
        (
            mesh.x.maximum_cell_size_m,
            mesh.y.maximum_cell_size_m,
            mesh.z.maximum_cell_size_m,
        )
    )
    return (
        f"| {stage} | {mesh.refinement:g}x | {line_counts} | {cell_counts} | "
        f"{mesh.total_cells} | {minima} | {maxima} | `{mesh.xml_sha256}` |"
    )


def _report(addendum: PatchMeshAddendum) -> str:
    audit = addendum.pre_fix_audit
    recheck = addendum.repaired_recheck
    uncertainty = (
        "The repaired movement exceeds 3%, so all historical NEC2-to-openEMS gaps "
        "retain an openEMS-discretization uncertainty footnote."
        if recheck.resonance_shift > recheck.self_convergence_threshold
        else (
            "The repaired movement is within 3%; no additional uncertainty footnote "
            "is required for the historical resonance-gap ladder."
        )
    )
    return "\n".join(
        [
            "# Mesh-count addendum for the Day 5-2 openEMS self-check",
            "",
            "## Audit conclusion",
            "",
            f"The pre-fix 2x/1x cell ratio was "
            f"{audit.decision.total_cell_ratio:.9f}, classified "
            f"`{audit.decision.interpretation}` by the preregistered rule. The archived "
            "2x XML was byte-identical to 1x, so the original self-convergence claim is "
            "retracted as `self_convergence_not_established` for that run.",
            "",
            f"Root cause: {addendum.root_cause}",
            "",
            "## Mesh evidence",
            "",
            "Line and cell-count triples are x/y/z. Cell-size triples are x/y/z in mm.",
            "",
            "| stage | refinement | grid lines | axis cells | total cells | min cell mm | max cell mm | XML SHA-256 |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
            _row("pre-fix audit", audit.mesh_1x),
            _row("pre-fix audit", audit.mesh_2x),
            _row("post-fix verification", recheck.mesh_1x_after_fix),
            _row("post-fix verification", recheck.mesh_2x_after_fix),
            "",
            f"The repaired 2x/1x ratio is "
            f"{recheck.repaired_mesh_decision.total_cell_ratio:.9f}, which is "
            f"`{recheck.repaired_mesh_decision.interpretation}` (effective threshold "
            ">=3). The post-fix 1x SHA-256 exactly matches the immutable pre-fix 1x "
            "evidence, proving the repair did not change refinement=1.0 output.",
            "",
            "## One-shot real 2x recheck",
            "",
            "| predicted wall s | actual wall s | f_res GHz | S11 dB | movement | threshold | final claim | source |",
            "|---:|---:|---:|---:|---:|---:|---|---|",
            f"| {recheck.predicted_seconds:.3f} | "
            f"{recheck.actual_wall_seconds:.3f} | "
            f"{recheck.curve.resonance_frequency_hz / 1e9:.9f} | "
            f"{recheck.curve.resonance_s11_db:.6f} | "
            f"{recheck.resonance_shift:.9%} | <=3% | "
            f"`{recheck.claim_status}` | `{recheck.run_id}` |",
            "",
            uncertainty,
            "",
            "## Scope",
            "",
            "The restored claim applies to the repaired openEMS patch mesh path. It does "
            "not reopen or alter the final cross-solver verdict: `DIVERGENT` remains "
            "unchanged because the archived grid-44 comparison missed the 5% resonance "
            "and 0.8 Pearson gates. No historical run or Day 5-2 analysis file is edited; "
            "this addendum and its two source runs are new evidence only.",
        ]
    )


def write_patch_mesh_addendum(repo_root: Path) -> PatchMeshAddendum:
    """Write LF-only JSON and Markdown beside, not over, prior analysis files."""

    addendum = build_patch_mesh_addendum(repo_root)
    output = repo_root / "artifacts" / "analysis" / ANALYSIS_DIRECTORY
    output.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            addendum.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    json_temporary = output / "mesh-addendum.json.tmp"
    json_temporary.write_bytes(payload)
    os.replace(json_temporary, output / "mesh-addendum.json")
    markdown = (_report(addendum) + "\n").encode("utf-8")
    markdown_temporary = output / "mesh-addendum.md.tmp"
    markdown_temporary.write_bytes(markdown)
    os.replace(markdown_temporary, output / "mesh-addendum.md")
    return addendum
