from __future__ import annotations

import json

from tools.audit_preview_binding import audit_batch, render_markdown


def test_audit_batch_reports_status_basis_and_conservation(tmp_path) -> None:
    document = tmp_path / "reference_no_test"
    document.mkdir()
    payload = {
        "summary": {
            "candidate_count": 3,
            "integrated_count": 1,
            "unmatched_sample_count": 1,
            "ambiguous_sample_count": 1,
            "invalid_candidate_count": 0,
            "candidate_conservation": {
                "unaccounted_candidate_count": 0,
            },
        },
        "candidate_outcomes": [
            {
                "candidate_id": "c1",
                "sample_resolution_status": "matched",
                "sample_resolution_basis": "table_sample_series_index",
                "sample_binding_anchors": ["sample_series_context"],
                "sample_matches": ["s001"],
                "sample_binding_context": {"table_id": "T_1"},
            },
            {
                "candidate_id": "c2",
                "sample_resolution_status": "unmatched_sample",
                "sample_matches": [],
            },
            {
                "candidate_id": "c3",
                "sample_resolution_status": "ambiguous_sample",
                "sample_matches": ["s001", "s002"],
            },
        ],
    }
    (document / "stage4r_unified_audit.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    report = audit_batch(tmp_path)

    assert report["document_count"] == 1
    assert report["summary"]["conservation_balanced"] is True
    assert report["summary"]["sample_resolution_status_counts"] == {
        "ambiguous_sample": 1,
        "matched": 1,
        "unmatched_sample": 1,
    }
    assert report["summary"]["sample_resolution_basis_counts"] == {
        "table_sample_series_index": 1,
    }
    markdown = render_markdown(report)
    assert "reference_no_test" in markdown
    assert "table_sample_series_index" in markdown
