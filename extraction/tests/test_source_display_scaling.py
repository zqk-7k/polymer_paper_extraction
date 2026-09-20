from stages.source_display_scaling import scale_rule, repair_display_scales


def test_different_display_conventions():
    assert scale_rule(r'$\tan \delta \times 10^3$')[0] == .001
    assert scale_rule(r'$M_n/10^3$')[0] == 1000
    assert scale_rule(r'$M_n^e)\times 10^-5$')[0] == 100000
    assert scale_rule(r'$\overline{M}_N \times 10^6$') is None
    assert scale_rule('Mw/Mn') is None
    assert scale_rule('current (A)') is None
    assert scale_rule('Mv (viscosity index) × 10^-3') is None
    assert scale_rule('Mnemonic × 10^-3') is None


def fixture(monkeypatch):
    from stages import source_display_scaling as m
    table = {'table_id': 'T_0_0', 'caption': 'Dielectric data', 'page': 0, 'cells': [
        {'cell_id': 'T_0_0:r0000:c0000', 'row_index': 0, 'column_index': 0, 'text': 'Sample'},
        {'cell_id': 'T_0_0:r0000:c0001', 'row_index': 0, 'column_index': 1, 'text': 'tan δ × 10^3'},
        {'cell_id': 'T_0_0:r0001:c0000', 'row_index': 1, 'column_index': 0, 'text': 'A'},
        {'cell_id': 'T_0_0:r0001:c0001', 'row_index': 1, 'column_index': 1, 'text': '136.0'}]}
    monkeypatch.setattr(m, 'table_requests', lambda _: [table])
    stage0 = {}
    stage4 = {'property_series': [{'property_name_raw': 'tan δ', 'points': [
        {'value_raw': '136.0', 'value_min': 136000., 'value_max': 136000.,
         'coordinates': [{'name_raw': 'sample', 'value_raw': 'A'}],
         'evidence': [{'block_id': 'T_0_0', 'table_locator': {'cell_id': 'T_0_0:r0001:c0001'}}]}]}]}
    return stage0, stage4


def test_repair_from_source_not_repeated_multiplication(monkeypatch):
    src, data = fixture(monkeypatch)
    first, audit = repair_display_scales(data, src)
    p = first['property_series'][0]['points'][0]
    assert p['value_min'] == .136 and p['value_raw'] == '136.0'
    assert p['coordinates'][0]['value_raw'] == 'A'
    second, again = repair_display_scales(first, src)
    assert second == first and not again['changes']
    assert len(audit['changes']) == 1
    assert data['property_series'][0]['points'][0]['value_min'] == 136000.


def test_no_cross_axis_scale(monkeypatch):
    src, data = fixture(monkeypatch)
    data['property_series'][0]['points'][0]['evidence'][0]['table_locator']['cell_id'] = 'T_0_0:r0001:c0000'
    assert repair_display_scales(data, src)[0] == data


def test_previously_empty_context_remains_schema_valid(monkeypatch):
    from schema.polymer_schema import MeasurementContext
    src, data = fixture(monkeypatch)
    data['property_series'][0]['points'][0]['measurement_context'] = {
        'condition_status': 'not_reported', 'other_conditions': {}}
    out, _ = repair_display_scales(data, src)
    ctx = out['property_series'][0]['points'][0]['measurement_context']
    validated = MeasurementContext.model_validate(ctx)
    assert validated.condition_status == 'reported'
    assert not ctx.get('temperature') and not ctx.get('method')


def test_interval_scaling_is_positive_and_preserves_order(monkeypatch):
    from stages import source_display_scaling as m
    src, data = fixture(monkeypatch)
    table = m.table_requests(src)[0]
    table['cells'][-1]['text'] = '40–70'
    out, audit = repair_display_scales(data, src)
    p = out['property_series'][0]['points'][0]
    assert (p['value_min'], p['value_max']) == (.04, .07)
    table['cells'][1]['text'] = 'M_n/10^3'
    out, audit = repair_display_scales(data, src)
    p = out['property_series'][0]['points'][0]
    assert (p['value_min'], p['value_max']) == (40000, 70000)


def test_equal_and_conflicting_nested_headers(monkeypatch):
    from stages import source_display_scaling as m
    src, data = fixture(monkeypatch)
    table = m.table_requests(src)[0]
    table['cells'][-1]['row_index'] = 2
    table['cells'].append({'cell_id': 'child', 'row_index': 1, 'column_index': 1,
                           'text': 'tan δ × 10^3'})
    out, audit = repair_display_scales(data, src)
    assert len(audit['changes']) == 1
    assert audit['changes'][0]['header_ids'] == ['T_0_0:r0000:c0001', 'child']
    table['cells'][-1]['text'] = 'tan δ × 10^4'
    out, audit = repair_display_scales(data, src)
    assert out == data and audit['skipped'][0]['reason'] == 'conflicting_source_scale'


def test_series_unit_conversion_is_not_overwritten(monkeypatch):
    src, data = fixture(monkeypatch)
    series = data['property_series'][0]
    series.update(unit_raw='Pa', unit_normalized='MPa')
    out, audit = repair_display_scales(data, src)
    assert out == data and audit['skipped'][0]['reason'] == 'unit_conversion_already_applied'
    # Point units override the inherited series units when explicitly present.
    series['points'][0].update(unit_raw='1', unit_normalized='1')
    out, audit = repair_display_scales(data, src)
    assert out['property_series'][0]['points'][0]['value_min'] == .136
