from scripts.semifinal_public_snapshot_verify import verify_snapshot_metadata


def test_public_snapshot_metadata_matches_frozen_terminal_facts() -> None:
    assert verify_snapshot_metadata() == {
        "manifest_count": 255,
        "accepted_count": 6000,
        "h1_count": 702,
        "h2_count": 0,
        "a_span_probe_solver_calls": 32,
        "a_span_probe_monotonic_responses": 10,
        "a_span_probe_endpoint": "span_support_sufficient_in_frozen_counterfactuals",
        "support_certificate_checked_spans": 480002,
    }
