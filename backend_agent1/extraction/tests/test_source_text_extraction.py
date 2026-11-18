from copy import deepcopy
import pytest

from stages.source_text_extraction import build_text_observations
from stages.source_table_extraction import build_source_extraction
from tools.source_extraction_export import validate_source_result, build_source_export


def extract(text):
    return build_text_observations('reference_no_test', [{'block_id': 'P1', 'type': 'text', 'text': text}])


def test_respectively_has_two_explicit_bindings_and_exact_source_spans():
    text = 'The elongation at break of the polyamic acid and polyimide was 6% and 29%, respectively.'
    rows = extract(text)
    assert [(r['article_sample_label_raw'], r['value_raw']) for r in rows] == [('polyamic acid','6'), ('polyimide','29')]
    for row in rows:
        for span in row['source_spans'].values():
            assert text[span['start']:span['end']] == span['text']
        assert row['value_normalized'] is None and row['sample_id'] is None


@pytest.mark.parametrize('text', [
    'The elongation at break of PAA was not 6%.',
    'The elongation at break of PAA would be 6%.',
    'The elongation at break of it was 6%.',
    'The elongation at break of PAA and PI was 6% and 29%.',
    'The elongation at break of PAA was 6% and 29%.',
    'Elongation at break was measured at 6% strain.',
    'The elongation at break of PAA was 6% higher than PI.',
    'The increase in the elongation at break of PAA was 6%.',
    'If the elongation at break of PAA is 6%, the model changes.',
])
def test_ambiguous_negated_hypothetical_or_condition_sentences_are_not_published(text):
    assert not extract(text)


def test_qualifier_and_repeated_mentions_remain_explicit():
    rows = extract('The elongation at break of PAA is only 6%. The elongation at break of PAA is about 6%.')
    assert len(rows) == 2 and rows[0]['observation_id'] != rows[1]['observation_id']
    assert 'only' in rows[0]['value_qualifier_raw'] and 'about' in rows[1]['value_qualifier_raw']


def test_normalized_stage0_null_section_is_supported_and_references_are_skipped():
    block = {'block_id': 'P1', 'type': 'text', 'section': None,
             'text': 'The elongation at break of PAA is 6%.'}
    assert len(build_text_observations('reference_no_test', [block])) == 1
    assert not build_text_observations('reference_no_test', [{**block, 'section': 'References'}])


def test_tensile_strengths_do_not_invent_break_or_yield_endpoint():
    rows=extract('The tensile strengths of polyamic acid and polyimide are 40.5 MPa and 100 MPa, respectively.')
    assert [(r['article_sample_label_raw'],r['value_raw']) for r in rows]==[('polyamic acid','40.5'),('polyimide','100')]
    assert all(r['standard_property_code']=='STD:tensile_strength_unspecified' for r in rows)
    assert all('tensile_endpoint_unspecified' in r['standard_mapping_reasons'] for r in rows)
    assert not extract('The tensile strength of PAA is 6%.')


def test_melting_point_is_a_named_value_with_source_unit():
    rows=extract('The melting point of sPP is about 130 °C.')
    assert rows[0]['value_raw']=='130' and rows[0]['unit_raw']=='°C'
    assert rows[0]['standard_property_code']=='STD:melting_temperature'


def test_frozen_text_review_is_local_and_source_change_only_rejects_affected_record():
    from stages.sample_catalog import digest
    from stages.source_text_reviews import reviewed_text_observations
    text='PI Tg 230 C DSC'
    def sp(s):
        i=text.index(s);return {'start':i,'end':i+len(s),'text':s}
    item={'review_id':'r1','document_id':'doc','block_id':'P1','source_text_sha256':digest(text),
          'spans':{k:sp(s) for k,s in [('sample','PI'),('property','Tg'),('value','230'),('unit','C'),('method','DSC')]},
          'reviewer':'test','basis':'Explicit sentence','standard_property_code':'STD:glass_transition_temperature'}
    config={'schema_version':'source_text_reviews.v1','reviews':[item]}
    rows,issues=reviewed_text_observations('doc',[{'block_id':'P1','text':text}],config)
    assert len(rows)==1 and not issues
    assert rows[0]['condition_context_raw'][0]['value_raw']=='DSC'
    rows,issues=reviewed_text_observations('doc',[{'block_id':'P1','text':text.replace('230','240')}],config)
    assert not rows and issues[0]['reason']=='review_source_changed_or_invalid'
    assert reviewed_text_observations('other',[],config)==([],[])


def test_text_only_document_enters_actual_export_and_changed_source_is_rejected(tmp_path):
    import json
    stage0 = {'document_id': 'reference_no_test', 'elements': [{'block_id':'P1', 'type':'text', 'page':0,
              'source_block_index':0, 'text':'The elongation at break of PAA is only 6%.'}]}
    data = build_source_extraction(stage0)
    validate_source_result(data)
    assert data['counts']['text_observation_count'] == 1 and data['counts']['table_count'] == 0
    root = tmp_path / 'source'
    (root / 'reference_no_test').mkdir(parents=True)
    (root / 'reference_no_test/source_extraction.json').write_text(json.dumps(data), encoding='utf8')
    output = tmp_path / 'export'
    result = build_source_export(root, output)
    assert result['counts']['usable_property'] == 1
    assert json.loads((output / 'usable_extractions.jsonl').read_text())['value_raw'] == '6'
    assert '查看原句' in (output / 'report.html').read_text(encoding='utf8')
    changed = deepcopy(data)
    changed['source_blocks'][0]['text'] = 'The elongation at break of PAA is only 7%.'
    with pytest.raises(ValueError, match='source spans'):
        validate_source_result(changed)
