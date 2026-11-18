"""Exclusive extraction ownership; shared table interpretation is not a third owner."""
from collections import defaultdict
from field_definitions import definition

GROUPS={
 'thermal':('热性质',{'thermal_property','heat_characteristic'}),
 'tensile':('拉伸性质',{'tensile_property'}),
 'other_mechanics':('剪切弯曲压缩冲击硬度',{'shear_property','flexural_property','compression_characteristic','impact_strength','hardness'}),
 'creep_rheology':('蠕变与流变',{'creep_characteristic','rheological_property'}),
 'solution_molecular':('溶液与分子信息',{'dilute_solution_property'}),
 'interface_transport':('界面与传输',{'physicochemical_property'}),
 'structure_material':('结构与材料描述',set()),
 'electrical_optical_physical':('电学光学与基础物性',{'electrical_property','optical_property','physical_property'}),
 'other_targets':('燃烧耐热及其他性质',{'heat_resistance_and_combustion','other_property'}),
 'characterization':('表征性质',set())}

def group_for(target):
    if target['section']=='stage5_property_vocabulary':return 'characterization'
    if target['section']=='specialized_property_vocabulary':
        return 'solution_molecular' if target['property_key'] in ('molecular_weight','solution_viscosity','degree_of_polymerization') else 'structure_material'
    schema=target['definition'];category=schema[1] if isinstance(schema,list) else None
    matches=[name for name,(_,categories) in GROUPS.items() if category in categories]
    assert len(matches)==1,(target['target_id'],category)
    return matches[0]

def assignment(catalog):
    groups=defaultdict(list)
    for t in catalog['targets']:groups[group_for(t)].append(t)
    assert set(groups)==set(GROUPS)
    return dict(groups)

def rendered(targets):
    index={}
    for t in targets:index.setdefault(t['section'],[]).append(t['property_key'])
    return {'target_index':index,'target_fields':[{'target_id':t['target_id'],
        'definition':definition(t),'subtype_required':t.get('subtype_required',False)} for t in targets]}

def owner(target_id):
    return 'stage5' if str(target_id).startswith('stage5_property_vocabulary:') else 'stage4n'
