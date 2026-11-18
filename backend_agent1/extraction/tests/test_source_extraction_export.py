import json
from pathlib import Path

import pytest

from stages.source_table_extraction import build_source_extraction
from tools.source_extraction_export import build_source_export
from tools.rebuild_source_extraction import rebuild
from tools.production_export import build_parser
from tests.test_source_table_extraction import source


def setup(tmp_path):
    data = source('<table><tr><td>Sample</td><td>Novel property</td></tr><tr><td>A</td><td>1 ± 0.2</td></tr></table>')
    root = tmp_path / 'input'
    directory = root / data['document_id']
    directory.mkdir(parents=True)
    result = build_source_extraction(data)
    path = directory / 'source_extraction.json'
    path.write_text(json.dumps(result), encoding='utf-8')
    return root, path, result


def test_default_source_view_exports_without_standard_codes(tmp_path):
    root, path, result = setup(tmp_path)
    before = path.read_bytes()
    summary = build_source_export(root, tmp_path / 'export')
    assert summary['counts']['usable_property'] == 1
    assert path.read_bytes() == before
    row = json.loads((tmp_path / 'export/usable_extractions.jsonl').read_text(encoding='utf-8'))
    assert row['value_raw'] == '1 ± 0.2' and row['sample_id'] is None
    assert build_parser().parse_args(['--publication-root', str(root), '--output-dir', 'out']).view == 'source'


@pytest.mark.parametrize('field,value', [('value_raw', '999'), ('property_header_path', ['Invented']), ('value_normalized', '999')])
def test_tampered_source_representation_is_not_exported(tmp_path, field, value):
    root, path, data = setup(tmp_path)
    data['observations'][0][field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        build_source_export(root, tmp_path / 'export')
    assert not (tmp_path / 'export').exists()


def test_independent_rebuild_needs_only_existing_source_table(tmp_path):
    data = source('<table><tr><td>Sample</td><td>Unknown</td></tr><tr><td>A</td><td>9</td></tr></table>')
    root = tmp_path / 'input'
    directory = root / data['document_id']
    directory.mkdir(parents=True)
    (directory / 'stage0_blocks.json').write_text(json.dumps(data))
    result = rebuild(root, tmp_path / 'missing-strict-publication', tmp_path / 'output')
    assert result['counts']['usable_property'] == 1
    assert result['api_requests'] == 0 and result['original_inputs_unchanged']
