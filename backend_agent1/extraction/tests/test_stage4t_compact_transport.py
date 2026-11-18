import json
from copy import deepcopy

import pytest

from stages.stage4t_compact_transport import compact_input, restore_input, restore_response
from stages.stage4t_table_interpretation import validate_interpretation


def payload():
    evidence = {'block_id': 'P1', 'source_sentence': 'An explicitly stated preparation and measurement description. ' * 4}
    process = {'step_id': 'p1', 'output_sample_ids': ['s1', 's2'], 'parameters': {'temperature': '100 C'}, 'evidence': evidence}
    return {'table_id': 'T1', 'cells': [
        {'cell_id': 'T1:r0000:c0000', 'text': 'Mw', 'row_index': 0, 'column_index': 0},
        {'cell_id': 'T1:r0001:c0000', 'text': '3.95', 'row_index': 1, 'column_index': 0},
        {'cell_id': 'T1:r0002:c0000', 'text': '4.64*', 'row_index': 2, 'column_index': 0}],
        'sources': [{'source_id': 'note1', 'kind': 'footnote', 'text': '* measured at 25 C'}],
        'subject_catalog': {'entities': [], 'samples': [
            {'sample_id': 's1', 'state_description': 'film', 'evidence': evidence, 'processes': [process]},
            {'sample_id': 's2', 'state_description': 'solution', 'evidence': evidence, 'processes': [process]}]}}


def response():
    return {'table_id': 'T1', 'direction': 'row_samples', 'axis_role': 'named_sample',
            'sample_binding_strategy': 'direct_row', 'requires_human_review': False,
            'header_assignments': [{'source_cell_ids': ['c0'], 'target_cell_ids': ['c1', 'c2'],
                'role': 'material_characteristic', 'semantic_label': 'molecular_weight', 'confidence': .9, 'reason': 'Mw'}],
            'scoped_relations': [{'kind': 'condition', 'name': 'temperature_condition',
                'source_refs': ['note1'], 'source_quote': '* measured at 25 C', 'target_cell_ids': ['c2'], 'reason': 'Local note'}]}


def test_lossless_input_round_trip_preserves_every_sample_cell_and_evidence():
    original = payload()
    frozen = deepcopy(original)
    wire, mapping = compact_input(original)
    assert restore_input(wire, mapping) == frozen
    assert original == frozen
    assert [s['state_description'] for s in wire['subject_catalog']['samples']] == ['film', 'solution']
    assert wire['transport']['definitions']
    assert len(wire['cells']) == len(original['cells'])
    assert [c['text'] for c in wire['cells']] == ['Mw', '3.95', '4.64*']


def test_independent_targets_and_local_exception_survive_response_restore():
    original = payload()
    _, mapping = compact_input(original)
    raw = response()
    restored = restore_response(raw, mapping)
    validated = validate_interpretation(restored, original, partial=True)
    assert validated.header_assignments[0].target_cell_ids == ['T1:r0001:c0000', 'T1:r0002:c0000']
    assert validated.scoped_relations[0].target_cell_ids == ['T1:r0002:c0000']
    assert raw == response()


def test_unknown_alias_quarantines_only_affected_relation():
    original = payload()
    _, mapping = compact_input(original)
    raw = response()
    raw['scoped_relations'][0]['target_cell_ids'] = ['c999']
    validated = validate_interpretation(restore_response(raw, mapping), original, partial=True)
    assert len(validated.header_assignments) == 1
    assert not validated.scoped_relations
    assert len(validated.rejected_items) == 1
    assert len(original['cells']) == 3


def test_quotes_names_and_sample_ids_are_never_rewritten():
    _, mapping = compact_input(payload())
    raw = {'source_quote': 'c1', 'reason': 'c2', 'candidate_sample_ids': ['c1'],
           'target_cell_ids': ['c1'], 'source_refs': ['c0', 'note1']}
    restored = restore_response(raw, mapping)
    assert restored['source_quote'] == 'c1'
    assert restored['reason'] == 'c2'
    assert restored['candidate_sample_ids'] == ['c1']
    assert restored['target_cell_ids'] == ['T1:r0001:c0000']
    assert restored['source_refs'] == ['T1:r0000:c0000', 'note1']


def test_duplicate_or_colliding_input_ids_are_rejected():
    data = payload()
    data['cells'].append(deepcopy(data['cells'][0]))
    with pytest.raises(ValueError, match='duplicate'):
        compact_input(data)
    with pytest.raises(ValueError, match='collides'):
        compact_input({'cells': [{'cell_id': 'c0', 'text': 'x'}]})
    with pytest.raises(ValueError, match='collides'):
        compact_input({'cells': [{'cell_id': 'T1:r0:c0', 'text': 'x'}],
                       'sources': [{'source_id': 'c0', 'text': 'a note'}]})


def test_aliases_reduce_repeated_reference_output_without_changing_targets():
    _, mapping = compact_input(payload())
    short = response()
    restored = restore_response(short, mapping)
    assert len(json.dumps(short)) < len(json.dumps(restored))


def test_interpreter_restores_before_validation_and_keeps_raw_response():
    from tests.test_stage4t_llm_interpreter import FakeClient, _response, _run, _data
    raw = _data()
    raw['header_assignments'][0]['source_cell_ids'] = ['c1']
    raw['header_assignments'][1]['source_cell_ids'] = ['c2']
    result = _run(FakeClient(response=_response(data=raw)))
    assert result['status'] == 'succeeded'
    assert result['interpretation']['header_assignments'][0]['source_cell_ids'] == ['T_1:r0000:c0001']
    assert result['raw_model_interpretation']['header_assignments'][0]['source_cell_ids'] == ['c1']
    assert result['transport_audit']['cell_id_map']['c1'] == 'T_1:r0000:c0001'


def test_failed_interpreter_keeps_transport_map():
    from llm_client import LLMRequestError
    from tests.test_stage4t_llm_interpreter import FakeClient, _run
    result = _run(FakeClient(error=LLMRequestError('offline fixture timeout')))
    assert result['status'] == 'fallback_candidate_only'
    assert result['transport_audit']['cell_id_map']['c1'] == 'T_1:r0000:c0001'


def test_each_sample_and_overlapping_condition_remain_separate():
    original = payload()
    _, mapping = compact_input(original)
    raw = response()
    raw['scoped_relations'] += [
        {'kind': 'subject', 'source_refs': ['c1'], 'source_quote': '3.95',
         'target_cell_ids': ['c1'], 'candidate_sample_ids': ['s1'], 'reason': 'Test fixture row one'},
        {'kind': 'subject', 'source_refs': ['c2'], 'source_quote': '4.64*',
         'target_cell_ids': ['c2'], 'candidate_sample_ids': ['s2'], 'reason': 'Test fixture row two'},
        {'kind': 'condition', 'name': 'temperature_condition', 'source_refs': ['note1'],
         'source_quote': '25 C', 'target_cell_ids': ['c1', 'c2'], 'reason': 'Overlapping relation retained'},
    ]
    validated = validate_interpretation(restore_response(raw, mapping), original, partial=True)
    assert not validated.rejected_items
    assert len(validated.scoped_relations) == 4
    assert validated.scoped_relations[1].candidate_sample_ids == ['s1']
    assert validated.scoped_relations[2].candidate_sample_ids == ['s2']
    assert validated.scoped_relations[1].target_cell_ids != validated.scoped_relations[2].target_cell_ids
