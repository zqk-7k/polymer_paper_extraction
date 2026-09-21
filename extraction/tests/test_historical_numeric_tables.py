from stages.stage4_direct_table_supplement import (
    table_cell_scalar, middle_dot_decimal_value, table_reported_interval,
    footnoted_thermal_components)


def test_signed_full_cell_not_arithmetic():
    assert table_cell_scalar('- 9') == -9
    assert table_cell_scalar('+ 2') == 2
    assert table_cell_scalar('5 - 9') is None


def test_three_decimal_places_need_column_corroboration():
    a={'cell_id':'a','column_index':1,'text':'1·071'}
    b={'cell_id':'b','column_index':1,'text':'1·222'}
    assert middle_dot_decimal_value(a, {'a':a}) is None
    assert middle_dot_decimal_value(a, {'a':a,'b':b}) == 1.071
    b['column_index']=2
    assert middle_dot_decimal_value(a, {'a':a,'b':b}) is None
    a['text']='1·071 + 3'
    assert middle_dot_decimal_value(a, {'a':a,'b':b}) is None


def test_ascii_hyphen_is_thermal_interval_not_two_scalars():
    assert table_reported_interval('24-27','melting temperature')['maximum'] == 27
    assert table_reported_interval('-24--20','melting temperature')['minimum'] == -24
    assert table_reported_interval('24-27','arithmetic expression') is None
    assert table_reported_interval('27-24','melting temperature') is None
    assert table_reported_interval('24-27+4','melting temperature') is None


def test_footnote_groups_preserve_different_heating_states():
    notes='c) Endotherms in the first heating trace (20 °C/min).\nd) Endotherm found after annealing (30 min).'
    points=footnoted_thermal_components(r'$138,154^{c)}$ $155^{d)}$', 'melting temperature', notes)
    assert [p['value'] for p in points] == [138,154,155]
    assert [p['role'] for p in points] == ['footnote_c_peak_1','footnote_c_peak_2','footnote_d_peak_1']
    assert 'annealing' in points[-1]['source_footnote_definition']
    assert footnoted_thermal_components(r'$138,154^{c)}$', 'melting temperature', '') == []
    assert footnoted_thermal_components(r'$138,154^{c)}$', 'melting temperature', 'c) Calculated molecular weight.') == []
    assert footnoted_thermal_components('138,154+155', 'melting temperature', notes) == []
