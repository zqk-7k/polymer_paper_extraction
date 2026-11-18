"""Explicit named-subunit assembly; candidate only, not preferred-CRU validation."""
from copy import deepcopy
from .supplied_fragment_join import assemble
CONTRACT='declared-cru-candidate/1.0'


def propose(parts):
    if not isinstance(parts,list) or not 2<=len(parts)<=10:
        raise ValueError('DECLARED_SUBUNITS_REQUIRED')
    fragments=[];links=[]
    for index,part in enumerate(parts):
        if not isinstance(part,dict) or not isinstance(part.get('name'),str) or not part['name'].strip():
            raise ValueError('SUBUNIT_NAME_REQUIRED')
        if len(part['name'])>180 or any(c in part['name'] for c in '\n\r'):
            raise ValueError('SUBUNIT_NAME_INVALID')
        if type(part.get('left_port')) is not int or type(part.get('right_port')) is not int or part['left_port']==part['right_port']:
            raise ValueError('TWO_DECLARED_PORTS_REQUIRED')
        fragments.append({'id':'u'+str(index),'smiles':part.get('smiles'),'src':deepcopy(part.get('src'))})
        if index:
            links.append({'left':{'fragment':'u'+str(index-1),'port':parts[index-1]['right_port']},
                'right':{'fragment':'u'+str(index),'port':part['left_port']},'bond':'single',
                'src':list(dict.fromkeys(parts[index-1]['src']+part['src']))})
    assembly=assemble(fragments,links)
    if assembly['status']!='ASSEMBLED_CANDIDATE' or len(assembly['remaining_ports'])!=2:
        return {'contract':CONTRACT,'status':'UNDETERMINED','assembly':assembly,'primary':None}
    text='poly['+''.join('('+p['name']+')' for p in parts)+']'
    return {'contract':CONTRACT,'status':'CANDIDATE','assembly':assembly,
        'primary':{'text':text,'kind':'structure_based','status':'CANDIDATE',
            'scope':'DECLARED_REPEAT_CONSTITUTION_ONLY','src':assembly['src'],
            'basis':'Ordered explicitly named subunits; graph assembled using existing port operation',
            'rule_locator':'IUPAC Brief Guide §4.1; RSSOP §4 Rule 1',
            'limitations':['Subunit name-to-graph consistency and preferred CRU require independent review.',
                'No end groups, molecular weight distribution or actual sample identity inferred.']},
        'declared_parts':deepcopy(parts),'preferred_iupac_name':None,
        'full_iupac_conformance':False,'source_fact':False,'automatic_update':False,
        'independent_review':'NOT_REVIEWED'}
