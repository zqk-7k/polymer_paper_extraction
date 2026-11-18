"""Read-only polymer/source-group hierarchy; no unique synthesis is inferred."""
from copy import deepcopy

VERSION = 'composite-source-evidence/1.0'


def annotate(parsed, components):
    by_id = {c['occurrence_id']: c for c in components}
    groups, members, rows = [], [], []
    def walk(node, parent=None, polymers=(), pool=None, level=0):
        kind, ident = node.get('kind'), node.get('occurrence_id')
        active_polymers = polymers
        if kind == 'polymer':
            active_polymers = polymers + (node['raw'],)
        if kind == 'source_pool':
            pool = ident
            groups.append({'occurrence_id': ident, 'members': [c.get('raw') for c in node['children']],
                'meaning': '名称中分号分组的来源集合；组内排列与实际比例未指定',
                'not_assumed': ['blend', 'random_sequence', 'equal_fractions']})
        if kind != 'group':
            rows.append({'occurrence_id': ident, 'parent_occurrence': parent,
                'level': level, 'kind': kind, 'operator': node.get('operator'), 'label': node.get('raw')})
        for child in node.get('children', []):
            walk(child, ident if kind != 'group' else parent, active_polymers, pool, level + (kind != 'group'))
        if node.get('children'):
            return
        component = by_id.get(ident)
        if component is None:
            return
        # One outer wrapper describes the product. Deeper wrappers name polymeric sources.
        nested = len(active_polymers) > 1
        context = {'source_pool_id': pool, 'polymer_wrappers': list(active_polymers),
                   'polymeric_source': nested, 'polymeric_source_name': active_polymers[-1] if nested else None,
                   'finite_graph_role': 'naming_source_of_polymeric_member' if nested else 'direct_named_source',
                   'chain_length': 'NOT_REPORTED', 'actual_polymer_end_groups': 'NOT_INFERRED'}
        component['hierarchy_context'] = context
        groups_present = bool(pool or nested)
        if groups_present:
            members.append({'occurrence_id': ident, 'name': active_polymers[-1] if nested else node.get('raw'),
                'member_role': '聚合物来源 / 预聚物描述' if nested else '有限来源分子',
                'source_name': node.get('raw'), 'source_graph_key': component.get('graph_key'),
                'group': pool, 'chain_length': '未报告' if nested else '不适用',
                'graph_meaning': '所示小分子是该聚合物的命名来源，不是整条预聚物' if nested else '已解析有限来源结构'})
    walk(parsed.get('ast') or {})
    return {'version': VERSION, 'groups': groups, 'members': members, 'tree_rows': rows,
            'whole_repeat_unit_is_unique': False, 'actual_synthesis_verified': False,
            'scope': 'name_declared_hierarchy_not_complete_product_structure',
            'limitations': ['分号组保持集合层次，不改写为共混或随机序列。',
                           '聚合物来源的链长、末端基团和全产品重复单元不能由来源列表唯一确定。']}
