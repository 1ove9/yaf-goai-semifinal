from __future__ import annotations

import inspect
from typing import cast

import pytest
from pydantic import ValidationError

from yaf_ai.exploration.paired_b_completion_coordinates import (
    CERTIFICATE_EXPECTED_SPANS,
    CERTIFICATE_EXPECTED_SPANS_PER_PARENT,
    MAPPING_VERSION,
    P01,
    P02,
    BCompletionCoordinateInvariantError,
    CertificateFailureWitness,
    CertificateSpanResult,
    FrozenBParent,
    ParentCertificateStatistics,
    ParentID,
    canonical_inverse,
    combine_certificate_statistics,
    decode_a_only_coordinates,
    encode_a_only_coordinates,
    evaluate_certificate_span,
    get_frozen_parent,
    half_up_map,
    interpolate_integer,
    minimum_legal_a_length,
    suffix_preconditions_hold,
    summarize_parent_certificate,
)
from yaf_ai.exploration.paired_feasible_coordinates import (
    SPAN_BOUNDS,
    STATE_A_LENGTH_BOUNDS,
)
from yaf_ai.exploration.paired_meander import (
    TRAJECTORY_POINT_COUNT,
    audit_trajectory,
    build_state_geometry,
    hardware_hash,
    state_geometry_hash,
)


def test_parent_constants_reconstruct_frozen_hardware_and_b_hashes() -> None:
    assert (P01.parent_id, P01.parent_code) == ("p01", 1)
    assert (P02.parent_id, P02.parent_code) == ("p02", 2)
    assert P01.hardware.model_dump(mode="json") == {
        "schema_version": 1,
        "mechanism_version": "ideal-symmetric-telescopic-PEC-meander-v1",
        "quantization_version": "integer-um-ppm-v1",
        "turn_count": 3,
        "feed_gap_ratio_ppm": 49_001,
        "terminal_ratio_ppm": 0,
        "max_total_wire_length_um": 100_000,
        "box_size_um": 40_000,
        "wire_radius_um": 50,
    }
    assert P02.hardware.feed_gap_ratio_ppm == 48_021
    assert P01.state_b.model_dump(mode="json") == {
        "state": "B",
        "total_wire_length_um": 26_090,
        "span_ratio_ppm": 785_552,
    }
    assert P02.state_b.total_wire_length_um == 26_646
    assert P02.state_b.span_ratio_ppm == 770_570
    for parent in (P01, P02):
        geometry = build_state_geometry(parent.hardware, parent.state_b)
        assert hardware_hash(parent.hardware) == parent.expected_hardware_hash
        assert (
            state_geometry_hash(parent.hardware, parent.state_b, geometry)
            == parent.expected_state_b_geometry_hash
        )


def test_parent_model_rejects_changed_frozen_identity() -> None:
    payload = P01.model_dump(mode="json")
    payload["expected_hardware_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="hardware hash does not reconstruct"):
        FrozenBParent.model_validate(payload)


@pytest.mark.parametrize("integer", range(10, 21))
def test_half_up_and_canonical_inverse_round_trip_every_integer(integer: int) -> None:
    raw = canonical_inverse(integer, (10, 20))
    assert half_up_map(raw, (10, 20)) == integer


def test_half_up_boundaries_ties_and_singleton_are_frozen() -> None:
    assert half_up_map(0.0, (10, 20)) == 10
    assert half_up_map(1.0, (10, 20)) == 20
    assert half_up_map(0.049999999999, (10, 20)) == 10
    assert half_up_map(0.05, (10, 20)) == 11
    assert half_up_map(0.0, (7, 7)) == 7
    assert half_up_map(1.0, (7, 7)) == 7
    assert canonical_inverse(7, (7, 7)) == 0.5


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_half_up_rejects_non_normalized_values(value: float) -> None:
    with pytest.raises(BCompletionCoordinateInvariantError, match="finite in"):
        half_up_map(value, (0, 1))


def test_bounds_and_inverse_fail_closed() -> None:
    with pytest.raises(BCompletionCoordinateInvariantError, match="reversed"):
        half_up_map(0.5, (2, 1))
    with pytest.raises(BCompletionCoordinateInvariantError, match="outside"):
        canonical_inverse(9, (10, 20))


def test_integer_interpolation_matches_the_frozen_formula() -> None:
    assert interpolate_integer(100, 0, 0) == 100
    assert interpolate_integer(100, 0, 10) == 50
    assert interpolate_integer(100, 0, 20) == 0
    assert interpolate_integer(101, 0, 10) == 51
    with pytest.raises(BCompletionCoordinateInvariantError, match=r"\[0,20\]"):
        interpolate_integer(1, 2, TRAJECTORY_POINT_COUNT)


@pytest.mark.parametrize("span", [760_000, 770_570, 785_552, 880_000, 1_000_000])
@pytest.mark.parametrize("parent", [P01, P02], ids=("p01", "p02"))
def test_known_parent_spans_have_the_frozen_lower_bound(
    parent: FrozenBParent,
    span: int,
) -> None:
    assert suffix_preconditions_hold(parent, span)
    assert minimum_legal_a_length(parent, span) == STATE_A_LENGTH_BOUNDS[0]


@pytest.mark.parametrize("parent", [P01, P02], ids=("p01", "p02"))
@pytest.mark.parametrize(
    ("raw", "expected_span", "expected_length"),
    [
        ((0.0, 0.0), 760_000, 50_000),
        ((1.0, 1.0), 1_000_000, 100_000),
        ((0.5, 0.5), 880_000, 75_000),
    ],
)
def test_decoder_changes_only_a_and_always_passes_both_audits(
    parent: FrozenBParent,
    raw: tuple[float, float],
    expected_span: int,
    expected_length: int,
) -> None:
    proposal = decode_a_only_coordinates(parent, raw, "test-a-only")
    assert proposal.hardware == parent.hardware
    assert proposal.state_b == parent.state_b
    assert proposal.state_a.span_ratio_ppm == expected_span
    assert proposal.state_a.total_wire_length_um == expected_length
    assert audit_trajectory(proposal).valid
    geometry_b = build_state_geometry(proposal.hardware, proposal.state_b)
    assert (
        state_geometry_hash(proposal.hardware, proposal.state_b, geometry_b)
        == parent.expected_state_b_geometry_hash
    )


@pytest.mark.parametrize("parent", [P01, P02], ids=("p01", "p02"))
def test_canonical_a_only_round_trip_is_byte_exact(parent: FrozenBParent) -> None:
    proposal = decode_a_only_coordinates(parent, (0.314159, 0.271828), "round-trip")
    encoded = encode_a_only_coordinates(parent, proposal)
    assert decode_a_only_coordinates(parent, encoded, proposal.proposer) == proposal


def test_encoder_rejects_a_proposal_bound_to_the_other_parent() -> None:
    p01_proposal = decode_a_only_coordinates(P01, (0.5, 0.5), "wrong-parent")
    with pytest.raises(BCompletionCoordinateInvariantError, match="frozen B parent"):
        encode_a_only_coordinates(P02, p01_proposal)


@pytest.mark.parametrize(
    "raw",
    [(), (0.1,), (0.1, 0.2, 0.3), (-0.1, 0.2), (0.1, float("nan"))],
)
def test_decoder_rejects_malformed_raw_vectors(raw: tuple[float, ...]) -> None:
    with pytest.raises(BCompletionCoordinateInvariantError):
        decode_a_only_coordinates(P01, raw, "invalid")


@pytest.mark.parametrize("parent", [P01, P02], ids=("p01", "p02"))
@pytest.mark.parametrize("span", [SPAN_BOUNDS[0], 880_000, SPAN_BOUNDS[1]])
def test_certificate_span_checks_both_boundaries_without_solver(
    parent: FrozenBParent,
    span: int,
) -> None:
    result = evaluate_certificate_span(parent, span)
    assert result.parent_id == parent.parent_id
    assert result.span_ratio_ppm == span
    assert result.lower_legal_length_um == 50_000
    assert result.upper_legal_length_um == 100_000
    assert result.passed


def test_certificate_statistics_preserve_first_witness_and_frozen_order() -> None:
    witness = CertificateFailureWitness(
        failure_class="lower_round_trip_failed",
        span_ratio_ppm=SPAN_BOUNDS[0],
        length_um=50_000,
        detail="synthetic known-answer failure",
    )
    failed = CertificateSpanResult(
        parent_id="p01",
        span_ratio_ppm=SPAN_BOUNDS[0],
        lower_legal_length_um=50_000,
        failures=(witness,),
    )
    passed = CertificateSpanResult(
        parent_id="p01",
        span_ratio_ppm=SPAN_BOUNDS[0] + 1,
        lower_legal_length_um=50_000,
    )
    statistics = summarize_parent_certificate(P01, (failed, passed))
    assert statistics.checked_span_count == 2
    assert statistics.failed_span_count == 1
    assert statistics.status == "incomplete"
    assert len(statistics.failure_tallies) == 1
    assert statistics.failure_tallies[0].first_witness == witness


def test_certificate_statistics_reject_non_contiguous_or_wrong_parent_rows() -> None:
    skipped = CertificateSpanResult(
        parent_id="p01",
        span_ratio_ppm=SPAN_BOUNDS[0] + 1,
        lower_legal_length_um=50_000,
    )
    with pytest.raises(BCompletionCoordinateInvariantError, match="contiguous"):
        summarize_parent_certificate(P01, (skipped,))
    wrong_parent = skipped.model_copy(
        update={"parent_id": "p02", "span_ratio_ppm": SPAN_BOUNDS[0]}
    )
    with pytest.raises(BCompletionCoordinateInvariantError, match="contiguous"):
        summarize_parent_certificate(P01, (wrong_parent,))


def test_top_level_statistics_require_p01_then_p02_and_reconstruct_counts() -> None:
    p01 = ParentCertificateStatistics(
        parent_id="p01",
        checked_span_count=0,
        failed_span_count=0,
        failure_tallies=(),
        status="incomplete",
    )
    p02 = ParentCertificateStatistics(
        parent_id="p02",
        checked_span_count=0,
        failed_span_count=0,
        failure_tallies=(),
        status="incomplete",
    )
    aggregate = combine_certificate_statistics(p01, p02)
    assert aggregate.mapping_version == MAPPING_VERSION
    assert aggregate.expected_span_count == CERTIFICATE_EXPECTED_SPANS
    assert aggregate.checked_span_count == 0
    assert aggregate.status == "incomplete"
    with pytest.raises(ValidationError, match="parent order"):
        combine_certificate_statistics(p02, p01)


def test_statistics_constants_cover_exactly_two_full_span_ranges() -> None:
    assert CERTIFICATE_EXPECTED_SPANS_PER_PARENT == 240_001
    assert CERTIFICATE_EXPECTED_SPANS == 480_002


def test_decoder_source_has_no_solver_or_result_dependency() -> None:
    source = inspect.getsource(decode_a_only_coordinates).lower()
    for forbidden in ("solver", "s11", "score", "frequency", "source_a"):
        assert forbidden not in source


def test_parent_lookup_fails_closed_for_an_unknown_runtime_value() -> None:
    invalid: object = "p03"
    with pytest.raises(BCompletionCoordinateInvariantError, match="unknown"):
        get_frozen_parent(cast(ParentID, invalid))
