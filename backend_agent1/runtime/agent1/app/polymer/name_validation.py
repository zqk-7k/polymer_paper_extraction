"""Candidate checks against a frozen passport, not an IUPAC certification."""
from .syntax import bracket_check

def check_name(kernel, passport, text, kind, *, contract=None):
    from .source_naming_validation import CONTRACT, compare
    if contract not in (None, CONTRACT):
        raise ValueError('UNKNOWN_NAME_VALIDATION_CONTRACT')
    checks = {'brackets': 'NOT_RUN', 'name_parse': 'NOT_RUN', 'identity_roundtrip': 'NOT_RUN',
              'periodic_stereo': 'NOT_RUN', 'preferred_cru_selection': 'NOT_RUN',
              'full_iupac_conformance': 'NOT_RUN', 'independent_review': 'NOT_RUN'}
    if not isinstance(text, str) or not text.strip() or len(text) > 5000:
        return {'accepted': False, 'reason_code': 'NAME_LIMIT', 'checks': checks}
    checks['brackets'] = 'PASS' if bracket_check(text)['valid'] else 'FAIL'
    if checks['brackets'] != 'PASS':
        return {'accepted': False, 'reason_code': 'BRACKETS_INVALID', 'checks': checks}
    parsed = kernel.parse({'name': text, 'interpretation_policy': 'evidence_only'})
    checks['name_parse'] = 'PASS' if parsed.get('status') == 'PARSED' else 'FAIL'
    core, evidence = passport.get('chemical_core') or {}, passport.get('evidence') or {}
    projected = parsed.get('semantic_projection') or {}
    if kind == 'structure_based':
        expected = (passport.get('identity_keys') or {}).get('constitution_key')
        observed = projected.get('constitution_key')
        same = bool(expected and observed and expected == observed)
        checks['comparison_scope'] = (core.get('constitution_model') or {}).get('scope')
        # Existing unoriented/achiral graph keys must not validate asserted stereo or chain ends.
        attrs = core.get('attributes') or {}
        unsupported = any((attrs.get(a) or {}).get('knowledge_status') == 'specified' for a in ('end_groups', 'tacticity'))
        same = same and not unsupported and not any(c in text for c in ('alpha-', 'omega-', 'α-', 'ω-'))
        import re
        if re.search(r'(?i)\b(?:cis|trans|isotactic|syndiotactic|atactic|racemic)\b|\([RSZE]\)', text):
            same = False
        for c in parsed.get('components') or []:
            smiles = (c.get('unit') or {}).get('unit_smiles') or ''
            if '@' in smiles or '/' in smiles or '\\' in smiles:
                same = False
    elif kind == 'source_based':
        if contract == CONTRACT:
            result = compare(kernel, passport, text)
            checks['comparison_scope'] = result.get('comparison_scope')
            checks['identity_roundtrip'] = 'PASS' if result['accepted'] else 'FAIL'
            return {**result, 'checks': checks, 'candidate_status':
                    'AUTOMATIC_IDENTITY_CHECKED_NOT_INDEPENDENTLY_REVIEWED' if result['accepted'] else 'UNVERIFIED'}
        expected = evidence.get('legacy_descriptor_key')
        observed = projected.get('descriptor_key')
        same = bool(expected and observed and expected == observed)
        checks['comparison_scope'] = 'typed_source_and_architecture_descriptor'
    else:
        return {'accepted': False, 'reason_code': 'DESCRIPTIVE_NOT_IUPAC_CHECKED', 'checks': checks}
    checks['identity_roundtrip'] = 'PASS' if same else 'FAIL'
    accepted = same and parsed.get('status') == 'PARSED'
    return {'accepted': accepted, 'reason_code': None if accepted else 'IDENTITY_OR_SCOPE_MISMATCH',
            'checks': checks, 'expected_key': expected, 'observed_key': observed,
            'candidate_status': 'AUTOMATIC_IDENTITY_CHECKED_NOT_INDEPENDENTLY_REVIEWED' if accepted else 'UNVERIFIED'}
