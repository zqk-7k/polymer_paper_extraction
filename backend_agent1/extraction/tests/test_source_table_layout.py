from stages.source_table_extraction import build_source_extraction
from tests.test_source_table_extraction import source


def rows(body):
    return build_source_extraction(source(body))['observations']


def test_column_groups_keep_material_separate_from_repeated_property():
    data=rows('<table><tr><td colspan="2">HS</td><td colspan="2">HI</td></tr><tr><td>d</td><td>I/I0</td><td>d</td><td>I/I0</td></tr><tr><td>4.2</td><td>100</td><td>3.1</td><td>99</td></tr></table>')
    assert [r['article_sample_label_raw'] for r in data]==['HS','HS','HI','HI']
    assert data[0]['property_header_path']==['d']


def test_blank_corner_state_rows_inherit_rowspan_sample_and_keep_state():
    data=rows('<table><tr><td></td><td>L</td><td>a</td></tr><tr><td rowspan="2">P(T)</td><td>Ox = 47</td><td>Ox = -4</td></tr><tr><td>Red = 53</td><td>Red = 1</td></tr></table>')
    assert len(data)==4
    assert all(r['article_sample_label_raw']=='P(T)' for r in data)
    assert data[0]['condition_context_raw'][0]['value_raw']=='Ox'
    assert data[0]['article_sample_key']!=data[2]['article_sample_key']


def test_spanning_sample_header_combines_blend_family_and_component():
    data=rows('<table><tr><td colspan="2">Sample</td><td>Tg</td></tr><tr><td rowspan="2">50/50 blend</td><td>NBR18/PEO</td><td>-70</td></tr><tr><td>NBR43/PEO</td><td>-49</td></tr></table>')
    assert len(data)==2
    assert data[0]['article_sample_label_raw']=='50/50 blend | NBR18/PEO'
    assert data[1]['article_sample_label_raw']=='50/50 blend | NBR43/PEO'


def test_concentration_is_condition_and_group_material_does_not_leak():
    data=rows('<table><tr><td>Concentration (%)</td><td>Conductivity (S/cm)</td></tr><tr><td>PVC</td><td>2.5</td></tr><tr><td colspan="2">Monomer 1</td></tr><tr><td>2</td><td>5.8</td></tr><tr><td colspan="2">Notes</td></tr><tr><td>1</td><td>9</td></tr></table>')
    prop=[r for r in data if r['record_kind']=='property']
    assert [r['article_sample_label_raw'] for r in prop]==['PVC','Monomer 1',None]
    assert prop[1]['condition_context_raw'][0]['value_raw']=='2'
    assert prop[1]['extraction_status']=='usable'


def test_two_row_property_axis_is_preserved_for_sample_columns():
    data=rows('<table><tr><td></td><td></td><td>poly(MPC)</td><td>poly(METAI)</td></tr><tr><td rowspan="2">Water</td><td>static</td><td>3</td><td>36</td></tr><tr><td>advancing</td><td>13</td><td>69</td></tr></table>')
    assert len(data)==4
    assert data[2]['property_header_path']==['Water','advancing']
    assert data[2]['article_sample_label_raw']=='poly(MPC)'


def test_conditions_are_not_reclassified_as_materials():
    data=rows('<table><tr><td>Concentration (%)</td><td>Tg</td></tr><tr><td>2</td><td>120</td></tr></table>')
    assert all(r['article_sample_label_raw'] is None for r in data)


def test_conformation_matrix_retains_energy_axis_and_group_heading_is_not_observation():
    data=rows('<table><tr><td></td><td>Chair</td><td>Boat</td></tr><tr><td colspan="3">P4THPMA</td></tr><tr><td>MMX (kJ mol-1)</td><td>33.348</td><td>53.517</td></tr></table>')
    assert len(data)==2
    assert data[0]['property_header_path']==['MMX (kJ mol-1)','Chair']
    assert data[0]['article_sample_label_raw']=='P4THPMA'
    assert data[0]['condition_context_raw'][0]['value_raw']=='Chair'


def test_headerless_property_values_preserve_first_numeric_row():
    from tests.test_source_table_extraction import source
    from stages.source_table_extraction import build_source_extraction
    data = source('<table><tr><td>Refractive index</td><td>1.47</td></tr><tr><td>Colour</td><td>yellow</td></tr><tr><td>Viscosity (CPS)</td><td>610</td></tr></table>', 'Properties of the resin')
    rows = build_source_extraction(data)['observations']
    assert [r['value_raw'] for r in rows] == ['1.47', 'yellow', '610']
    assert rows[0]['property_name_raw'] == 'Refractive index'
    assert rows[0]['article_sample_label_raw'] != '1.47'


def test_two_condition_axes_do_not_publish_time_as_optical_property():
    from tests.test_source_table_extraction import source
    from stages.source_table_extraction import build_source_extraction
    data = source('<table><tr><td rowspan="2">Wave length (nm)</td><td colspan="2">Curing time (s)</td></tr><tr><td>10</td><td>20</td></tr><tr><td>400</td><td>90</td><td>91</td></tr></table>', 'Optical response in arbitrary units')
    rows = build_source_extraction(data)['observations']
    assert [r['value_raw'] for r in rows] == ['90', '91']
    assert all(r['property_name_raw'] is None and r['extraction_status'] == 'needs_review' for r in rows)
    assert any(c['value_raw'] == '400' for c in rows[0]['condition_context_raw'])
