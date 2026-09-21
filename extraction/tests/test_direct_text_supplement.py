from stages.stage4_direct_text_supplement import merge_text, parse_value


def test_literal_text_validation_rejects_invented_number():
    element = {"block_id": "b1", "type": "text", "page": 0, "text": "Polymer A had a Tg of 85 °C."}
    fact = {"block_id": "b1", "quote": element['text'], "property_name": "glass transition temperature",
            "value_raw": "85", "unit_raw": "°C", "sample_label": "Polymer A",
            "sample_evidence_block_id": "b1", "role": "material_property"}
    out,audit=merge_text({}, {'elements':[element]}, [{'facts':[fact]}])
    assert out['property_series'][0]['points'][0]['value_min']==85
    fact['value_raw']='99'
    assert not merge_text({}, {'elements':[element]}, [{'facts':[fact]}])[0]['property_series']
    fact['value_raw']='8'
    assert not merge_text({}, {'elements':[element]}, [{'facts':[fact]}])[0]['property_series']
    assert parse_value('2.4 × 10^{4}') == 24000
    assert parse_value('85-90') is None


def test_overlapping_text_chunks_do_not_repeat_molecular_weight_aliases():
    doc = {'elements': [{'block_id': 'p', 'type': 'text', 'page': 0,
                        'text': 'Polymer A: Mw = 5432; Mw/Mn = 1.43.'}]}
    fact = {'block_id': 'p', 'quote': 'Mw = 5432', 'property_name': 'weight-average molecular weight (Mw)',
            'value_raw': '5432', 'sample_label': 'Polymer A', 'sample_evidence_block_id': 'p', 'role': 'material_property'}
    other = dict(fact, property_name='weight-average molecular weight')
    result, audit = merge_text({}, doc, [{'facts': [fact]}, {'facts': [other]}])
    assert len(result['property_series']) == 1
    assert audit['decisions'][-1]['reason'] == 'duplicate_same_source_fact'


def test_same_number_for_different_quantities_is_not_merged():
    from stages.stage4_direct_text_supplement import text_fact_identity
    assert text_fact_identity('b', 'Mw', '1.5', None, 'A') != text_fact_identity('b', 'Mn', '1.5', None, 'A')
    assert text_fact_identity('b', 'Tg', '85', 'C', 'A') != text_fact_identity('b', 'Tm', '85', 'C', 'A')
    assert text_fact_identity('b', 'Tg', '85', 'C', 'A') != text_fact_identity('c', 'Tg', '85', 'C', 'A')


def test_different_overlapping_quotes_preserve_one_fact():
    text = 'Polymer A had a Tg of 85 °C. This was measured using DSC.'
    doc = {'elements': [{'block_id':'b1','type':'text','page':0,'text':text}]}
    fact = {'block_id':'b1','quote':'Tg of 85 °C','property_name':'glass transition temperature',
            'value_raw':'85','unit_raw':'°C','sample_label':'Polymer A',
            'sample_evidence_block_id':'b1','role':'material_property'}
    other = dict(fact,quote=text)
    result,audit=merge_text({},doc,[{'facts':[fact]},{'facts':[other]}])
    assert len(result['property_series']) == 1
    assert audit['decisions'][-1]['reason']=='duplicate_same_source_fact'
