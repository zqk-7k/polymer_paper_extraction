from stages.stage4_direct_table_supplement import canonical_unit
from stages.source_unit_font_repair import repair_source_unit_fonts


def test_nested_font_units_preserve_dimensions_and_citation_digits():
    assert canonical_unit(r'$\mathrm { { J } / \mathrm { { g } } }$') == 'J/g'
    assert canonical_unit(r'$\mathbf { J } / \mathbf { g }$') == 'J/g'
    assert canonical_unit(r'\mathrm { g \cdot m o l ^ { - 1 } }') == 'g·mol-1'
    assert canonical_unit(r'\mathrm{J/g^{31}}') == 'J/g31'
    assert canonical_unit(r'\mathrm{\hat{C}}') != 'C'


def test_unit_repair_requires_verbatim_source_and_keeps_values():
    raw = r'$\mathbf { J } / \mathbf { g }$'
    record = dict(value_raw='209', value_min=209, unit_raw=raw,
                  unit_normalized='mathbfJ/mathbfg', evidence=[{'block_id': 'P_0_1'}])
    stage4 = {'properties': [record]}
    assert repair_source_unit_fonts(stage4, {'elements': []})['changes'] == []
    source = {'elements': [{'block_id': 'P_0_1', 'text': '209 ' + raw}]}
    assert len(repair_source_unit_fonts(stage4, source)['changes']) == 1
    assert record['value_min'] == 209 and record['value_raw'] == '209'
    assert record['unit_raw'] == raw and record['unit_normalized'] == 'J/g'
    assert repair_source_unit_fonts(stage4, source)['changes'] == []
