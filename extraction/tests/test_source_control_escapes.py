from stages.source_control_escapes import decode_control_escapes, restore_source_control_spellings
from stages.stage4_direct_text_supplement import merge_text, source_temperature_unit, surface_key


def test_only_equivalent_control_spellings_match():
    assert surface_key(r'48.8<sup>\x01</sup>C') == surface_key(r'48.8<sup>\u0001</sup>C')
    assert surface_key(r'48.8<sup>\x02</sup>C') != surface_key(r'48.8<sup>\u0001</sup>C')
    assert surface_key('12') != surface_key(r'1\x012')
    assert decode_control_escapes(r'\x41 and \times') == r'\x41 and \times'
    assert restore_source_control_spellings(r'x\x01C', r'y\u0001C') == r'x\u0001C'


def test_context_required_to_resolve_damaged_temperature_unit():
    unit = r'<sup>\x01</sup>C'
    assert source_temperature_unit(unit, 'glass transition temperature', 'A: 60 °C') == '°C'
    assert source_temperature_unit(unit, 'electric charge', 'A: 60 °C') is None
    assert source_temperature_unit(unit, 'glass transition temperature', 'A: 60 C') is None
    assert source_temperature_unit(r'<sup>\x01</sup>g', 'temperature', '60 °C') is None
    assert source_temperature_unit(r'<sup>\x02</sup>C', 'temperature', '60 °C') is None


def test_source_quote_and_raw_unit_keep_original_escaped_spelling():
    source = r'Polymer A: Tg=65 °C and Tm=140<sup>\u0001</sup>C.'
    fact = {'block_id': 'p', 'quote': r'Tm=140<sup>\x01</sup>C', 'value_raw': '140',
            'property_name': 'melting temperature', 'unit_raw': r'<sup>\x01</sup>C',
            'sample_label': 'Polymer A', 'sample_evidence_block_id': 'p', 'role': 'material_property'}
    result, audit = merge_text({}, {'elements': [{'block_id': 'p', 'page': 0, 'type': 'text', 'text': source}]}, [{'facts': [fact]}])
    assert audit['decisions'][0]['accepted']
    series = result['property_series'][0]
    assert series['unit_normalized'] == '°C'
    assert series['unit_raw'] == r'<sup>\u0001</sup>C'
    assert series['points'][0]['evidence'][0]['source_sentence'] in source
    assert series['measurement_context']['other_conditions']['unit_resolution_status'].startswith('inferred')
    series['unit_normalized'] = 'x01C'
    series['points'][0]['unit_normalized'] = 'x01C'
    repaired, audit = merge_text(result, {'elements': [{'block_id': 'p', 'page': 0, 'type': 'text', 'text': source}]}, [])
    assert len(repaired['property_series']) == 1
    assert len(audit['retained_unit_repairs']) == 1
    assert repaired['property_series'][0]['points'][0]['unit_normalized'] == '°C'
