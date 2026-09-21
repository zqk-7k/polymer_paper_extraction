import copy
from stages.source_subject_labels import preserve_prose_subject_labels, temperature_attributed_to_label


def fixture():
    quote = 'Q had 4% loss at 430°C, while R had 4% loss at 450°C.'
    ev = {'block_id': 'b', 'page': 0, 'source_type': 'text', 'source_sentence': quote}
    points = [{'point_id': f'pt{i:03d}', 'sample_resolution_status': 'unresolved',
               'coordinates': [{'name_raw': 'source sample label', 'value_raw': label, 'evidence': ev},
                               {'name_raw': 'associated decomposition temperature', 'value_raw': str(temp), 'unit_raw': '°C', 'evidence': ev}],
               'value_raw': '4', 'value_min': 4., 'value_max': 4., 'unit_raw': '%',
               'measurement_context': {'condition_status': 'reported', 'other_conditions': {
                   'fact_role': 'measurement_criterion', 'source_loss_relation_id': f'fake{i}'}},
               'coverage_status': 'covered', 'evidence': [ev], 'confidence': {'score': 0.0}}
              for i, (label, temp) in enumerate([('Q', 430), ('R', 450)], 1)]
    return {'property_series': [{'series_id': 'series001', 'property_name_raw': 'weight loss', 'points': points}]}, {'elements': [{'block_id': 'b', 'type': 'text', 'text': quote}]}


def test_explicit_attribution_accepts_correct_and_rejects_swapped():
    q = 'Q had 4% loss at 430°C, while R had 4% loss at 450°C.'
    assert temperature_attributed_to_label(q, 'Q', 430)
    assert temperature_attributed_to_label(q, 'R', 450)
    assert not temperature_attributed_to_label(q, 'Q', 450)
    assert not temperature_attributed_to_label(q, 'R', 430)
    q = 'In air, Td40 occurred at 480°C for Q, 460°C for R.'
    assert temperature_attributed_to_label(q, 'Q', 480)
    assert not temperature_attributed_to_label(q, 'Q', 460)
    assert not temperature_attributed_to_label('Td40 did not occur at 480°C for Q.', 'Q', 480)


def test_shared_single_subject_predicate_and_boundaries():
    q = 'The Q-1 polyimide exhibited 4% weight loss at 430°C in nitrogen (Fig. 2) and at 405°C in flowing air.'
    assert temperature_attributed_to_label(q, 'Q-1', 430)
    assert temperature_attributed_to_label(q, 'Q-1', 405)
    assert not temperature_attributed_to_label(q, 'Q', 430)
    assert not temperature_attributed_to_label(q, 'q-1', 430)
    assert not temperature_attributed_to_label('Q and R had losses at 430°C and 450°C, respectively.', 'R', 430)


def test_contiguous_source_and_complete_idempotence():
    data, source = fixture()
    out, audit = preserve_prose_subject_labels(data, source)
    assert audit['labels_preserved'] == 2
    assert all(not x['sample_id_inferred'] for x in audit['decisions'])
    out2, second = preserve_prose_subject_labels(out, source)
    assert out2 == out and second['labels_preserved'] == 0
    x = copy.deepcopy(source)
    x['elements'][0]['text'] = 'Q had 4% loss at 430°C, with intervening actual source text, while R had 4% loss at 450°C.'
    assert preserve_prose_subject_labels(data, x)[1]['labels_preserved'] == 0


def test_swapped_upstream_coordinates_and_noncriterion_abstain():
    data, source = fixture()
    data['property_series'][0]['points'][0]['coordinates'][1]['value_raw'] = '450'
    data['property_series'][0]['points'][1]['coordinates'][1]['value_raw'] = '430'
    assert preserve_prose_subject_labels(data, source)[1]['labels_preserved'] == 0


def test_ambiguous_coordinates_existing_labels_and_multi_evidence():
    for kind in ('source sample label', 'associated decomposition temperature'):
        data, source = fixture()
        p = data['property_series'][0]['points'][0]
        p['coordinates'].append({'name_raw': kind, 'value_raw': 'other' if kind == 'source sample label' else '420', 'unit_raw': '°C'})
        assert preserve_prose_subject_labels(data, source)[1]['labels_preserved'] == 1
    data, source = fixture()
    p = data['property_series'][0]['points'][0]
    p['sample_label_raw'] = 'existing'
    assert preserve_prose_subject_labels(data, source)[0]['property_series'][0]['points'][0]['sample_label_raw'] == 'existing'
    data, source = fixture()
    p = data['property_series'][0]['points'][0]
    p['evidence'].insert(0, {'block_id': 'missing', 'source_sentence': 'not the source'})
    assert preserve_prose_subject_labels(data, source)[1]['labels_preserved'] == 2


def test_fractional_temperature_joint_subject_and_long_negation():
    assert temperature_attributed_to_label('Q had 4% loss at 430.5°C.', 'Q', 430.5)
    assert not temperature_attributed_to_label('Q and R both had 4% loss at 430°C.', 'Q', 430)
    assert not temperature_attributed_to_label('Q and R both had 4% loss at 430°C.', 'R', 430)
    assert not temperature_attributed_to_label('It was not found even after multiple independent thermal measurements at 430°C for Q.', 'Q', 430)


def test_label_survives_stage4_final_schema_and_numeric_view():
    from schema.polymer_schema import PropertySeriesPoint, FinalPropertySeriesPoint
    from evaluation.property_views import property_series_numeric_records
    data, source = fixture()
    out, audit = preserve_prose_subject_labels(data, source)
    assert audit['new_numeric_observations'] == 0
    for point in out['property_series'][0]['points']:
        assert PropertySeriesPoint.model_validate(point).sample_label_raw == point['sample_label_raw']
        payload = {k: v for k, v in point.items() if k not in {'evidence', 'coordinates'}}
        payload.update(evidence_ids=['ev001'], coordinates=[])
        assert FinalPropertySeriesPoint.model_validate(payload).sample_label_raw == point['sample_label_raw']
        assert not point.get('sample_id') and point['sample_resolution_status'] == 'unresolved'
    assert [r['sample_label_raw'] for r in property_series_numeric_records(out)] == ['Q', 'R']
    data, source = fixture()
    for p in data['property_series'][0]['points']:
        p['measurement_context']['other_conditions']['fact_role'] = 'material_property'
    assert preserve_prose_subject_labels(data, source)[1]['labels_preserved'] == 0
