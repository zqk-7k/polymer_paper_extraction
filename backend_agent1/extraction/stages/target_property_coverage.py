"""Document × configured property accounting; presence never implies completeness."""
from collections import defaultdict
import re

from stages.source_field_enrichment import clean_header
from stages.standard_mapping import normalize_mapping_text, units_in_text


SECTIONS = ('property_vocabulary', 'stage5_property_vocabulary', 'specialized_property_vocabulary')
PROPERTY_KINDS = {'property', 'qualitative_property'}
# These affect semantic identity, unlike missing units or presentation notation.
SEMANTIC_REASONS = {'symbol_interpretation_requires_review',
                    'molecular_weight_statistic_unresolved',
                    'distribution_not_confirmed_as_dispersity'}


def build_catalog(schema, registry, sections=SECTIONS):
    """Keep namespaces and property subtypes; never merge by shared PolyInfo codes."""
    if not sections or set(sections) - set(SECTIONS):
        raise ValueError('Unsupported target sections')
    targets = []
    for section in sections:
        for key, definition in schema[section].items():
            definition = definition if isinstance(definition, dict) else {}
            aliases = {key, key.replace('_', ' '), *definition.get('aliases', [])}
            codes = []
            flags = []
            for entry in registry['entries']:
                field = 'pipeline_specialized_key' if section == 'specialized_property_vocabulary' else 'pipeline_property_name'
                if entry.get(field) == key or entry['key'] == key:
                    aliases.update(entry.get('aliases', []))
                    codes.append('STD:' + entry['key'])
                    flags.extend(entry.get('review_flags', []))
            targets.append({'target_id': section + ':' + key, 'property_key': key,
                            'section': section, 'aliases': sorted(aliases),
                            'standard_property_codes': sorted(set(codes)),
                            'semantic_review_flags': sorted(set(flags))})
    return {'schema_version': 'target_property_catalog.v1', 'sections': list(sections), 'targets': targets}


def _header_name(text):
    text = clean_header(text)
    # Only remove a recognized unit suffix. Parenthesized qualifiers remain.
    match = re.search(r'\s*\(([^()]*)\)\s*$', text)
    if match and units_in_text(match[1]):
        if normalize_mapping_text(match[1]) in {normalize_mapping_text(u) for u in units_in_text(match[1])}:
            text = text[:match.start()]
    return normalize_mapping_text(text)


def target_matches(observation, catalog):
    if observation['record_kind'] not in PROPERTY_KINDS:
        return []
    # Compare complete names, never substring "strength" with "strength at break".
    names = {_header_name(h) for h in observation.get('property_header_path', [])}
    names.add(_header_name(observation.get('property_name_raw')))
    matches = []
    for target in catalog['targets']:
        aliases = {normalize_mapping_text(a) for a in target['aliases']}
        exact = sorted(names & aliases)
        code = observation.get('standard_property_code')
        reviewed = target['target_id'] in observation.get('reviewed_target_ids', [])
        model_assigned = target['target_id'] in observation.get('model_target_ids', [])
        if not reviewed and not model_assigned and not exact and code not in target['standard_property_codes']:
            continue
        reasons = set(observation.get('standard_mapping_reasons', []))
        uncertain = not exact and bool(reasons & (SEMANTIC_REASONS | set(target['semantic_review_flags'])))
        if model_assigned and not exact and code not in target['standard_property_codes']:
            uncertain = True
        matches.append({'target_id': target['target_id'],
                        'match_status': 'candidate' if uncertain else 'source_property_identified',
                        'basis': 'reviewed_source_definition' if reviewed else 'model_source_interpretation' if model_assigned else 'complete_source_header_alias' if exact else 'existing_property_mapping',
                        'matched_aliases': exact, 'standard_property_code': code})
    return matches


def _mention_patterns(catalog):
    # Hints locate work, not prove a measurement. Avoid tiny aliases (e.g. Mn)
    # triggering prose matches or turning a mention into "reported".
    return {t['target_id']: re.compile(r'(?<!\w)(?:' + '|'.join(
        re.escape(normalize_mapping_text(a)) for a in t['aliases']
        if len(normalize_mapping_text(a)) >= 5) + r')(?!\w)', re.I)
        for t in catalog['targets']}


def build_coverage(documents, catalog, published_rows):
    targets = catalog['targets']
    if not targets or len({t['target_id'] for t in targets}) != len(targets):
        raise ValueError('Empty or duplicate target catalog')
    if len({d['document_id'] for d in documents}) != len(documents):
        raise ValueError('Duplicate source document')
    sources = {(d['document_id'], r['observation_id']): r for d in documents for r in d['observations']}
    published = {}
    for row in published_rows:
        key = (row['document_id'], row['observation_id'])
        if key in published or key not in sources or row != sources[key] or row['extraction_status'] != 'usable':
            raise ValueError('Export is duplicate, stale, or inconsistent with source observations')
        published[key] = row
    patterns = _mention_patterns(catalog)
    ledger, assignments, unassigned = [], [], []
    for document in documents:
        doc = document['document_id']
        buckets = defaultdict(list)
        for obs in document['observations']:
            matches = target_matches(obs, catalog)
            if not matches and obs['record_kind'] in PROPERTY_KINDS:
                unassigned.append({'document_id': doc, 'observation_id': obs['observation_id'],
                                   'source_cell_id': obs['source_cell_id'], 'property_name_raw': obs['property_name_raw'],
                                   'status': 'target_scope_or_mapping_unresolved'})
            for match in matches:
                assignment = {'document_id': doc, 'observation_id': obs['observation_id'],
                              'source_cell_id': obs['source_cell_id'], **match,
                              'extraction_status': obs['extraction_status'],
                              'in_usable_export': (doc, obs['observation_id']) in published}
                buckets[match['target_id']].append(assignment)
                assignments.append(assignment)
        text_blocks = [(b['block_id'], normalize_mapping_text(b.get('text'))) for b in document.get('source_blocks', [])]
        for target in targets:
            tid = target['target_id']
            entries = buckets[tid]
            accepted = [e for e in entries if e['match_status'] == 'source_property_identified' and e['extraction_status'] == 'usable']
            exported = [e['observation_id'] for e in accepted if e['in_usable_export']]
            missing = [e['observation_id'] for e in accepted if not e['in_usable_export']]
            review = [e['observation_id'] for e in entries if e not in accepted]
            mentions = [bid for bid, text in text_blocks if patterns[tid].search(text)]
            status = ('published_present_completeness_unchecked' if exported else
                      'identified_but_not_exported' if missing else
                      'candidate_needs_review' if review else
                      'source_mention_needs_extraction' if mentions else 'not_yet_located')
            ledger.append({'document_id': doc, 'target_id': tid, 'property_key': target['property_key'],
                           'status': status, 'published_observation_ids': exported,
                           'unpublished_observation_ids': missing, 'review_observation_ids': review,
                           'mention_block_ids': mentions, 'source_sha256': document['source_sha256'],
                           'all_values_accounted_for': False, 'verified_not_reported': False,
                           'remaining_work': ['check_all_source_tables_text_and_figures_for_omissions'] +
                               (['export_identified_records'] if missing else []) +
                               (['resolve_target_or_axis_candidates'] if review else [])})
    return {'ledger': ledger, 'assignments': assignments, 'unassigned_properties': unassigned}
