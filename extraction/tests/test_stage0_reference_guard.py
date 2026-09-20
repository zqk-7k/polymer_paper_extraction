import pytest

from stages.stage0_reference_guard import is_mislabeled_characterization
from stages.stage0_load_document import load_document_elements
from schema.polymer_schema import SourceDocument
from test_stage0_load_document import element, source_document
from stages.stage0_load_document import run_stage0
import json


@pytest.mark.parametrize('text,section,expected', [
    ('Characterization data for P-PEG: yield 81.2%. Mw: 5432 (GPC). 1H NMR (500 MHz).', 'Experimental section', True),
    ('Characterisation of resin A: yield 50%. SEC, NMR.', 'Methods', True),
    ('[10] Characterization data for polymers. NMR and GPC. 2002, 34, 550.', 'Methods', False),
    ('Characterization of polymer synthesis, NMR and GPC. 2002, 34, 550.', 'References and Notes', False),
    ('Characterization data for A: NMR and GPC 500.', '参考文献', False),
    ('Characterization of new polymers. 2002, 34, 550.', 'Methods', False),
    ('A. Author; B. Author. Polymer 2002, 10, 500.', 'Results', False),
    ('Characterization data for A: yield 50%. NMR 500.', '', False),
])
def test_guard(text, section, expected):
    assert is_mislabeled_characterization({'element_type': 'references', 'text': text, 'section': section}) is expected


def test_reference_heading_wins_and_recovery_preserves_source():
    text = 'Characterization data for resin A: yield 50%. GPC; 1H NMR at 500 MHz.'
    assert not is_mislabeled_characterization({'element_type': 'references', 'text': text, 'section': 'Methods'}, 'References')
    source = SourceDocument.model_validate(source_document([
        element('P_0_0', 'title', 0, text='Experimental', title_level=2),
        element('R_0_1', 'references', 1, text=text, section='Methods'),
        element('R_0_2', 'references', 2, text='1. Author. Journal 2004, 10, 100.'),
    ]))
    result = load_document_elements(source)
    assert [e.block_id for e in result.elements] == ['P_0_0', 'R_0_1']
    recovered = result.elements[1]
    assert recovered.type == 'text' and recovered.text == text
    assert tuple(recovered.bbox) == (1, 2, 3, 4) and recovered.source_block_index == 1
    assert result.warnings[-1]['code'] == 'experimental_paragraph_recovered'


def test_old_filtered_cache_is_repaired_once(tmp_path):
    doc = source_document([
        element('P_0_0', 'title', 0, text='Experimental', title_level=2),
        element('R_0_1', 'references', 1, text='Characterization data for A: yield 50%. NMR 500; GPC.', section='Methods'),
    ])
    source = tmp_path / 'reference_no_0000001_document.json'
    source.write_text(json.dumps(doc), encoding='utf-8')
    path, _ = run_stage0(source, tmp_path / 'out')
    stale = json.loads(path.read_text(encoding='utf-8'))
    stale['elements'] = [e for e in stale['elements'] if e['block_id'] != 'R_0_1']
    path.write_text(json.dumps(stale), encoding='utf-8')
    _, cached = run_stage0(source, tmp_path / 'out')
    assert not cached
    assert any(e['block_id'] == 'R_0_1' for e in json.loads(path.read_text(encoding='utf-8'))['elements'])
    assert run_stage0(source, tmp_path / 'out')[1]


def test_actual_reference_heading_does_not_cause_cache_invalidation_loop(tmp_path):
    doc = source_document([
        element('P_0_0', 'title', 0, text='References', title_level=2),
        element('R_0_1', 'references', 1, text='Characterization data for A: yield 50%. NMR 500; GPC.', section='Methods'),
    ])
    source = tmp_path / 'reference_no_0000001_document.json'
    source.write_text(json.dumps(doc), encoding='utf-8')
    run_stage0(source, tmp_path / 'out')
    assert run_stage0(source, tmp_path / 'out')[1]
