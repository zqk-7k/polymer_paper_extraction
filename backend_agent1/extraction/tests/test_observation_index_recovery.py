from copy import deepcopy
import json
from pathlib import Path
import pytest

from stages.observation_index_recovery import (
    recover_observation, source_context, property_compatible,
    recover_missing_peak_cells, recover_equation_observations,
)
from stages.final_unit_conversion import enrich_observation, match_reference, parse_numeric
from tools.production_alignment_audit import (
    build_audit, candidate_code, load_registry, DEFAULT_STANDARD, DEFAULT_REGISTRY, DEFAULT_SCHEMA,
)
from tools.production_export import build_export
from tools.source_index_diagnostics import build_diagnostics, read_rows


def context(label='', caption='', definition='', value='7', extra=()):
    cells = [dict(cell_id='T:r1:c0', row_index=1, column_index=0, text=label),
             dict(cell_id='T:r1:c1', row_index=1, column_index=1, text=value), *extra]
    return source_context([{'type': 'table', 'block_id': 'T', 'caption': caption, 'table_cells': cells},
                           {'type': 'text', 'block_id': 'P', 'text': definition}])


@pytest.mark.parametrize('raw,caption,definition,code,qualifier', [
    ('$P_{n}^{a}$', 'Common properties of polyamidines', '', 'degree_of_polymerization', {}),
    ('$X^{a,e}$', 'Physical properties', 'degrees of polymerization (x)', 'degree_of_polymerization', {}),
    ('Initial Modulus (GPa)', 'Thin Film Tensile Properties', '', 'tensile_modulus', {}),
    ('$T_s$ (°C)', '', 'softening temperatures (T_s)', 'softening_temperature', {}),
    ('$T_r$(°C)', '', 'recrystallization temperature (T_r)', 'crystallization_temperature', {'event_raw': 'recrystallization'}),
    ('$T_2^{c}$, °C', 'Thermal properties', 'two decomposition peaks', 'thermal_decomposition_temperature', {'decomposition_peak_index': 2}),
    ('Wt. loss (%)', 'Thermal properties', '', 'thermal_decomposition_weight_loss', {}),
])
def test_source_confirmed_semantics_keep_value_and_evidence(raw, caption, definition, code, qualifier):
    item = {'property_name_raw': raw, 'value_raw': '7', 'table_id': 'T', 'row_index': 1, 'column_index': 1}
    before = deepcopy(item)
    out = recover_observation(item, context(caption=caption, definition=definition))
    assert item == before
    assert out['value_raw'] == '7'
    assert out['recovered_property_code'] == f'STD:{code}'
    assert out['index_qualifiers'] == qualifier
    assert out['source_cell_locator']['cell_id'] == 'T:r1:c1'
    assert 'T' in out['index_semantic_evidence']


@pytest.mark.parametrize('raw,caption,definition', [
    ('$X$', '', 'Crystallinity (X)'),
    ('$T_s$', '', 'softening temperature (T_soft); tensile strength (T_s)'),
    ('$T_r$', '', 'recrystallization temperature (T_c)'),
    ('Initial modulus', 'Compression properties', ''),
    ('$T_2$', 'Thermal properties', 'second melting peak'),
])
def test_ambiguous_symbols_do_not_gain_a_property(raw, caption, definition):
    out = recover_observation({'property_name_raw': raw, 'value_raw': '7'}, context(caption=caption, definition=definition))
    assert 'recovered_property_code' not in out


def test_transposed_table_uses_property_row_not_sample_header():
    item = {'property_name_raw': 'sample_1', 'value_raw': '7', 'table_id': 'T', 'row_index': 1, 'column_index': 1}
    out = recover_observation(item, context(label='$P_{n}^{a}$', caption='Polymer properties'))
    assert out['recovered_property_code'] == 'STD:degree_of_polymerization'
    assert out['property_name_raw'] == 'sample_1'
    assert out['index_property_label'] == '$P_{n}^{a}$'


def test_transposed_row_unit_is_inherited_only_from_explicit_source_header():
    item = {'property_name_raw': 'sample_1', 'value_raw': '0.12', 'table_id': 'T', 'row_index': 1, 'column_index': 1}
    ctx = context(label=r'$\mu_{\text{inh}}$ (dl g $^{-1}$ )', value='0.12')
    out = recover_observation(item, ctx)
    assert out['index_unit_evidence']['cell_id'] == 'T:r1:c0'
    assert enrich_observation(out, 'dl/g')['standard_value'] == .12
    assert 'unit_raw' not in item
    no_unit = recover_observation(item, context(label=r'$\mu_{\text{inh}}$', value='0.12'))
    assert not no_unit.get('unit_raw')


def test_frequency_is_attached_to_its_column_and_dc_stays_distinct():
    ctx = context(extra=[dict(cell_id='T:r0:c1', row_index=0, column_index=1, text='10 kHz', column_span=1),
                         dict(cell_id='T:r0:c2', row_index=0, column_index=2, text='40 MHz', column_span=1)])
    for col, freq in [(1, '10 kHz'), (2, '40 MHz')]:
        item = {'table_id': 'T', 'row_index': 1, 'column_index': col, 'property_name_raw': 'Dielectric constant'}
        out = recover_observation(item, ctx)
        assert out['recovered_property_code'] == 'STD:dielectric_constant_ac'
        assert out['index_qualifiers']['frequency_raw'] == freq
    assert 'recovered_property_code' not in recover_observation({'property_name_raw': 'Dielectric constant DC'}, context())
    assert not property_compatible('STD:dielectric_constant_ac', {'candidate_code': 'STD:dielectric_constant_dc'})


def test_generalization_is_one_way_and_surface_components_stay_separate():
    assert property_compatible('STD:impact_strength_unspecified', {'candidate_code': 'STD:izod_impact'})
    assert not property_compatible('STD:izod_impact', {'candidate_code': 'STD:impact_strength_unspecified'})
    assert property_compatible('STD:d_spacing', {'candidate_code': 'STD:lattice_spacing', 'semantic_label': 'd_spacing'})
    assert not property_compatible('STD:d_spacing', {'candidate_code': 'STD:lattice_spacing', 'property_name_raw': 'lattice parameter a'})
    assert not property_compatible('STD:surface_tension_polar', {'candidate_code': 'STD:surface_tension_dispersive'})


def test_ranges_and_spaced_decimals_parse_without_relaxing_scalar_matches():
    for raw, values in [(r'$1 \sim 3^{\circ}$', [1, 3]), ('227–393 (peaks)', [227, 393]), ('1. 3 2', [1.32])]:
        assert [float(x) for x in parse_numeric(raw)['values']] == values
    for raw in ['Table 1. 3 2', '<5', '1 2 3', '2 (samples)', 'MW/Mn=1.32']:
        assert parse_numeric(raw) is None
    out = enrich_observation({'value_raw': r'$1 \sim 3^{\circ}$', 'value_min': 1, 'value_max': 1, 'unit_raw': '°'}, 'degree', 'STD:contact_angle')
    assert out['standard_value'] == [1, 3]
    assert match_reference({'value_min': 1, 'value_max': 3}, out)
    assert not match_reference({'value_min': 1}, out)
    assert not match_reference({'value_min': 7}, enrich_observation({'value_raw': '7.5', 'unit_raw': 'degree'}, 'degree'))
    assert not match_reference({'value_min': 295, 'value_max': 300}, enrich_observation({'value_raw': '295', 'unit_raw': 'C'}, 'C'))


def test_peak_cells_recover_only_missing_numeric_td_cells():
    ctx = context(value='227–393 (peaks)')
    shadow = {'tables': [{'table_id': 'T', 'direction': 'row_samples', 'header_rows': [0],
                          'property_candidates': [{'column_index': 1, 'property_name_raw': 'Td',
                              'property_name_normalized': 'thermal_decomposition_temperature', 'unit_raw': '°C'}]}]}
    out = list(recover_missing_peak_cells(shadow, ctx))
    assert len(out) == 1 and out[0]['value_raw'] == '227–393 (peaks)'
    assert out[0]['routing_source_file'] == 'stage4t_shadow.json'
    shadow['tables'][0]['shadow_observations'] = [{'cell_id': 'T:r1:c1'}]
    assert not list(recover_missing_peak_cells(shadow, ctx))


def test_equation_assignment_uses_source_not_reference_or_ratio_arithmetic():
    raw = r'$$ \overline {{{M}}}_{\mathrm{w}} / \overline {{{M}}}_{\mathrm{n}} = 1. 3 2. $$'
    ctx = source_context([{'type': 'equation', 'block_id': 'E1', 'text': raw}])
    out = list(recover_equation_observations(ctx))
    assert len(out) == 1 and out[0]['value_raw'] == '1. 3 2'
    assert out[0]['evidence'][0]['source_sentence'] == raw
    _, aliases = load_registry()
    assert candidate_code(out[0], aliases) == 'STD:molecular_weight_dispersity'
    for raw in ['Mw/Mn < 1.32', 'Mw = 62, Mn = 47', 'Mw/Mn = 1.32 ± 0.1']:
        assert not list(recover_equation_observations(source_context([{'type': 'equation', 'block_id': 'E1', 'text': raw}])))


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / 'reports/production_alignment_20260914_split'
BATCH = ROOT / 'batch_results/preview_batch_31_0913_stage4r_fix'


@pytest.mark.skipif(not BASELINE.exists(), reason='Local frozen cohort not installed')
def test_111_cohort_end_to_end_without_llm_and_without_reference_backfill(tmp_path):
    standard_before = DEFAULT_STANDARD.read_bytes()
    audit_dir, diag_dir, export_dir = (tmp_path / name for name in ('audit', 'diagnostics', 'export'))
    build_audit(DEFAULT_STANDARD, BATCH, DEFAULT_REGISTRY, DEFAULT_SCHEMA, audit_dir)
    summary = build_diagnostics(BASELINE, audit_dir, diag_dir, ROOT / 'docs/source_index_review_notes_20260914.jsonl', 111)
    assert summary['cohort_recovered'] == 99
    assert summary['before_captured'] == 1271
    assert summary['after_captured'] == 1370
    assert not summary['regressions']
    assert not summary['gains_outside_cohort']
    assert not summary['recovered_without_source_evidence']
    manifest = build_export(audit_dir, export_dir, diag_dir / 'diagnostics_111.jsonl')
    assert manifest['counts']['candidate_value_only'] == manifest['counts']['final_value_only'] == 1370
    assert manifest['counts']['not_captured'] == 172
    assert manifest['counts']['unit_conversion_review'] == 59
    final = {r['standard_record_id']: r for r in read_rows(export_dir / 'final_value_only.jsonl')}
    for r in read_rows(diag_dir / 'diagnostics_111.jsonl'):
        if r['current_value_captured']:
            published = final[r['standard_record_id']]
            assert published['sample_binding_ignored']
            assert all(o['source_file'] and o['numeric_present'] for o in published['observations'])
    failed = {r['standard_record_id']: r for r in read_rows(export_dir / 'not_captured.jsonl')}
    assert failed['GT:reference_no_0043955:321']['failure_reason'] == 'source_reference_value_conflict'
    assert DEFAULT_STANDARD.read_bytes() == standard_before
