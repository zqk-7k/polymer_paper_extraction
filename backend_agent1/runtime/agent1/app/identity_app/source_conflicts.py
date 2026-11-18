"""Preserve declared source alternatives; never repair OCR facts by plausibility alone."""
from .diagnostics import ordered, reference_set


def conflicts_for(material, candidate):
    mid = material['id']
    raw = list(material.get('evidence_conflicts', [])) + [
        c for c in candidate.get('source_conflicts', [])
        if mid in [c.get('material_id'), *c.get('material_ids', [])]]
    if candidate.get('adoption_policy') not in ('identity-adoption/1.3', 'identity-adoption/1.5'):
        return raw
    # Equality is strict; divergent same-ID payloads stay visible to the gate.
    views = []
    for c in raw:
        if not c.get('id') or not any(c == previous for previous in views):
            views.append(c)
    return views


def conflict_errors(material, candidate, refs, diagnostics=None):
    errors, seen = [], set()
    for ci, c in enumerate(conflicts_for(material, candidate)):
        cid = c.get('id')
        alternatives = c.get('alternatives', [])
        base = {'material_id': material['id'], 'conflict_id': cid,
                'conflict_view_index': ci, 'path': f'conflict_views[{ci}]',
                'path_scope': 'projected preserved conflict views'}

        def add(code, **detail):
            errors.append(code)
            if diagnostics is not None:
                diagnostics.append({'code': code, **base, **detail})

        if not cid or not c.get('property') or type(c.get('impacts_naming')) is not bool:
            add('SOURCE_CONFLICT_ID_PROPERTY_SCOPE_REQUIRED', missing_or_invalid_fields=[
                key for key in ('id', 'property', 'impacts_naming')
                if (type(c.get(key)) is not bool if key == 'impacts_naming' else not c.get(key))])
        if cid in seen:
            add('SOURCE_CONFLICT_ID_PAYLOAD_COLLISION' if candidate.get('adoption_policy') in ('identity-adoption/1.3', 'identity-adoption/1.5')
                else 'SOURCE_CONFLICT_ID_PROPERTY_SCOPE_REQUIRED', reason='repeated conflict ID')
        seen.add(cid)
        if len(alternatives) < 2 or len({x.get('id') for x in alternatives}) != len(alternatives):
            add('SOURCE_CONFLICT_ALTERNATIVES_REQUIRED', path=base['path']+'.alternatives',
                alternative_count=len(alternatives), alternative_ids=[x.get('id') for x in alternatives])
        for ai, x in enumerate(alternatives):
            if not x.get('id') or 'as_reported' not in x or not x.get('representation') or not x.get('source_refs') or not set(x['source_refs']).issubset(refs):
                add('SOURCE_CONFLICT_RAW_EVIDENCE_REQUIRED', path=f"{base['path']}.alternatives[{ai}]",
                    alternative_index=ai, alternative_id=x.get('id'),
                    missing_fields=[key for key in ('id', 'as_reported', 'representation', 'source_refs')
                                    if (key not in x if key == 'as_reported' else not x.get(key))],
                    source_refs_type=type(x.get('source_refs')).__name__,
                    unowned_source_refs=ordered(reference_set(x.get('source_refs')) - reference_set(refs)))
        r = c.get('resolution', {})
        if r.get('status') not in ('unresolved', 'hypothesis', 'source_confirmed') or not r.get('reason'):
            add('SOURCE_CONFLICT_RESOLUTION_REQUIRED', path=base['path']+'.resolution',
                status=r.get('status'), allowed_statuses=['unresolved', 'hypothesis', 'source_confirmed'],
                missing_fields=['reason'] if not r.get('reason') else [])
        if r.get('status') in ('hypothesis', 'source_confirmed') and r.get('selected_alternative_id') not in {x.get('id') for x in alternatives}:
            add('SOURCE_CONFLICT_SELECTION_REQUIRED', path=base['path']+'.resolution.selected_alternative_id',
                selected_alternative_id=r.get('selected_alternative_id'), alternative_ids=[x.get('id') for x in alternatives])
        if r.get('status') == 'source_confirmed' and (not r.get('confirmation_source_refs') or not set(r['confirmation_source_refs']).issubset(refs)):
            add('SOURCE_CONFLICT_CONFIRMATION_EVIDENCE_REQUIRED', path=base['path']+'.resolution.confirmation_source_refs',
                missing_fields=['confirmation_source_refs'] if not r.get('confirmation_source_refs') else [],
                unowned_source_refs=ordered(reference_set(r.get('confirmation_source_refs')) - reference_set(refs)),
                claim_scope='primary-model declaration; not independent source interpretation')
    return list(dict.fromkeys(errors))


def naming_conflict_errors(material, candidate, proposal, diagnostics=None):
    refs = set(material.get('source_refs', []))
    errors = conflict_errors(material, candidate, refs, diagnostics)
    review = proposal.get('conflict_review', {})
    conflicts = conflicts_for(material, candidate)

    def add(code, **detail):
        errors.append(code)
        if diagnostics is not None:
            diagnostics.append({'code': code, 'material_id': material['id'], **detail})

    if review.get('status') not in ('none_detected', 'preserved') or not review.get('reason') or not set(proposal.get('source_refs', [])).issubset(set(review.get('examined_source_refs', []))) or not set(review.get('examined_source_refs', [])).issubset(refs):
        add('EXPLICIT_SOURCE_CONFLICT_REVIEW_REQUIRED', path='proposal.conflict_review', status=review.get('status'),
            allowed_statuses=['none_detected', 'preserved'], missing_fields=['reason'] if not review.get('reason') else [],
            unexamined_proposal_source_refs=ordered(reference_set(proposal.get('source_refs'))-reference_set(review.get('examined_source_refs'))),
            unowned_examined_source_refs=ordered(reference_set(review.get('examined_source_refs'))-refs))
    if conflicts and (review.get('status') != 'preserved' or set(review.get('conflict_ids', [])) != {x.get('id') for x in conflicts}):
        declared = {x.get('id') for x in conflicts}; linked = reference_set(review.get('conflict_ids'))
        add('ALL_SOURCE_CONFLICTS_MUST_BE_PRESERVED', path='proposal.conflict_review',
            required_status='preserved', missing_conflict_ids=ordered(declared-linked), extra_conflict_ids=ordered(linked-declared))
    for ci, c in enumerate(conflicts):
        if not c.get('impacts_naming'): continue
        state = c.get('resolution', {}).get('status')
        basis = proposal.get('evidence_basis')
        detail = {'conflict_id': c.get('id'), 'conflict_view_index': ci, 'path': 'proposal.evidence_basis', 'evidence_basis': basis}
        if state == 'unresolved' and basis != 'broader_scope':
            add('UNRESOLVED_IDENTITY_CONFLICT_REQUIRES_BROADER_NAME', **detail, allowed_bases=['broader_scope'])
        if state == 'hypothesis' and basis not in ('feasible_hypothesis', 'most_likely_hypothesis'):
            add('CONFLICT_CORRECTION_MUST_REMAIN_HYPOTHETICAL', **detail, allowed_bases=['feasible_hypothesis', 'most_likely_hypothesis'])
    return list(dict.fromkeys(errors))
