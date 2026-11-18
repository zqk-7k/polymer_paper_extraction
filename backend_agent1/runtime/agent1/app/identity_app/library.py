"""Compact, version-bound component occurrences for the reader (no chemistry)."""
import unicodedata
from collections import Counter
from .evidence import library_summary
from .storage import digest

CONTRACT = 'component-library/4.0'
ASSOCIATION_LABELS = {'composition':'明确组成关系', 'precursor':'前体与来源组分',
                      'process':'制备与工艺辅助', 'naming':'命名来源', 'other':'其他文献关联'}


def association_category(use, field, component):
    """Classify the saved relation, never promote a generic link to composition."""
    if use.get('relation') in ('comparison','series_members','sample_state_of','processed_from'):
        return 'other'
    text = search_text(' '.join(str(x or '') for x in
                       (use.get('relation'), use.get('role'), component.get('role')))).replace('_', ' ')
    if any(x in text for x in ('naming', 'nomenclatur', 'nomenclatural', '命名')):
        return 'naming'
    if any(x in text for x in ('not product constituent', 'not polymer constituent',
                               'not incorporated', 'solvent', 'catalyst', 'initiator',
                               'workup', 'recrystallization', 'precipitation', 'processing',
                               'purification', 'preparation agent', '溶剂', '催化', '引发', '洗涤')):
        return 'process'
    if field == 'material_id' and use.get('relation') in (
            'physical_blend_component', 'formulation_component', 'covalent_constitutional_unit',
            'polymer_matrix', 'noncovalent_material_blend', 'graft_backbone_of', 'graft_sidechain_of'):
        return 'composition'
    if field == 'source_molecule_material_id' or any(x in text for x in (
            'precursor', 'reactant', 'monomer', 'polymerization source', 'polycondensation source',
            'diol source', 'diamine source', 'dianhydride source', '投料', '前体', '来源单体')):
        return 'precursor'
    return 'other'


def role_group(entry):
    """Reading categories only; the reported kind/role remains unchanged."""
    role = search_text(entry.get('role')).replace('_', ' ')
    if entry.get('kind') == 'monomer' or any(x in role for x in ('monomer', '单体', 'naming source', 'nomenclature source')):
        return 'monomer'
    if entry.get('kind') in ('polymer', 'prepolymer', 'oligomer', 'blend', 'network'):
        return 'polymer'
    if any(x in role for x in ('solvent', '溶剂', 'antisolvent', 'eluent', '溶解', '洗涤')):
        return 'solvent'
    if any(x in role for x in ('catalyst', 'initiator', '催化', '引发')):
        return 'catalyst'
    if any(x in role for x in ('precursor', 'intermediate', '前体', '中间体')):
        return 'precursor'
    if any(x in role for x in ('additive', 'stabilizer', 'filler', 'dopant', '添加', '填料', 'crosslink', 'curing')):
        return 'additive'
    if any(x in role for x in ('reagent', 'reactant', 'acid', 'base', '试剂', '投料', '反应物', '碱')):
        return 'reagent'
    return 'other'


def search_text(value):
    return unicodedata.normalize('NFKC', str(value or '')).casefold()


def identity_projection(material, candidate, bundle):
    """Group only exact saved finite encodings; never infer real-material equality.

    The saved isomeric canonical SMILES includes isotope, charge, salts and maps.
    No map removal, tautomer/salt normalization or polymer-unit matching occurs.
    Assumptions, unknowns and role claims remain in each source's immutable record.
    """
    gids = material.get('graph_ids') or []
    graph = candidate.get('graphs', {}).get(gids[0], {}) if len(gids) == 1 else {}
    smiles = graph.get('canonical_smiles')
    finite = (material.get('kind') in ('monomer', 'component') and
              graph.get('scope') == 'finite_molecule' and isinstance(smiles, str) and
              bool(smiles.strip()) and '*' not in smiles and not graph.get('ports'))
    body = ({'contract': 'reader-finite-structure/1.0', 'canonical_smiles': smiles}
            if finite else {'contract': 'reader-source-record/1.0', 'job_id': bundle['job_id'],
                            'version': bundle['version'], 'id': material['id']})
    return {'identity_key': digest(body), 'identity_basis': 'finite_graph' if finite else 'source_record'}


def component_entries(bundle):
    c = bundle['candidate']; materials = c['materials']; uses = {}; associations = {}
    for owner in materials.values():
        for use in owner.get('components') or []:
            if not isinstance(use, dict): continue
            for field in ('material_id', 'source_molecule_material_id'):
                mid = use.get(field)
                if mid in materials:
                    uses.setdefault(mid, []).append({'id': owner['id'], 'label': owner['label'],
                                                    'role': use.get('role') or use.get('relation')})
                    associations.setdefault(mid, []).append({
                        'id':owner['id'], 'label':owner['label'], 'kind':owner['kind'],
                        'role':use.get('role'), 'relation':use.get('relation'), 'field':field,
                        'category':association_category(use, field, materials[mid]),
                        'source_refs':use.get('source_refs') or [], 'reason':use.get('reason'),
                        'evidence_basis':use.get('evidence_basis')})
    # Explicit source relations are also readable; endpoint direction is retained.
    # They do not enlarge the component inventory or imply actual consumption.
    for relation in c.get('relations') or []:
        if not isinstance(relation, dict): continue
        left=relation.get('from_material_id');right=relation.get('to_material_id')
        if left not in materials or right not in materials or left==right: continue
        for mid, other, direction in ((left,right,'outgoing'),(right,left,'incoming')):
            owner=materials[other];use={**relation,'relation':relation.get('type')}
            associations.setdefault(mid, []).append({'id':other,'label':owner['label'],'kind':owner['kind'],
                'role':None,'relation':relation.get('type'),'field':'explicit_relation', 'direction':direction,
                'category':association_category(use,'explicit_relation',materials[mid]),
                'source_refs':relation.get('source_refs') or [],'reason':relation.get('reason'),
                'evidence_basis':relation.get('evidence_basis')})
    entries = []
    for m in materials.values():
        if not (m.get('kind') in ('monomer', 'component') or m['id'] in uses or
                m.get('role') in ('blend_component', 'starting_polymer_and_control')): continue
        aliases = [m['label']]
        for p in m.get('identity_preparations') or []:
            aliases.extend([p.get('raw_name'), p.get('full_name'), *(p.get('aliases') or [])])
        aliases.extend(m.get('aliases') or [])
        aliases = list(dict.fromkeys(x for x in aliases if isinstance(x, str) and x))
        used_by = list({(x['id'], x['role']): x for x in uses.get(m['id'], [])}.values())
        entries.append({'job_id': bundle['job_id'], 'version': bundle['version'], 'id': m['id'],
                        'label': m['label'], 'kind': m['kind'], 'major': m.get('major'),
                        'role': m.get('role'), 'aliases': aliases, 'used_by': used_by,
                        'associations':list({digest(a):a for a in associations.get(m['id'], [])}.values()),
                        'source_title': c.get('title', ''), **library_summary(m, c),
                        **identity_projection(m, c, bundle)})
        entries[-1]['role_group'] = role_group(entries[-1])
    return entries


def identity_groups(entries):
    groups = {}
    for entry in entries:
        # Compatibility for callers providing an old, unprojected occurrence.
        key = entry.get('identity_key') or digest({k: entry[k] for k in ('job_id', 'version', 'id')})
        groups.setdefault(key, []).append(entry)
    return groups


def source_counts(records):
    return {'paper_count': len({e['job_id'] for e in records}), 'occurrence_count': len(records)}


def identity_summary(records):
    targets = {(e['job_id'],a['id']) for e in records for a in e.get('associations', [])}
    return {**records[0], **source_counts(records),
            'source_labels':list(dict.fromkeys(e['label'] for e in records)),
            'role_groups':list(dict.fromkeys(e.get('role_group') or role_group(e) for e in records)),
            'association_count':len(targets),
            'association_categories':{k:len({(e['job_id'],a['id']) for e in records
                for a in e.get('associations', []) if a['category']==k}) for k in ASSOCIATION_LABELS}}


def records_for_key(entries, key):
    if len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('COMPONENT_KEY_INVALID')
    records = identity_groups(entries).get(key)
    if not records: raise ValueError('COMPONENT_NOT_FOUND')
    return records


def association_page(entries, key, query):
    records = records_for_key(entries, key); summary = identity_summary(records)
    category = query.get('category', ['all'])[0]; term = search_text(query.get('q', [''])[0]).strip()
    limit = min(40, max(1, int(query.get('limit', ['12'])[0])))
    offset = max(0, int(query.get('offset', ['0'])[0])); targets = {}
    for e in records:
        for a in e.get('associations', []):
            if category != 'all' and a['category'] != category: continue
            if term and not all(w in search_text(a['label']+' '+e['source_title']) for w in term.split()): continue
            target = targets.setdefault((e['job_id'],a['id']), {'job_id':e['job_id'], 'version':e['version'],
                'id':a['id'],'label':a['label'],'kind':a['kind'],'source_title':e['source_title'],'links':[]})
            target['links'].append({**a, 'source_id':e['id'], 'source_label':e['label']})
    rows = list(targets.values()); total = len(rows)
    offset = min(offset, ((total-1)//limit)*limit if total else 0)
    return {'identity_key':key, 'categories':summary['association_categories'],
            'association_count':summary['association_count'], 'total':total,
            'offset':offset,'limit':limit,'entries':rows[offset:offset+limit]}


def sources(entries, key, query):
    """Bounded source list from current adopted papers, independent of UI filters."""
    records = records_for_key(entries, key)
    limit = min(40, max(1, int(query.get('limit', ['12'])[0])))
    offset = max(0, int(query.get('offset', ['0'])[0]))
    by_paper = {}
    for e in records:
        paper = by_paper.setdefault(e['job_id'], {'job_id': e['job_id'], 'version': e['version'],
                                               'title': e['source_title'], 'entries': []})
        paper['entries'].append({k: e.get(k) for k in ('id', 'label', 'name', 'kind', 'role', 'associations')})
    papers = list(by_paper.values())
    term = search_text(query.get('q', [''])[0]).strip()
    if term: papers = [p for p in papers if all(w in search_text(p['title']+' '+
        ' '.join(e['label'] for e in p['entries'])) for w in term.split())]
    matched = len(papers)
    offset = min(offset, ((matched - 1) // limit) * limit if matched else 0)
    return {'identity_key': key, 'identity_basis': records[0].get('identity_basis', 'source_record'),
            'name': records[0].get('name') or records[0]['label'], **source_counts(records),
            'matched_paper_count':matched, 'offset': offset, 'limit': limit, 'papers': papers[offset:offset + limit]}


def page(entries, papers, query):
    limit = min(100, max(1, int(query.get('limit', ['40'])[0])))
    offset = max(0, int(query.get('offset', ['0'])[0]))
    term = search_text(query.get('q', [''])[0]).strip()
    kind = query.get('kind', ['all'])[0]; owner = query.get('owner', [''])[0]
    role = query.get('role', ['all'])[0]
    group = query.get('group', ['all'])[0]
    sort = query.get('sort', ['recent'])[0]
    view = query.get('view', ['records'])[0]
    shared = query.get('shared', ['0'])[0] == '1'
    identities = identity_groups(entries)
    statistics = {key: source_counts(records) for key, records in identities.items()}
    by_record = {(e['job_id'], e['version'], e['id']): key for key, records in identities.items() for e in records}
    kinds = Counter(e['kind'] for e in entries)
    roles = Counter(e.get('role') for e in entries if e.get('role'))
    groups = Counter(e.get('role_group') or role_group(e) for e in entries)
    def matches(e):
        values = [e['label'], e.get('name'), *e['aliases'], *e.get('formulas', [])]
        text = search_text(' '.join(str(x or '') for x in values))
        return (not term or all(word in text for word in term.split())) and (
            kind == 'all' or e['kind'] == kind) and (role == 'all' or e.get('role') == role) and (
            group == 'all' or (e.get('role_group') or role_group(e)) == group)
    filtered = [e for e in entries if matches(e) and
                (not shared or statistics[by_record[e['job_id'], e['version'], e['id']]]['paper_count'] > 1)]
    counts = Counter(e['job_id'] for e in filtered)
    rows = [e for e in filtered if not owner or e['job_id'] == owner]
    projected = []; seen = set()
    for e in rows:
        key = by_record[e['job_id'], e['version'], e['id']]
        if view == 'components' and key in seen: continue
        seen.add(key)
        aliases = list(dict.fromkeys(a for record in identities[key] for a in record['aliases']))
        projected.append({**identity_summary(identities[key]), **e, 'identity_key': key,
                          **statistics[key],
                          'aliases': aliases if view == 'components' else e['aliases']})
    rows = projected
    if sort == 'name':
        rows.sort(key=lambda e: search_text(e.get('name') or e['label']))
    elif sort == 'sources':
        rows.sort(key=lambda e: (-e['paper_count'], -e['occurrence_count']))
    if term:
        # Exact identity matches precede incidental mentions in a paper title.
        rows.sort(key=lambda e: (0 if term in [search_text(e['label']), *map(search_text, e['aliases'])] else
                                 1 if term in search_text(e.get('name')) else 2))
    total = len(rows)
    # A changed adoption or filter can shrink the last page.
    offset = min(offset, ((total - 1) // limit) * limit if total else 0)
    selected = rows[offset:offset + limit]
    compact = query.get('compact', ['0'])[0] == '1'
    if compact:
        selected = [{k:v for k,v in e.items() if k not in ('tool_statuses','associations','used_by','aliases')} for e in selected]
    return {'entries': selected, 'total': total, 'library_total': len(entries),
            'contract':CONTRACT,
            'library_identity_total': len(identities), 'view': view,
            'cross_paper_identity_total': sum(v['paper_count'] > 1 for v in statistics.values()),
            'offset': offset, 'limit': limit, 'matched_total': len(filtered),
            'papers': [{'job_id': p['job_id'], 'title': p['title'], 'version': p['version'],
                        'component_count': p['component_count'], 'matched_count': counts[p['job_id']]}
                       for p in papers], 'kinds': dict(kinds), 'roles': {} if compact else dict(roles),
            'groups': dict(groups)}
