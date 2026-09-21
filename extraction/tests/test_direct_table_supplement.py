from stages.stage4_direct_table_supplement import scalar, materialize, canonical_unit, unit_in_header, header_applies, footnoted_scalar


def test_declared_footnote_number_keeps_marker():
    assert footnoted_scalar('285c', r'$^{c}$ Determination from cited method.') == (285., 'c')
    assert footnoted_scalar('1.5a', '') == (None, None)
    assert footnoted_scalar('highd', r'$^{d}$ Method.') == (None, None)


def test_conductivity_uses_existing_inverse_display_contract():
    table={'table_id':'T1','page':0,'caption':'DC conductivity','cells':[
        {'cell_id':'a','row_index':1,'column_index':0,'text':'A'},
        {'cell_id':'h','row_index':0,'column_index':1,'text':r'$\sigma(10^{12}\Omega^{-1} \text{cm}^{-1})$'},
        {'cell_id':'v','row_index':1,'column_index':1,'text':'2.58'}]}
    group={'property_name_raw':'conductivity','property_name_normalized':'DC conductivity',
           'unit_raw':r'$\Omega^{-1} \text{cm}^{-1}$','header_cell_ids':['h'],'scale_exponent':12,
           'points':[{'cell_id':'v','subject_cell_ids':['a']}]}
    result,_=materialize(table,{'groups':[group]},1)
    point=result[0]['points'][0]
    assert point['value_min']==2.58e-12
    assert point['value_raw']=='2.58'
    assert point['unit_normalized']=='S/cm'


def test_scalar_does_not_treat_ranges_or_symbols_as_values():
    assert scalar("1.50") == 1.5
    assert scalar("102,000") == 102000
    assert scalar("1.5 ± 0.2") == 1.5
    assert scalar("1-5") is None
    assert scalar("5/10") is None
    assert scalar("-") is None
    assert scalar("1.5a") is None


def test_scientific_cell_is_a_literal_not_a_formula():
    assert scalar(r'$2.00 \times 10^{3}$') == 2000
    assert scalar('4.5 × 10⁵') == 450000
    assert scalar('7.5 × 10<sup>5</sup>') == 750000
    assert scalar('2.0 × 10^3 / 4.5 × 10^5') is None
    assert scalar('2.0 × 10^3 + 1') is None
    assert scalar('2.0 × 10^3 g/mol') is None


def test_source_cell_value_not_model_value_and_subject_unresolved():
    table = {"table_id": "T1", "page": 0, "caption": "Properties", "cells": [
        {"cell_id": "a", "text": "A", "row_index": 1, "column_index": 0},
        {"cell_id": "h", "text": "Tg (°C)", "row_index": 0, "column_index": 1},
        {"cell_id": "v", "text": "85", "row_index": 1, "column_index": 1}]}
    group = {"property_name_raw": "Tg", "property_name_normalized": "glass transition temperature", "unit_raw": "°C",
             "header_cell_ids": ["h"], "points": [{"cell_id": "v", "subject_cell_ids": ["a"], "value": 999}]}
    result, audit = materialize(table, {"groups": [group]}, 1)
    assert result[0]["points"][0]["value_min"] == 85
    assert result[0]["points"][0]["sample_resolution_status"] == "unresolved"
    group["points"][0]["cell_id"] = "a"
    assert materialize(table, {"groups": [group]}, 1)[0] == []
    group["points"][0]["cell_id"] = "v"
    group["scale_exponent"] = 4
    assert materialize(table, {"groups": [group]}, 1)[0] == []
    group["scale_exponent"] = 0
    group["unit_raw"] = "MPa"
    assert materialize(table, {"groups": [group]}, 1)[0] == []


def test_typographic_units_and_scale_axis():
    assert canonical_unit(r'\mathrm { ~ \AA }') == 'angstrom'
    assert canonical_unit('Å') == 'angstrom'
    assert unit_in_header('Å', 'd (Å)')
    assert canonical_unit('°C.') == '°C'
    assert unit_in_header('°C', r'Tg ($^{\circ}$C)')
    assert unit_in_header('°C', r'$T_g^oC$')
    assert unit_in_header('°C', r'$T_g^{o} C$')
    assert not unit_in_header('°C', 'Tg oC')
    assert not unit_in_header('Pa', 'Sample')
    assert not unit_in_header('Pa', 'MPa')
    assert not unit_in_header('degree', 'Tg (°C)')
    assert not unit_in_header('°', 'Tg (°C)')
    assert unit_in_header('degree', 'angle (°)')
    assert header_applies({'row_index':0,'column_index':1,'column_span':2}, {'row_index':2,'column_index':2})
    assert not header_applies({'row_index':0,'column_index':1}, {'row_index':2,'column_index':2})


def test_uncertainty_and_shared_context_are_preserved():
    table = {'table_id':'T1','page':0,'caption':'Film properties','cells':[
        {'cell_id':'a','row_index':1,'column_index':0,'text':'A'},
        {'cell_id':'h','row_index':0,'column_index':1,'text':'Tg (°C)'},
        {'cell_id':'v','row_index':1,'column_index':1,'text':'85 ± 2'}]}
    group={'property_name_raw':'Tg','unit_raw':'°C','header_cell_ids':['h'],
           'points':[{'cell_id':'v','subject_cell_ids':['a']}]}
    result,_=materialize(table,{'groups':[group]},1)
    assert result[0]['measurement_context']['condition_status']=='reported'
    point=result[0]['points'][0]
    assert point['value_min']==85
    assert point['value_raw']=='85 ± 2'
    assert point['measurement_context']['other_conditions']['reported_uncertainty_raw']=='± 2'


def test_scale_from_unrelated_column_is_rejected():
    table={'table_id':'T1','page':0,'caption':'Properties','cells':[
        {'cell_id':'a','row_index':1,'column_index':0,'text':'A'},
        {'cell_id':'h1','row_index':0,'column_index':1,'text':'Mn (10^4)'},
        {'cell_id':'h2','row_index':0,'column_index':2,'text':'Mw'},
        {'cell_id':'v','row_index':1,'column_index':2,'text':'5'}]}
    group={'property_name_raw':'Mw','header_cell_ids':['h1','h2'],'scale_exponent':4,
           'points':[{'cell_id':'v','subject_cell_ids':['a']}]}
    result,audit=materialize(table,{'groups':[group]},1)
    assert result==[]
    assert audit[-1]['reason']=='scale_header_does_not_apply_to_response'


def test_same_cell_cannot_be_assigned_to_conflicting_samples():
    import copy
    table={'table_id':'T1','page':0,'caption':'Properties','cells':[
        {'cell_id':'a','row_index':1,'column_index':0,'text':'A'},
        {'cell_id':'b','row_index':2,'column_index':0,'text':'B'},
        {'cell_id':'h','row_index':0,'column_index':1,'text':'Tg (°C)'},
        {'cell_id':'v','row_index':1,'column_index':1,'text':'85'}]}
    group={'property_name_raw':'Tg','unit_raw':'°C','header_cell_ids':['h'],
           'points':[{'cell_id':'v','subject_cell_ids':['a']}]}
    conflicting=copy.deepcopy(group)
    conflicting['points'][0]['subject_cell_ids']=['b']
    result,audit=materialize(table,{'groups':[group,conflicting]},1)
    assert result==[]
    assert all(d['reason']=='source_cell_has_conflicting_subject_or_state' for d in audit)
