import json

import pytest

from tools.rebuild_measurement_publication import rebuild, STAGE_FILES
from tests.test_stage6_validate_merge import all_stages


def test_rebuild_preserves_sources_and_reports_missing_documents(tmp_path):
    source = tmp_path / "input"
    doc = source / "reference_no_0000002"
    doc.mkdir(parents=True)
    for name, model in zip(STAGE_FILES, all_stages()):
        (doc / name).write_text(json.dumps(model.model_dump(mode="json")), encoding="utf-8")
    (source / "reference_no_missing").mkdir()
    result = rebuild(source, tmp_path / "output")
    assert result["original_inputs_unchanged"]
    assert result["api_requests"] == 0
    assert result["document_status_counts"] == {"published": 1, "missing_input": 1}
    assert (tmp_path / "output" / doc.name / "measurement_publication.json").is_file()
    assert (tmp_path / "output/review_queue.jsonl").is_file()
    with pytest.raises(ValueError, match="exists"):
        rebuild(source, tmp_path / "output")
    with pytest.raises(ValueError, match="separate"):
        rebuild(source, source / "nested")


def test_missing_stages_still_write_available_raw_table_candidates(tmp_path):
    from tests.test_measurement_publication import fixture
    from tests.test_raw_measurement_candidates import shadow
    _, inputs = fixture()
    source = tmp_path / "input"
    doc = source / "reference_no_test"
    doc.mkdir(parents=True)
    for stage, name in (("stage0", STAGE_FILES[0]), ("stage2", STAGE_FILES[2])):
        inputs[stage]["document_id"] = doc.name
        (doc / name).write_text(json.dumps(inputs[stage]), encoding="utf-8")
    raw = shadow()
    raw["document_id"] = doc.name
    (doc / "stage4t_shadow.json").write_text(json.dumps(raw), encoding="utf-8")
    result = rebuild(source, tmp_path / "output")
    assert result["document_status_counts"] == {"missing_input": 1}
    assert result["raw_candidate_counts"]["expression_count"] == 1
    assert result["raw_candidate_review_route_counts"] == {"source_review": 1}
    queue = (tmp_path / "output/raw_candidate_review_queue.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(queue[0])["review_route"] == "source_review"
    assert json.loads(queue[0])["source_context"] is None
    assert (tmp_path / "output" / doc.name / "raw_candidate_ledger.json").is_file()
    assert not (tmp_path / "output" / doc.name / "measurement_publication.json").exists()
    extracted = json.loads((tmp_path / 'output' / doc.name / 'source_extraction.json').read_text(encoding='utf-8'))
    assert extracted['counts']['claim_count'] == 1
    assert extracted['counts']['table_count'] > 0
    assert result['source_status_counts'] == {'source_rechecked': 1}
    assert result['default_view'] == 'source_extraction'


def test_corrupt_raw_input_clears_stale_stage6_publication(tmp_path):
    from stages.stage6_validate_merge import run_stage6
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    paths = [inputs / name for name in STAGE_FILES]
    for path, model in zip(paths, all_stages()):
        path.write_text(json.dumps(model.model_dump(mode="json")), encoding="utf-8")
    (inputs / "stage4t_shadow.json").write_text('{bad json', encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    for name in ("final.json", "measurement_publication.json", "report.html"):
        (output / name).write_text('stale', encoding="utf-8")
    validation, published = run_stage6('reference_no_0000002', *paths, output / "stage6_validation.json", output / "final.json")
    assert not published and validation.status == "failed"
    assert not any((output / name).exists() for name in ("final.json", "measurement_publication.json"))
    assert 'stale' not in (output / 'report.html').read_text(encoding='utf-8')
    source = json.loads((output / 'source_extraction.json').read_text(encoding='utf-8'))
    assert source['document_id'] == 'reference_no_0000002'
