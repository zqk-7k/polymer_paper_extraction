"""Source attribution guards for explicitly saved identity properties."""


def property_errors(material, refs, candidate=None):
    errors = []
    for p in material.get('identity_properties') or []:
        if not isinstance(p, dict) or not p.get('property') or not p.get('source_refs') or not set(p['source_refs']).issubset(refs):
            errors.append('PROPERTY_SOURCE_OBJECT_REQUIRED')
            continue
        evidence = p.get('source_evidence')
        detailed = (candidate or {}).get('adoption_policy') == 'identity-adoption/1.5'
        if evidence is None and detailed:
            errors.append('PROPERTY_RAW_SOURCE_EVIDENCE_REQUIRED')
            continue
        if evidence is None:
            continue
        if not isinstance(evidence, dict) or evidence.get('representation') not in (
                'page_image', 'mineru_text', 'pdf_text', 'author_statement') or 'as_reported' not in evidence:
            errors.append('PROPERTY_LITERAL_REPRESENTATION_REQUIRED')
            continue
        if detailed and (not isinstance(evidence.get('as_reported'),str) or not evidence['as_reported'].strip()
                         or evidence.get('material_id')!=material['id']):
            errors.append('PROPERTY_LITERAL_MATERIAL_BINDING_REQUIRED')
        if evidence.get('table') and (not evidence.get('column_header') or not evidence.get('row_label')):
            errors.append('PROPERTY_TABLE_HEADER_ROW_REQUIRED')
        if evidence.get('material_id', material['id']) != material['id']:
            errors.append('PROPERTY_TABLE_MATERIAL_MISMATCH')
        # A declared discrepancy cannot disappear into one selected value. Its
        # source alternatives/resolution must remain in the shared conflict form.
        if evidence.get('discrepancy_detected'):
            from .source_conflicts import conflicts_for
            conflicts = conflicts_for(material, candidate or {})
            if evidence.get('conflict_id') not in {x.get('id') for x in conflicts}:
                errors.append('PROPERTY_RAW_CONFLICT_REQUIRED')
    return errors
