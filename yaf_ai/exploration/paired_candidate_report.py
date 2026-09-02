"""Human-readable report for the committed NEC2 candidate freeze."""

from __future__ import annotations

from pathlib import Path

from yaf_ai.exploration.paired_candidates import (
    FROZEN_REPORT_PATH,
    CandidateFreezeDocument,
    CandidateFreezeError,
    FrozenCategoryCandidate,
    write_once_or_match,
)


def _required_metric(value: float | None, label: str) -> float:
    if value is None:
        raise CandidateFreezeError(f"selected candidate lacks {label}")
    return value


def _candidate_rows(
    candidates: tuple[FrozenCategoryCandidate, ...],
) -> list[str]:
    rows: list[str] = []
    for candidate in candidates:
        status = "eligible" if candidate.positive_eligible else "diagnostic only"
        rows.append(
            f"| {candidate.category} | `{candidate.source_run_id}` step "
            f"{candidate.source_step_index} | {candidate.valid_record_count}/"
            f"{candidate.source_record_count} | {candidate.base_score:.6f} | "
            f"{candidate.metrics.worst_reflected_power_fraction:.6f} | "
            f"{status} |"
        )
    return rows


def _state_rows(
    candidates: tuple[FrozenCategoryCandidate, ...],
) -> list[str]:
    rows: list[str] = []
    for candidate in candidates:
        for state in (candidate.metrics.state_a, candidate.metrics.state_b):
            rows.append(
                f"| {candidate.category} | {state.state} | "
                f"{state.selected_frequency_hz / 1e9:.4f} GHz | "
                f"{state.selected_s11_db:.3f} dB | {state.selected_index} | "
                f"{str(state.valid_search).lower()} |"
            )
    return rows


def render_candidate_report(document: CandidateFreezeDocument) -> bytes:
    """Render an answer-first technical report from the frozen document."""

    top_es, top_random, manual = document.candidates
    effect = document.effect_assessment
    diagnostic = document.validity_gate_diagnostic
    statistics = document.agent_run_statistics
    top_statistic = next(
        statistic for statistic in statistics if statistic.run_id == top_es.source_run_id
    )
    state_a = top_es.metrics.state_a
    state_b = top_es.metrics.state_b
    valid_statistics = tuple(
        statistic for statistic in statistics if statistic.valid_pair_count > 0
    )
    valid_cells = len(valid_statistics)
    other_cells = len(statistics) - valid_cells
    es_statistics = tuple(
        statistic for statistic in statistics if statistic.agent in ("es-cold", "es-warm")
    )
    es_valid_pairs = sum(statistic.valid_pair_count for statistic in es_statistics)
    es_accepted_pairs = sum(statistic.accepted_pair_count for statistic in es_statistics)
    valid_source_summary = ", ".join(
        f"{statistic.agent} seed {statistic.seed} ({statistic.valid_pair_count})"
        for statistic in valid_statistics
    )
    if valid_statistics:
        valid_matrix_summary = (
            f"{valid_source_summary} supplied "
            f"{sum(item.valid_pair_count for item in valid_statistics)} "
            f"NEC2-valid paired proposals; the remaining {other_cells} cells "
            "produced none."
        )
    else:
        valid_matrix_summary = (
            f"No matrix cell supplied a NEC2-valid paired proposal; all "
            f"{len(statistics)} cells are diagnostic only."
        )
    warm_statistics = tuple(statistic for statistic in statistics if statistic.agent == "es-warm")
    warm_valid_cells = sum(statistic.valid_pair_count > 0 for statistic in warm_statistics)
    total_pairs = sum(statistic.accepted_pair_count for statistic in statistics)
    total_curves = sum(statistic.subprocess_curve_count for statistic in statistics)
    total_rejections = sum(statistic.rejected_proposals for statistic in statistics)
    clearance = _required_metric(
        top_es.trajectory.minimum_clearance_m,
        "trajectory clearance",
    )
    pitch = _required_metric(
        top_es.trajectory.minimum_pitch_m,
        "trajectory pitch",
    )
    height = _required_metric(
        top_es.trajectory.minimum_height_m,
        "trajectory height",
    )
    effect_outcome = "passed" if effect.passed else "failed"
    if top_es.positive_eligible:
        hypothesis_heading = (
            "## A NEC2-valid two-state computational hypothesis emerged, "
            "but it is not a confirmed discovery"
        )
        hypothesis_description = (
            "The preregistered eligibility-first rule froze one auditable "
            "NEC2-only hypothesis. The same ideal telescopic meander model "
            f"predicts state A at {state_a.selected_frequency_hz / 1e9:.4f} GHz "
            f"with S11={state_a.selected_s11_db:.3f} dB and state B at "
            f"{state_b.selected_frequency_hz / 1e9:.4f} GHz with "
            f"S11={state_b.selected_s11_db:.3f} dB; its "
            f"{top_es.trajectory.point_count}-point discrete trajectory passes "
            "the geometry audit."
        )
        candidate_status = f"NEC2-only / {document.verdict_ceiling}"
    else:
        hypothesis_heading = (
            "## No NEC2-valid two-state computational hypothesis survived the frozen rule"
        )
        hypothesis_description = (
            "The preregistered eligibility-first rule found no eligible ES pair. "
            "The retained top-ES row is a diagnostic object only; its predicted "
            "frequencies and scores do not constitute a candidate discovery."
        )
        candidate_status = f"diagnostic-only / {document.verdict_ceiling}"
    if effect.passed:
        effect_followup = (
            "Passing this NEC2 search-reference gate would still not establish "
            "a confirmed improvement without the remaining frozen gates."
        )
    else:
        effect_followup = (
            "Because this frozen gate failed, even future cross-solver agreement "
            "cannot turn this candidate into `confirmed_improvement` without a "
            "new, prospectively registered study."
        )
    if diagnostic.valid_pair_search:
        selection_explanation = (
            "Each pool is first restricted to valid pairs when any exist, then "
            "sorted by base score. The highest raw ES score was already valid, "
            "so no score-only exclusion changed the ES selection."
        )
        diagnostic_heading = "## The raw-score leader also passed the validity gate"
        diagnostic_text = (
            f"The highest raw ES score came from "
            f"`{diagnostic.source_run_id}` step "
            f"{diagnostic.source_step_index}: base score "
            f"{diagnostic.base_score:.6f} and an apparent "
            f"{100.0 * diagnostic.apparent_reduction_fraction:.3f}% reduction "
            "in L. Its selected minima passed the preregistered validity gate, "
            "so no score-only exclusion was needed."
        )
    else:
        selection_explanation = (
            "Each pool is first restricted to valid pairs when any exist, then "
            "sorted by base score. The ES candidate is therefore not replaced by "
            "a higher raw score whose minima sit at sweep boundaries."
        )
        diagnostic_heading = "## The validity gate rejected the invalid raw-score leader"
        diagnostic_text = (
            f"The highest raw ES score came from "
            f"`{diagnostic.source_run_id}` step "
            f"{diagnostic.source_step_index}: base score "
            f"{diagnostic.base_score:.6f} and an apparent "
            f"{100.0 * diagnostic.apparent_reduction_fraction:.3f}% reduction "
            "in L. Its minima were at state-A index "
            f"{diagnostic.state_a_selected_index} and state-B index "
            f"{diagnostic.state_b_selected_index}. The preregistered internal-"
            "minimum condition excluded it from the eligible pool."
        )
    lines = [
        "# Semifinal paired-state NEC2 candidate freeze",
        "",
        hypothesis_heading,
        "",
        (
            f"The frozen nine-cell matrix completed {total_pairs:,} paired "
            f"evaluations ({total_curves:,} real NEC2 subprocess curves) and "
            f"recorded {total_rejections:,} geometry rejections without spending "
            f"evaluation budget. {valid_matrix_summary}"
        ),
        "",
        hypothesis_description,
        "",
        (
            f"The preregistered NEC2 effect comparison {effect_outcome}: "
            f"worst-state reflected power changed by "
            f"{100.0 * effect.relative_reduction_fraction:.3f}% versus the "
            f"frozen manual template against a "
            f"{100.0 * effect.threshold_fraction:.1f}% reduction threshold. "
            "Cross-seed stability, lambda/40 direction, gain guardrails, and "
            "openEMS confirmation are not established. The verdict ceiling is "
            f"`{document.verdict_ceiling}`."
        ),
        "",
        f"## Candidate card: paired-state hypothesis {top_es.pair_hash[:12]}...",
        "",
        f"**Status:** `{candidate_status}`",
        (
            "**Claim boundary:** this catalog label is not `YAF-M1`, a confirmed "
            "improvement, a new invention, or a manufacturable antenna."
        ),
        "",
        "| Frozen field | Value |",
        "| --- | --- |",
        (f"| Source | `{top_es.source_run_id}`, step {top_es.source_step_index} |"),
        f"| Pair SHA-256 | `{top_es.pair_hash}` |",
        f"| Hardware SHA-256 | `{top_es.hardware_hash}` |",
        f"| Turn count | {top_es.proposal.hardware.turn_count} |",
        (f"| Feed-gap ratio | {top_es.proposal.hardware.feed_gap_ratio_ppm} ppm |"),
        (f"| Terminal ratio | {top_es.proposal.hardware.terminal_ratio_ppm} ppm |"),
        (
            f"| State A wire length / span | "
            f"{top_es.proposal.state_a.total_wire_length_um / 1000.0:.3f} mm / "
            f"{top_es.proposal.state_a.span_ratio_ppm / 1_000_000:.6f} |"
        ),
        (
            f"| State B wire length / span | "
            f"{top_es.proposal.state_b.total_wire_length_um / 1000.0:.3f} mm / "
            f"{top_es.proposal.state_b.span_ratio_ppm / 1_000_000:.6f} |"
        ),
        (
            f"| Discrete trajectory | {top_es.trajectory.point_count} points; "
            f"valid={str(top_es.trajectory.valid).lower()} |"
        ),
        f"| Minimum clearance | {1000.0 * clearance:.6f} mm |",
        f"| Minimum pitch | {1000.0 * pitch:.6f} mm |",
        f"| Minimum height | {1000.0 * height:.6f} mm |",
        "",
        (
            "The endpoint states share one quantized hardware identity. The ideal "
            "model changes total wire length from "
            f"{top_es.proposal.state_a.total_wire_length_um / 1000.0:.3f} mm to "
            f"{top_es.proposal.state_b.total_wire_length_um / 1000.0:.3f} mm and "
            "span ratio from "
            f"{top_es.proposal.state_a.span_ratio_ppm / 1_000_000:.6f} to "
            f"{top_es.proposal.state_b.span_ratio_ppm / 1_000_000:.6f}. It does "
            "not model sleeve overlap, contact resistance, actuator volume, stress, "
            "conductor loss, or a continuous-motion proof."
        ),
        "",
        "## Eligibility, not raw score, determined the frozen objects",
        "",
        selection_explanation,
        "",
        ("| Category | Source | Valid pool | Base score | Worst reflected power | Status |"),
        "| --- | --- | ---: | ---: | ---: | --- |",
        *_candidate_rows((top_es, top_random, manual)),
        "",
        ("| Category | State | Selected frequency | S11 | Index | Valid internal minimum |"),
        "| --- | --- | ---: | ---: | ---: | --- |",
        *_state_rows((top_es, top_random, manual)),
        "",
        f"## The preregistered effect gate {effect_outcome}",
        "",
        (
            "The comparison is `L_candidate <= "
            f"{effect.maximum_candidate_to_reference_ratio:.2f} * L_manual`, "
            "where `L` is the worse state's reflected-power fraction in the "
            "NEC2 lambda/20 search reference."
        ),
        "",
        "| Quantity | Value |",
        "| --- | ---: |",
        f"| Top-ES L | {effect.candidate_value:.12f} |",
        f"| Manual L | {effect.reference_value:.12f} |",
        (
            f"| Required maximum L | "
            f"{effect.maximum_candidate_to_reference_ratio * effect.reference_value:.12f} |"
        ),
        (f"| Observed reduction | {100.0 * effect.relative_reduction_fraction:.6f}% |"),
        f"| Required reduction | {100.0 * effect.threshold_fraction:.1f}% |",
        f"| Gate | {'PASS' if effect.passed else 'FAIL'} |",
        "",
        effect_followup,
        "",
        diagnostic_heading,
        "",
        diagnostic_text,
        "",
        (f"## NEC2-valid paired proposals appeared in {valid_cells} of {len(statistics)} cells"),
        "",
        ("| Agent | Seed | Accepted | Valid | Valid rate | Best raw | Best valid | Rejections |"),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for statistic in statistics:
        valid_score = (
            "-"
            if statistic.best_valid_base_score is None
            else f"{statistic.best_valid_base_score:.6f}"
        )
        lines.append(
            f"| {statistic.agent} | {statistic.seed} | "
            f"{statistic.accepted_pair_count} | {statistic.valid_pair_count} | "
            f"{100.0 * statistic.valid_pair_fraction:.2f}% | "
            f"{statistic.best_raw_base_score:.6f} | {valid_score} | "
            f"{statistic.rejected_proposals} |"
        )
    lines.extend(
        [
            "",
            (
                f"{valid_cells} of {len(statistics)} cells contained at least one "
                f"NEC2-valid pair. The combined ES pool had {es_valid_pairs} valid "
                f"records out of {es_accepted_pairs:,} accepted pairs. The frozen "
                f"top-ES source cell ({top_statistic.agent} seed "
                f"{top_statistic.seed}) contributed "
                f"{top_statistic.valid_pair_count}. Raw-score differences in cells "
                "with zero valid pairs are descriptive only."
            ),
            "",
            "## Every number is bound to committed evidence",
            "",
            (
                f"The freeze reads {total_pairs:,} accepted records directly from "
                f"Git commit `{document.source_evidence_commit}`. It binds each "
                "source log and summary to manifest SHA-256 "
                f"`{document.source_manifest_sha256}`, recomputes metrics from "
                "archived curves, reconstructs selected geometry hashes and the "
                f"{top_es.trajectory.point_count}-point trajectory, and binds the "
                "manual row to its committed "
                "warm-parent document. Draft `runs/` files are not inputs."
            ),
            "",
            (
                "The G5 supersession prospectively authorized NEC2 hypothesis "
                "generation while keeping openEMS locked. The three objects were "
                "frozen before any later cross-check output. Exact tables are used "
                "instead of a chart because this artifact is a categorical freeze; "
                "the full 101-point curves remain in the cited source logs."
            ),
            "",
            "## Remaining gates and next action",
            "",
            "- `lambda/40` effect direction: not evaluated.",
            ("- Realized-gain guardrails: not evaluated; search curves contain no gain."),
            "- Independent openEMS cross-check: not authorized or evaluated.",
            (
                f"- Cross-seed stability: limited to {warm_valid_cells} of "
                f"{len(warm_statistics)} warm seeds and {valid_cells} of "
                f"{len(es_statistics)} ES runs."
            ),
            "- Continuous mechanics and manufacturing: outside the ideal-PEC model.",
            "",
            (
                "No new solver run is authorized by this freeze. A later study "
                "must first preregister and release both 5.8 GHz and 2.45 GHz rod-"
                "renderer anchors, then separately authorize exactly the frozen "
                f"{len(document.candidates)} objects times two states. Because the "
                f"{100.0 * effect.threshold_fraction:.1f}% effect gate has "
                "already failed, cross-checking could establish solver consistency "
                "but cannot retroactively produce the frozen positive verdict."
            ),
            "",
            "## Further research question",
            "",
            (
                "Can a new, prospectively registered search target this apparently "
                "seed-local valid region while exceeding the unchanged "
                f"{100.0 * effect.threshold_fraction:.1f}% reflected-power "
                "gate across multiple seeds? That must be a separate study; it "
                "cannot add or swap candidates in this frozen batch."
            ),
            "",
        ]
    )
    return "\n".join(lines).encode("utf-8")


def write_or_verify_candidate_report(
    repo_root: Path,
    document: CandidateFreezeDocument,
    *,
    verify: bool,
    report_path: Path | None = None,
) -> None:
    """Write once or verify the report byte-for-byte."""

    relative = FROZEN_REPORT_PATH if report_path is None else report_path
    destination = relative if relative.is_absolute() else repo_root.resolve() / relative
    expected = render_candidate_report(document)
    if verify:
        if not destination.exists():
            raise CandidateFreezeError("frozen-candidate report is missing")
        try:
            actual = destination.read_bytes()
        except OSError as error:
            raise CandidateFreezeError(f"cannot read frozen-candidate report: {error}") from error
        if actual != expected:
            raise CandidateFreezeError("refusing to verify changed candidate report")
        return
    write_once_or_match(destination, expected)
