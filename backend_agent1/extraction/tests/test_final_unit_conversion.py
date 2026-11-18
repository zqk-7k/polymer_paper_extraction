from copy import deepcopy
import pytest
from stages.final_unit_conversion import attach_table_scale, enrich_observation, match_reference
from tools.production_alignment_audit import value_match


@pytest.mark.parametrize('value,source,target,result', [
    (80, 'MPa', 'GPa', .08), (.08, 'GPa', 'MPa', 80),
    (359.25, 'K', 'c', 86.1), (86.1, '°C', 'K', 359.25),
    (1118.93, 'J/m', 'kJ/m', 1.11893), (41.84, 'J/g', 'kcal/g', .01),
    (4.5e-6, 'S/cm', '1/(ohm*cm)', 4.5e-6),
])
def test_known_conversions(value, source, target, result):
    item = {'value_min': value, 'unit_raw': source}
    snapshot = deepcopy(item)
    converted = enrich_observation(item, target)
    assert item == snapshot
    assert converted['standard_value'] == pytest.approx(result)
    assert enrich_observation(converted, target) == converted
    assert converted['original_value'] == value


@pytest.mark.parametrize('raw,value', [
    (r'$4.5 \times 10^{-6}$', 4.5e-6), ('6.7×10⁻⁶', 6.7e-6),
    ('4.5e-6', 4.5e-6), ('10^{4}', 10000), ('19 800', 19800),
    ('0', 0), ('-42.5', -42.5),
])
def test_full_number_parse(raw, value):
    out = enrich_observation({'value_raw': raw, 'unit_raw': 'S/cm'}, 'S/cm')
    assert out['standard_value'] == pytest.approx(value)


def test_latex_raw_repairs_mantissa_without_mutating_original():
    out = enrich_observation({'value_raw': r'$4.5 \times 10^{-6}$', 'value_min': 4.5, 'unit_raw': 'S/cm'}, 'S/cm')
    assert out['standard_value'] == 4.5e-6
    assert out['value_min'] == 4.5
    assert 'raw_structured_value_conflict' in out['conversion_warnings']


def test_interval_and_uncertainty_offset():
    r = enrich_observation({'value_raw': '-10–20', 'unit_raw': '°C'}, 'K')
    assert r['standard_value'] == [263.15, 293.15]
    r = enrich_observation({'value_raw': '300 ± 2', 'unit_raw': 'K'}, 'c')
    assert r['standard_value'] == 26.85
    assert r['standard_uncertainty'] == 2
    r = enrich_observation({'value_raw': '30,000 ~ 120,000'})
    assert r['standard_value'] == [30000, 120000]


def test_no_empty_header_matches_and_no_small_number_false_positive():
    assert not value_match({'value_min': 16000, 'value_max': 16000}, {'property_name_raw': 'Mn'})
    assert not value_match({'value_min': 1.1e-8}, {'value_raw': '1.1e-6'})
    assert not enrich_observation({'value_raw': 'Table 4'}, 'K')['numeric_present']
    assert not enrich_observation({'value_raw': True}, 'K')['numeric_present']


def test_unknown_and_incompatible_units_preserve_source():
    out = enrich_observation({'value_raw': '12', 'unit_raw': 'unknown'}, 'MPa')
    assert out['standard_value'] is None
    assert out['original_value'] == 12
    assert out['unit_conversion_status'] == 'unit_review_required'
    out = enrich_observation({'value_raw': '12', 'unit_raw': 'J/mol'}, 'J/g')
    assert out['unit_conversion_status'] == 'unit_conflict'
    assert out['standard_unit'] is None
    first = enrich_observation({'value_raw': '80', 'unit_raw': 'MPa'}, 'GPa')
    second = enrich_observation(first, 'J/g')
    assert second['standard_value'] is None
    assert 'standard_numeric_values' not in second
    assert second['source_numeric_values'] == [80]


def test_missing_target_keeps_source_without_inventing_unit():
    out = enrich_observation({'value_min': 19800})
    assert out['standard_value'] == 19800
    assert out['standard_unit'] is None
    assert out['unit_conversion_status'] == 'unit_source_only'


def test_header_multiplier_is_idempotent_and_ambiguous_multiplier_is_reviewed():
    r = enrich_observation({'value_raw': '1.6', 'scale_factor_exponent': 4})
    assert r['standard_value'] == 16000
    assert enrich_observation(r) == r
    r = enrich_observation({'value_raw': '1.6×10^4', 'scale_factor_exponent': 4})
    assert r['standard_value'] is None
    assert r['unit_conversion_status'] == 'unit_review_required'


def test_matching_uses_converted_source_and_reference_rounding():
    out = enrich_observation({'value_min': 38.8, 'unit_raw': 'J/g'}, 'kcal/g')
    assert match_reference({'value_min': '.00927'}, out) == 'converted_matches_reference_rounding'
    assert match_reference({'value_min': '.0927'}, out) is None
    assert value_match({'value_min': .08, 'reviewed_unit': 'GPa'}, {'value_raw': '80', 'unit_raw': 'MPa'})


def test_source_rounding_is_accounted_for_but_not_arbitrary_rescaling():
    for raw, unit, target, gt in [('344.2', 'K', 'c', 71), ('42.9', 'J/g', 'kcal/g', .0102), ('35.8', 'J/g', 'kcal/g', .00855)]:
        out = enrich_observation({'value_raw': raw, 'unit_raw': unit}, target)
        assert match_reference({'value_min': gt}, out) == 'converted_matches_reference_rounding'
    out = enrich_observation({'value_raw': '6.7e-6', 'unit_raw': 'S/cm'}, 'S/cm')
    assert match_reference({'value_min': '6.7e-5'}, out) is None


def test_table_scale_has_source_locator_and_header_itself_is_not_a_value():
    tables = {'T1': {'table_cells': [{'cell_id': 'T1:r1:c1', 'row_index': 1, 'column_index': 1, 'text': '$10^{4}$'}]}}
    item = {'source_stage': 'stage4t', 'semantic_label': 'molecular_weight', 'table_id': 'T1',
            'row_index': 2, 'column_index': 1, 'value_raw': '1.6'}
    enriched = attach_table_scale(item, tables)
    assert enriched['scale_factor_evidence']['cell_id'] == 'T1:r1:c1'
    assert enrich_observation(enriched)['standard_value'] == 16000
    header = {**item, 'row_index': 1, 'value_raw': '$10^{4}$'}
    assert enrich_observation(attach_table_scale(header, tables))['numeric_present'] is False
    assert 'scale_factor_exponent' not in item


def test_standalone_cli_writes_enriched_jsonl_without_overwriting_source(tmp_path, monkeypatch):
    import json
    import sys
    from stages.final_unit_conversion import main
    source, target = tmp_path / 'input.jsonl', tmp_path / 'output.jsonl'
    original = json.dumps({'value_raw': '80', 'unit_raw': 'MPa'})+'\n'
    source.write_text(original, encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['converter', '--input', str(source), '--output', str(target), '--target-unit', 'GPa'])
    main()
    assert json.loads(target.read_text(encoding='utf-8'))['standard_value'] == .08
    assert source.read_text(encoding='utf-8') == original
