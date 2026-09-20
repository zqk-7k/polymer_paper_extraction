import copy
import pytest
from stages.stage4_direct_table_supplement import (
    materialize, unit_in_header, has_display_exponent, inline_heat_capacity_components, table_cell_scalar)
from stages.source_display_scaling import scale_rule, repair_display_scales


def fixture(header, value, name, unit, exponent=2):
    cells = [dict(cell_id='s', row_index=0, column_index=0, text='Material'),
             dict(cell_id='h', row_index=0, column_index=1, text=header),
             dict(cell_id='a', row_index=1, column_index=0, text='blend A'),
             dict(cell_id='v', row_index=1, column_index=1, text=value)]
    table = dict(table_id='T', cells=cells, caption='Properties of blends', page=0)
    response = {'groups': [dict(property_name_raw=header, property_name_normalized=name,
        unit_raw=unit, scale_exponent=exponent, header_cell_ids=['h'],
        points=[dict(cell_id='v', subject_cell_ids=['a'], condition_cell_ids=[])])]}
    return table, response


def test_superscript_units_and_exponents_are_typographic_not_new_evidence():
    header = r'$\Delta C_p$ (cal g $^{-1}$ °C $^{-1}$) ($\times 10^2$)'
    assert unit_in_header('cal g⁻¹ °C⁻¹', header)
    assert not unit_in_header('J g⁻¹ K⁻¹', header)
    assert has_display_exponent(r'Mw [×10$^{3}$ g/mol]', 3)
    assert has_display_exponent('Mw [×10³ g/mol]', 3)
    assert not has_display_exponent('Mw [×103 g/mol]', 3)
    assert not has_display_exponent('Mw [×10³ g/mol]', -3)


def test_bracketed_units_and_response_multipliers_have_opposite_meaning():
    assert scale_rule(r'M_w [×10$^{3}$ g/mol]')[0] == 1000
    assert scale_rule('Mw (×10³)')[0] == 1000
    assert scale_rule('Mw ×10³') is None
    assert scale_rule('Mw of RU [×10³ g/mol]') is None
    assert scale_rule(r'$\Delta C_p$ (cal g $^{-1}$ °C $^{-1}$) ($\times 10^2$)')[0] == .01
    assert scale_rule('Cp ×10²')[0] == .01
    assert scale_rule('composition ×10²') is None


def test_complete_inline_assignments_are_not_arithmetic_or_anonymous_lists():
    text = r'$\Delta C_{p_1}=8.3$ $\Delta C_{p_2}=1.5$ $\Delta C_{p_3}=1.6$'
    got = inline_heat_capacity_components(text, 'Heat capacity increment')
    assert [x['value'] for x in got] == [8.3, 1.5, 1.6]
    assert [x['role'] for x in got] == ['DeltaCp1', 'DeltaCp2', 'DeltaCp3']
    assert not inline_heat_capacity_components(text, 'Molecular weight')
    assert not inline_heat_capacity_components('8.3, 1.5, 1.6', 'Heat capacity')
    assert not inline_heat_capacity_components(text+' + 5', 'Heat capacity')


def test_heat_capacity_materialization_and_repair_are_idempotent(monkeypatch):
    table, response = fixture(r'ΔCp (cal g$^{-1}$ °C$^{-1}$) (×10$^{2}$)',
        r'\Delta C_{p_1}=8.3 \Delta C_{p_2}=1.5 \Delta C_{p_3}=1.6',
        'Heat capacity increment', 'cal g⁻¹ °C⁻¹')
    series, audit = materialize(table, response, 1)
    assert len(series) == 1, audit
    assert [p['value_min'] for p in series[0]['points']] == pytest.approx([.083,.015,.016])
    from stages import source_display_scaling as m
    monkeypatch.setattr(m, 'table_requests', lambda _: [table])
    original = {'property_series': series}
    again, audit = repair_display_scales(original, {})
    assert again == original and not audit['changes']
    wrong = copy.deepcopy(original)
    wrong['property_series'][0]['points'][0]['value_min'] = 830
    wrong['property_series'][0]['points'][0]['value_max'] = 830
    fixed, audit = repair_display_scales(wrong, {})
    assert fixed['property_series'][0]['points'][0]['value_min'] == pytest.approx(.083)
    assert len(audit['changes']) == 1


def test_approximation_is_literal_and_keeps_qualifier():
    assert table_cell_scalar('~138') == 138
    assert table_cell_scalar('~130 to 140') is None
    assert table_cell_scalar('138 + 10') is None
    table, response = fixture(r'M_w [×10$^{3}$ g/mol]', '~138', 'Molecular weight', 'g/mol', 3)
    series, audit = materialize(table, response, 1)
    assert len(series) == 1, audit
    point = series[0]['points'][0]
    assert point['value_min'] == 138000 and point['value_raw'] == '~138'
    assert point['measurement_context']['other_conditions']['reported_approximation']
