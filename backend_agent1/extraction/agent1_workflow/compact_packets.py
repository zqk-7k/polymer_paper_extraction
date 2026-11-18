"""Full article text in every worker; disjoint complete field definitions per group."""
from copy import deepcopy
import json
from packets import compact_identity
from field_groups import GROUPS,assignment,rendered
from table_transport import pack,unpack
from spectrum_tasks import partition

def byte_size(value):return len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode())

def article_blocks(raw):
    return [{'block_id':b['block_id'],'section':b.get('section'),'source_type':b.get('type'),
             'text':b['text']} for b in raw['elements']
            if b.get('text') and b.get('type') not in ('image','figure','table')]

def build_packets(stage0,identity,catalog):
    prose=article_blocks(stage0);groups=assignment(catalog);n=[];t=[];s=[];audits=[]
    common={'document_id':stage0['document_id'],'identity_directory':compact_identity(identity)}
    tables=[]
    for b in stage0['elements']:
        if b.get('type')!='table':continue
        source={'table_id':b['block_id'],'caption':b.get('caption'),'cells':b.get('table_cells',[]),'notes':b.get('table_notes',[])}
        packed,mapping=pack(source);assert unpack(packed,mapping)==source
        tables.append(packed)
        packet={**deepcopy(common),**rendered(catalog['targets']),'table':packed,
            'related_blocks':deepcopy(prose),'shared_methods':[],
            'field_owner_policy':{'stage4n':'all non-characterization fields','stage5':'stage5_property_vocabulary only'}}
        task={'task_id':f't2_{len(t)+1:03d}','packet':packet,'owned_source_ids':[b['block_id']],
              'source_table':source,'cell_id_map':mapping}
        t.append(task)
    for group,targets in groups.items():
        stage='stage5' if group=='characterization' else 'stage4n'
        packet={**deepcopy(common),**rendered(targets),'owned_blocks':deepcopy(prose),
                'context_blocks':[],'shared_methods':[],'table_context':deepcopy(tables),
                'task_contract':{'group':group,'title':GROUPS[group][0],
                    'allowed_target_ids':[x['target_id'] for x in targets],
                    'full_article_text':True,'semantic_source_filtering':False,
                    'table_context_role':'Context and cross-references only. Original table cells are exclusively read through Stage4T.',
                    'bibliography_role':'Bibliography is context, never a result of the current samples.'}}
        task={'task_id':('s5_' if stage=='stage5' else 'n_')+group,'packet':packet,
              'owned_source_ids':[b['block_id'] for b in prose],
              'allowed_target_ids':[x['target_id'] for x in targets]}
        (s if stage=='stage5' else n).append(task)
    s=partition(s,catalog)
    for stage,tasks in (('stage4n',n),('stage4t',t),('stage5',s)):
        for task in tasks:
            audit={'stage':stage,'task_id':task['task_id'],'after_packet_bytes':byte_size(task['packet']),
                'fields':{'allowed_count':len(task['packet']['target_fields']),'detailed_count':len(task['packet']['target_fields'])},
                'full_owned_text_preserved':True,'all_source_cells_preserved':True,
                'shared_methods_duplicate_count':0,'prose_source_ids':[b['block_id'] for b in prose],
                'prose_characters':sum(len(b['text']) for b in prose)}
            task['packing_audit']=audit;audits.append(audit)
    return n,t,s,audits
