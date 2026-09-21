from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from stages.stage4_schema_isolation import isolate_invalid_scalar_records, is_degraded_empty_shell
from stages.stage4_property import _preview_publication_status
from schema.polymer_schema import PropertyStageResponse
from tests.test_stage4_property import FakeClient


def payload():
    return FakeClient().call_json('', '').data


def test_invalid_aggregate_is_quarantined_not_relabelled():
    data = payload()
    bad = deepcopy(data['properties'][0])
    bad.update(property_id='prop011', observation_role='aggregate')
    data['properties'].append(bad)
    original = deepcopy(data)
    fixed, report = isolate_invalid_scalar_records(data)
    assert data == original
    assert fixed['properties'] == data['properties'][:1]
    assert report[0]['record'] == bad
    assert report[0]['original_index'] == 1
    PropertyStageResponse.model_validate(fixed)
    with pytest.raises(ValidationError):
        PropertyStageResponse.model_validate(data)  # Strict is unchanged.


def test_root_unknown_condition_is_not_hidden():
    data = payload()
    data['properties'][0]['measurement_condition_id'] = 'mc999'
    with pytest.raises(ValidationError):
        isolate_invalid_scalar_records(data)


def test_series_and_unknown_root_fields_are_not_dropped():
    for invalid in ({'unexpected': 1}, {'property_series': [{'series_id': 'bad'}]}):
        with pytest.raises(ValidationError):
            isolate_invalid_scalar_records({**payload(), **invalid})


def test_valid_payload_is_unchanged_and_quarantine_is_partial():
    data = payload()
    fixed, report = isolate_invalid_scalar_records(data)
    assert fixed is data and report == []
    status, _ = _preview_publication_status(preview_degraded_reason=None,
        incomplete_response_reason=None, preview_semantic_bypass_reason=None,
        property_series=[], schema_quarantined=True)
    assert status == 'candidate_partial'


def test_only_known_empty_shell_warning_prevents_cache_reuse():
    assert is_degraded_empty_shell(SimpleNamespace(warnings=[{'code': 'preview_degraded_empty_shell'}]))
    assert not is_degraded_empty_shell(SimpleNamespace(warnings=[{'code': 'series_subject_unresolved'}]))
