"""One naming service: generated and verified-input candidates are distinct."""
from .chemical_support import build_support
from .name_validation import check_name

class NamingService:
    def __init__(self, kernel):
        self.kernel = kernel

    def name_declared_cru(self,parts):
        """Explicit-subunit candidate, not preferred IUPAC certification."""
        from .declared_cru_candidate import propose
        return propose(parts)

    def check_model_structure(self, proposal, target):
        """Generic proposal checks, with tool coverage distinct from model rule review."""
        from .model_naming import check_structure_proposal
        return check_structure_proposal(self.kernel, proposal, target)

    def name_structure(self,smiles,*,rule_contract=None,knowledge_snapshot=None):
        if rule_contract=='iupac-regular-unit-graph-candidate/1.0':
            from .regular_unit_candidates import structure_name
            return structure_name(self.kernel,smiles)
        if rule_contract=='iupac-triazine-graph-candidate/1.0':
            from .triazine_graph_naming import structure_name
            return structure_name(self.kernel,smiles)
        if rule_contract=='iupac-supported-naming/1.0':
            from .supported_naming_v1 import structure_name
            return structure_name(self.kernel,smiles)
        if rule_contract=='iupac-supported-naming/1.2':
            from .growth_naming import structure_name
            return structure_name(self.kernel,smiles,knowledge_snapshot)
        from .supported_naming import structure_name
        return structure_name(self.kernel,smiles)

    def name(self, passport, scope='reported_source_architecture_without_end_groups', *, validation_contract=None, rule_contract=None, knowledge_snapshot=None):
        if rule_contract=='iupac-supported-naming/1.2':
            from .growth_naming import name
            return name(self.kernel,passport,knowledge_snapshot)
        if rule_contract is not None:
            if rule_contract == 'iupac-supported-naming/1.0':
                from .supported_naming_v1 import name
                return name(self.kernel, passport)
            from .supported_naming import CONTRACT, name
            if rule_contract != CONTRACT:
                raise ValueError('UNKNOWN_NAMING_RULE_CONTRACT')
            return name(self.kernel, passport)
        if not passport:
            return {'primary': None, 'alternatives': [], 'unverified': [], 'reason_code': 'PASSPORT_NOT_CREATED',
                    'preferred_iupac_name': None, 'full_iupac_conformance': False}
        support = build_support(self.kernel, passport)
        candidates, rejected, seen = [], [], set()
        def add(text, kind, origin, trace=None):
            if not text or text in seen:
                return
            seen.add(text)
            check = check_name(self.kernel, passport, text, kind, contract=validation_contract)
            from .source_naming_validation import CONTRACT, SCOPE
            candidate = {'text': text, 'kind': kind, 'origin': origin, 'scope':
                         ('supported_unoriented_achiral_constitution_without_end_groups' if kind == 'structure_based'
                          else SCOPE if validation_contract == CONTRACT else scope),
                         'status': 'CANDIDATE', 'rule_refs': support['rule_ids'], 'evidence_refs': [support['passport_ref']],
                         'assumptions': [], 'omitted_fields': ['sample_identity', 'unreported_end_groups'],
                         'checks': check['checks'], 'validation': check, 'local_trace': trace or {},
                         'independent_review': 'PENDING', 'is_newly_generated': origin != 'INPUT_NAME_VERIFIED_NOT_NEW_NAME'}
            if kind == 'source_based' and validation_contract == CONTRACT:
                candidate['omitted_fields'] = check.get('excluded_from_name_comparison', [])
            (candidates if check['accepted'] else rejected).append(candidate)
        direction = support.get('backbone_direction_evidence') or {}
        if support['structure_naming_ready'] and direction.get('status') == 'DECIDED':
            add(direction.get('candidate_name'), 'structure_based', 'LOCAL_RULE13_NAMING', direction)
        modes = ('structure', 'source') if support['structure_naming_ready'] else ('source', 'structure')
        for mode in modes:
            try:
                output = self.kernel.dispatch('name_from_passport', {'passport': passport, 'mode': mode})
                name = output.get('name_candidate')
                kind = 'structure_based' if mode == 'structure' or not support['source_naming_ready'] else 'source_based'
                add(name, kind, 'LOCAL_FROZEN_NAMING', output)
            except (ValueError, KeyError, TypeError, RuntimeError):
                continue
        if support['structure_naming_ready'] and not candidates:
            smiles = (support['constitution'] or {}).get('canonical_repeat_smiles')
            if smiles:
                result = self.kernel.dispatch('name_from_unit', {'smiles': smiles})
                add(result.get('structure_based_name_candidate'), 'structure_based', 'LOCAL_GRAPH_NAMING', result)
        if not candidates and support['status'] == 'PARSED':
            text = (passport.get('evidence') or {}).get('original_name')
            kind = 'structure_based' if support['structure_naming_ready'] else 'source_based'
            # Re-parse and compare the name; never display unchecked input as generated nomenclature.
            add(text, kind, 'INPUT_NAME_VERIFIED_NOT_NEW_NAME')
        return {**({'validation_contract': validation_contract} if validation_contract else {}),
                'primary': candidates[0] if candidates else None, 'alternatives': candidates[1:3],
                'unverified': rejected[:3], 'chemical_support': support,
                'reason_code': None if candidates else 'NAMING_OUT_OF_CHECKED_SCOPE',
                'preferred_iupac_name': None, 'full_iupac_conformance': False}
