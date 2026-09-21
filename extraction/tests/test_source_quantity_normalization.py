from stages.source_quantity_normalization import normalization_rule, normalize_source_quantities


def test_temperature_shift_is_not_absolute_and_ambiguous_window_is_skipped():
    assert normalization_rule('onset temperature shift', 'K')[:2] == (1., 0.)
    assert normalization_rule('glass transition temperature depression', 'K')[:2] == (1., 0.)
    assert normalization_rule('processing temperature window', 'K') is None
from stages.stage4_direct_text_supplement import parse_value


def test_spaced_digits_require_math_context_but_thousands_are_supported():
    assert parse_value('1 2 7 , 0 0 0') is None
    assert parse_value('1 2 7 , 0 0 0', source_quote='Mw $=1 2 7 , 0 0 0$')==127000
    assert parse_value('63 000') is None
    assert parse_value('63 000',source_quote='Mw $=63 000$')==63000
    assert parse_value('12 345',source_quote='Entries 12 345 were checked.') is None
    assert parse_value('1 2',source_quote='Samples 1 2 were used') is None


def test_temperature_units_not_intervals_and_no_inference():
    assert normalization_rule('glass transition temperature','K')[:3]==(1.,-273.15,'°C')
    assert normalization_rule('temperature difference','K')[:3]==(1.,0.,'°C')
    assert normalization_rule('molecular weight','K') is None
    assert normalization_rule('glass transition temperature','') is None
    assert normalization_rule('molecular weight','million g/mol')[:3]==(1e6,0.,'g/mol')


def test_raw_evidence_unchanged_and_idempotent():
    record={'property_name_normalized':'glass transition temperature','value_raw':'339.4','value_min':339.4,
            'value_max':339.4,'unit_raw':'K','unit_normalized':'K','evidence':[{'source_sentence':'339.4'}]}
    doc={'properties':[record]}
    out,audit=normalize_source_quantities(doc)
    p=out['properties'][0]
    assert abs(p['value_min']-66.25)<1e-9 and p['unit_normalized']=='°C'
    assert p['value_raw']=='339.4' and p['unit_raw']=='K' and p['evidence']==record['evidence']
    assert doc['properties'][0]['value_min']==339.4
    again,audit2=normalize_source_quantities(out)
    assert again==out and not audit2['changes']
