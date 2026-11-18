import json
from pathlib import Path

from stages.source_figure_links import build_figure_links, references
from stages.source_table_extraction import build_source_extraction
from tools.source_extraction_export import build_source_export, figure_file_link


def test_reference_lists_ranges_supplements_and_number_boundaries():
    assert references('Figures 1, 2 and 4 show curves; Figs. S1–S3 compare samples.')=={
        ('figure','1'),('figure','2'),('figure','4'),('figure','S1'),('figure','S2'),('figure','S3')}
    assert references('Fig. 10(a) and Scheme 2')=={('figure','10'),('scheme','2')}


def test_figure_only_result_is_located_without_inventing_property_value(tmp_path):
    image=tmp_path/'curve #1.png';image.write_bytes(b'fixture')
    data=build_source_extraction({'document_id':'reference_no_example','elements':[
        {'block_id':'P1','type':'text','text':'The dielectric behavior is shown in Figure 1.'},
        {'block_id':'P2','type':'text','text':'Figure 10 shows a different material.'},
        {'block_id':'I1','type':'image','caption':'Figure 1. Dielectric spectra.', 'image_path':str(image)}]})
    links=build_figure_links(data)
    assert not data['observations']
    assert [b['block_id'] for b in links[0]['mention_blocks']]==['P1']
    assert not links[0]['value_extraction_required']
    source=tmp_path/'source';(source/data['document_id']).mkdir(parents=True)
    (source/data['document_id']/'source_extraction.json').write_text(json.dumps(data),encoding='utf8')
    result=build_source_export(source,tmp_path/'export')
    assert result['counts']['available_figure_links']==1 and result['counts']['usable_property']==0
    html=(tmp_path/'export/report.html').read_text(encoding='utf8')
    assert '打开原图片' in html and 'curve%20%231.png' in html
    assert 'The dielectric behavior' in html


def test_missing_image_is_explicit_and_caption_markup_is_escaped(tmp_path):
    assert figure_file_link('not-present.png',tmp_path/'report.html') is None
    assert figure_file_link('javascript:alert(1)',tmp_path/'report.html') is None
    data={'document_id':'doc','source_blocks':[],'source_figure_blocks':[
        {'block_id':'I1','caption':'Figure 3. <script>bad</script>','image_path':None}],'observations':[]}
    from tools.source_extraction_export import render_source_report
    render_source_report(data,tmp_path/'report.html')
    text=(tmp_path/'report.html').read_text(encoding='utf8')
    assert '&lt;script&gt;bad&lt;/script&gt;' in text and '图片文件未定位' in text


def test_same_block_reference_links_observation_without_asserting_curve_binding():
    data={'document_id':'doc','source_blocks':[{'block_id':'P1','text':'The value is 3.2, as shown in Figure 2.'}],
          'source_figure_blocks':[{'block_id':'I2','caption':'Figure 2. Data.','image_path':'i2.png'}],
          'observations':[{'observation_id':'o1','source_block_id':'P1'}]}
    link=build_figure_links(data)[0]
    assert link['related_observation_ids']==['o1']
    assert link['relation_basis']=='explicit_figure_reference_in_same_block'


def test_image_path_resolves_relative_to_batch_input_ancestors(tmp_path):
    source=tmp_path/'pipeline/processed/documents';source.mkdir(parents=True)
    image=tmp_path/'pipeline/organized/reference_no_new/images/chart.png'
    image.parent.mkdir(parents=True);image.write_bytes(b'fixture')
    report=tmp_path/'different/output/report.html'
    link=figure_file_link('organized/reference_no_new/images/chart.png',report,[source])
    assert Path(link['resolved_image_path'])==image
