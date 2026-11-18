"""Carry explicitly evidenced monomer identities into received records."""
import re


def explicit_monomers(identity, blocks, verify_source):
    roles = {}
    for sample in identity.get('samples', []):
        if sample.get('sample_kind') not in ('monomer', 'intermediate'):
            continue
        label = sample.get('sample_label_raw')
        evidence = sample.get('evidence') or {}
        quote = evidence.get('source_sentence')
        block_id = evidence.get('block_id')
        if not label or not verify_source(blocks, block_id, quote):
            continue
        # Preserve label case: monomer ia and polymer Ia may coexist.
        pattern = r'(?i:\bmonomers?\s+)' + re.escape(label) + r'(?![\w-])'
        if not re.search(pattern, quote):
            continue
        roles[sample['sample_id']] = {
            'role': 'monomer', 'label_raw': label,
            'block_id': block_id, 'quote': quote,
            'basis': 'directory_identity_and_explicit_source_role',
        }
    return roles


def annotate(row, roles):
    evidence = roles.get(row.get('sample_id'))
    if evidence is None:
        return row
    row['monomer_excluded'] = True
    row['monomer_label_raw'] = evidence['label_raw']
    row['subject_role_evidence'] = dict(evidence)
    if row.get('status') == 'adopted':
        row['status'] = 'extracted_uncategorized'
        row['core_status'] = 'extracted_uncategorized'
        row['subject_role_reclassification'] = {
            'prior_status': 'adopted', 'reason': 'source_identified_monomer',
        }
    return row
