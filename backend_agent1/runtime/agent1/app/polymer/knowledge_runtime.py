"""Per-run read-through candidates; never promote the shared Registry."""
from pathlib import Path
import re
from rdkit import Chem
from .chemistry import canonicalize
from .periodic import canonicalize_unit
from .common import ROOT, fail
from .providers import OpsinProvider

class KnowledgeRegistry:
    def __init__(self, base, knowledge, allow_opsin=True, max_calls=8):
        self.base = base
        self.version, self.index = knowledge.candidate_index()
        self.events, self.cache, self.unit_cache = [], {}, {}
        self.calls, self.max_calls = 0, max_calls
        self.allow_opsin = allow_opsin
        jar = ROOT / 'third_party/opsin-core.jar'
        self.provider = OpsinProvider(jar=jar if jar.is_file() else None)

    def __getattr__(self, name):
        base = self.__dict__.get('base')
        if base is None:
            raise AttributeError(name)
        return getattr(base, name)

    @staticmethod
    def structural(name):
        return bool(re.search(r'(?:diyl|triyl|tetrayl|ylene)$|^(?:oxy|imino|carbonyl|sulfanediyl)', name))

    def _rows(self, role, name):
        from .knowledge_service import KnowledgeService
        return self.index.get((role, KnowledgeService.alias_key(name)), [])

    def _tool(self, name):
        if not self.allow_opsin or self.calls >= self.max_calls:
            return fail('LOCAL_TOOL_DISABLED_OR_BUDGET_EXHAUSTED', 'NEEDS_DETAILS')
        health = self.provider.probe()
        if not health['available'] or health['jar_sha256'] != health['expected_jar_sha256']:
            return fail('OPSIN_UNAVAILABLE_OR_HASH_MISMATCH', 'NEEDS_DETAILS')
        self.calls += 1
        result = self.provider.resolve(name)
        self.events.append({'tool': 'opsin', 'input': name, 'status': result.get('status'),
                            'parser_status': result.get('parser_status'), 'initiated_by': 'deterministic',
                            'network_requests': 0, 'source': result.get('source'), 'response': result})
        return result

    def resolve(self, name):
        if not isinstance(name, str):
            return fail('NAME_MUST_BE_TEXT', 'INVALID')
        if name in self.cache:
            return self.cache[name]
        original = self.base.resolve(name)
        if original.get('status') in ('PARSED', 'AMBIGUOUS') or original.get('reason_code') == 'ALIAS_REVOKED':
            return original
        candidates = []
        for row in self._rows('source_molecules', name):
            graph = canonicalize(row.get('canonical_smiles') or row.get('smiles'))
            if graph.get('status') == 'PARSED':
                candidates.append({**graph, 'name': name, 'reference_label': name, 'binding_status': 'DRAFT',
                                   'source': {'type': 'published_research_candidate', 'component_key': row['component_key'], 'data_version': self.version}})
        distinct = {r['molecule_key']: r for r in candidates}
        if len(distinct) > 1:
            result = fail('ALIAS_HAS_MULTIPLE_STRUCTURES', 'AMBIGUOUS', candidates=candidates)
        elif distinct:
            result = next(iter(distinct.values()))
        elif not self.structural(name):
            result = self._tool(name)
            if result.get('status') == 'PARSED':
                result = {**result, 'reference_label': name, 'name': name}
        else:
            result = original
        self.events.append({'tool': 'component_resolver', 'input': name, 'role': 'source_molecules',
                            'status': result.get('status'), 'data_version': self.version,
                            'candidate_count': len(distinct), 'initiated_by': 'deterministic'})
        self.cache[name] = result
        return result

    def resolve_unit(self, name, original):
        if len(name) > 1200:
            return original
        if name in self.unit_cache:
            return self.unit_cache[name]
        rows = self._rows('fragments_cu', name)
        raw = [(r.get('canonical_smiles') or r.get('smiles'), {'component_key': r['component_key'], 'data_version': self.version}) for r in rows]
        if not raw and self.structural(name):
            result = self._tool('poly(' + name + ')')
            if (result.get('parser_status') == 'SUCCESS' and result.get('status') != 'AMBIGUOUS'
                    and result.get('stereo_state') != 'requested_not_encoded'):
                raw = [(result.get('candidate_smiles') or result.get('isomeric_smiles'), result.get('source', {}))]
        candidates = []
        for smiles, source in raw:
            mol = Chem.MolFromSmiles(smiles) if smiles else None
            if mol is None:
                continue
            ports = sum(atom.GetAtomicNum() == 0 for atom in mol.GetAtoms())
            if ports != 2:
                self.events.append({'tool': 'typed_structure', 'input': name, 'status': 'PARTIAL',
                                    'role': 'fragment', 'port_count': ports, 'candidate_smiles': smiles,
                                    'reason_code': 'NOT_A_TWO_PORT_LINEAR_UNIT'})
                continue
            periodic = canonicalize_unit(smiles)
            if periodic.get('status') == 'PARSED':
                candidates.append({'status': 'PARSED', 'unit_smiles': smiles, 'periodic': periodic,
                                   'subunit_names': [name], 'support_type': 'TOOL_OR_LIBRARY_UNIT_CANDIDATE',
                                   'rule_id': 'TYPED-COMPONENT-RESOLUTION/1.0', 'source': source,
                                   'name_independently_verified': False})
        distinct = {r['periodic']['periodic_graph_key']: r for r in candidates}
        result = next(iter(distinct.values())) if len(distinct) == 1 else original
        if len(distinct) > 1:
            result = fail('UNIT_ALIAS_HAS_MULTIPLE_STRUCTURES', 'AMBIGUOUS', candidates=candidates)
        events = self.__dict__.get('events')
        if events is not None:
            events.append({'tool': 'component_resolver', 'input': name, 'role': 'fragments_cu',
                                'status': result.get('status'), 'data_version': self.__dict__.get('version'),
                                'candidate_count': len(distinct), 'initiated_by': 'deterministic',
                                'resolution_origin': 'published_components' if rows else 'local_tool_or_unresolved',
                                'component_keys': [r['component_key'] for r in rows]})
        self.unit_cache[name] = result
        return result

    def counters(self):
        return {'local_tool_calls': self.calls, 'chemical_network_requests': 0,
                'library_resolution_events': sum(e['tool'] == 'component_resolver' for e in self.events)}
