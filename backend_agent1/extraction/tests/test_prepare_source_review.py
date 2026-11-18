import json
from tools.prepare_source_review import prepare
from tools.source_evidence_view import evidence_view
from tests.test_source_table_extraction import source


def test_review_packet_is_source_only_and_empty_answers_are_not_passes(tmp_path):
    d=tmp_path/'input/reference_no_test';d.mkdir(parents=True)
    (d/'stage0_blocks.json').write_text(json.dumps(source('<table><tr><td>Sample</td><td>Tg</td></tr><tr><td>A</td><td>120</td></tr></table>')),encoding='utf-8')
    summary=prepare(d.parent,tmp_path/'out',count=2)
    packet=json.loads((tmp_path/'out/review_packet.json').read_text(encoding='utf-8'))
    assert summary['targets']==2 and summary['review_status']=='awaiting_independent_review'
    assert all(t['review']['role'] is None for t in packet['targets'])
    assert 'standard_property_code' not in json.dumps(packet)


def test_source_markup_cannot_close_embedded_data_script():
    html=evidence_view({'observations':[],'tables':[{'caption':'</script><script>alert(1)</script>'}]})
    assert '</script><script>alert' not in html
    assert r'\u003c/script>' in html
