"""Verified native agent1 delivery -> existing directory contract, without inference."""
from pathlib import Path
from copy import deepcopy
import argparse
import hashlib
import json
import os
import re
import sys


def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.writing')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf8')
    temporary.replace(path)


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verified_bundle(job, store, pdf):
    job, store = Path(job), Path(store)
    state, pointer = read(job / 'run.json'), read(job / 'adopted.json')
    if state.get('status') != 'DELIVERED':
        raise ValueError('Agent1 has not delivered; drafts and historical fallback are prohibited')
    source_hash = file_hash(pdf)
    if any(x.get('source_sha256') != source_hash for x in (state, pointer)):
        raise ValueError('Agent1/PDF hash mismatch')
    if pointer.get('job_id') != job.name:
        raise ValueError('Adoption pointer belongs to another job')
    version = pointer.get('version', '')
    if not re.fullmatch(r'[0-9a-f]{64}', version):
        raise ValueError('Invalid immutable bundle version')
    path = store / 'versions' / version / 'bundle.json'
    bundle = read(path)
    body = {k: v for k, v in bundle.items() if k != 'version'}
    actual = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                       separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if actual != version or bundle.get('version') != version:
        raise ValueError('Agent1 bundle integrity mismatch')
    if bundle.get('job_id') != job.name or bundle.get('source_sha256') != source_hash:
        raise ValueError('Agent1 bundle source/job mismatch')
    if bundle.get('source_index', {}).get('source_sha256') != source_hash:
        raise ValueError('Agent1 evidence index source mismatch')
    return bundle, path


def text(value):
    if value is None:
        return ''
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def project(bundle, paper, raw, package):
    candidate = bundle['candidate']
    materials, graphs = candidate['materials'], candidate.get('graphs', {})
    index = bundle['source_index']
    blocks = {b['id']: b for b in index.get('blocks', [])}
    objects, links = [], []
    categories = {'polymer': '聚合物', 'monomer': '单体', 'component': '组分',
                  'blend': '共混物', 'network': '网络'}
    for material in materials.values():
        if material.get('major') is not True:
            continue
        view = package(material, graphs)
        pages = set()
        for ref in material.get('source_refs', []):
            page = int(ref[5:]) if re.fullmatch(r'page:\d+', ref) else blocks.get(ref, {}).get('page')
            if page is not None:
                if not isinstance(page, int) or not 1 <= page <= index['page_count']:
                    raise ValueError('Native source page outside the PDF')
                pages.add(page)
            links.append({'agent_id': material['id'], 'native_source_ref': ref,
                          'pdf_page_1based': page,
                          'downstream_context_block_ids': [b['block_id'] for b in raw['elements']
                                                          if page is not None and b.get('page') == page - 1],
                          'binding_basis': 'same_pdf_page_context_only_not_identity_verification'})
        components = []
        for component in material.get('components', []):
            if not isinstance(component, dict):
                continue
            cid = component.get('material_id') or component.get('source_molecule_material_id')
            label = component.get('label') or materials.get(cid, {}).get('label') or cid or ''
            roles = '，'.join(text(component.get(k)) for k in ('role', 'relation', 'amount') if component.get(k))
            components.append(str(label) + ('（' + roles + '）' if roles else ''))
        composition = material.get('composition') or {}
        components.extend(str(k) + ': ' + text(v) for k, v in composition.items())
        names = [text(n) if isinstance(n, str) else text(n.get('text') or n.get('name'))
                 for n in view.get('source_names', [])]
        objects.append({'ID': material['id'], '标签': material.get('label'),
                        '类别': categories.get(material.get('kind'), material.get('kind')),
                        '角色': material.get('role'), '来源名': '\n'.join(n for n in names if n),
                        '组分与投料比': '\n'.join(components),
                        '制备方式': text(material.get('preparation')),
                        '未知事项': text(view.get('unknowns')),
                        '来源页': '，'.join('page:' + str(p) for p in sorted(pages)),
                        'native_source_refs': deepcopy(material.get('source_refs', [])),
                        'native_bundle_version': bundle['version']})
    return {'paper': paper, 'major_objects': objects}, links


def main():
    parser = argparse.ArgumentParser()
    for key in ('job', 'store', 'pdf', 'document', 'agent1-app', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.agent1_app.resolve()))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from identity_app.name_package import package
    from stages.stage0_load_document import load_source_document, load_document_elements, recover_missing_equations
    bundle, bundle_path = verified_bundle(args.job, args.store, args.pdf)
    source = read(args.document)
    raw = source if 'source_document_schema_version' in source else load_document_elements(
        recover_missing_equations(load_source_document(args.document))).model_dump(mode='json', exclude_none=True)
    paper = raw['document_id'].removeprefix('reference_no_')
    if args.pdf.stem != raw['document_id']:
        raise ValueError('Document/PDF reference number mismatch')
    projected, links = project(bundle, paper, raw, package)
    work = args.output.resolve() / '_conversion_context'
    write(work / 'workflow_config.json', {'papers': [paper]})
    os.environ['POLYMER_AGENT1_RUN_ROOT'] = str(work)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from unified_directory import convert
    entities, samples, handoff = convert(projected, raw)
    dest = args.output / raw['document_id']
    for name, data in [('agent1_entities.json', entities), ('agent1_directory_samples.json', samples),
                       ('agent1_handoff.json', handoff), ('stage0_blocks.json', raw)]:
        write(dest / name, data)
    write(dest / 'native_bundle_projection.json', projected)
    write(dest / 'native_evidence_links.json', links)
    write(dest / 'native_delivery_receipt.json', {'job_id': args.job.name, 'version': bundle['version'],
          'source_sha256': bundle['source_sha256'], 'bundle_path': str(bundle_path.resolve()),
          'bundle_file_sha256': file_hash(bundle_path), 'document_sha256': file_hash(args.document),
          'model_calls': 0, 'projection_only': True, 'historical_result_fallback': False,
          'imported_samples': len(samples['samples']), 'source_links': len(links)})
    print(json.dumps({'document': raw['document_id'], 'samples': len(samples['samples']), 'handoff': str(dest)}))


if __name__ == '__main__':
    main()
