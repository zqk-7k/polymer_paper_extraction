"""Locate explicitly cited figures without reading or estimating their values."""
import re


LABEL = re.compile(r'\b(Figures?|Figs?\.?|Schemes?|Charts?)\s*(S?\d+)\b', re.I)
GROUP = re.compile(r'\b(Figures?|Figs?\.?|Schemes?|Charts?)\s*'
                   r'(S?\d+(?:\s*\([a-z]\))?(?:\s*(?:,\s*(?:and\s+)?|and\s+|to\s+|[-–—])\s*S?\d+(?:\s*\([a-z]\))?)*)', re.I)


def references(text):
    found = set()
    for match in GROUP.finditer(text or ''):
        kind = 'figure' if match[1].lower().startswith('fig') else match[1].lower().rstrip('s')
        tokens = re.findall(r'S?\d+', match[2], re.I)
        found.update((kind, t.upper()) for t in tokens)
        for start, end in re.findall(r'\b(S?\d+)\s*(?:[-–—]|to)\s*(S?\d+)\b', match[2], re.I):
            if start.upper().startswith('S') != end.upper().startswith('S'):
                continue
            lo, hi = int(start.lstrip('sS')), int(end.lstrip('sS'))
            if lo <= hi <= lo+50:
                prefix='S' if start.upper().startswith('S') else ''
                found.update((kind,prefix+str(n)) for n in range(lo,hi+1))
    return found


def build_figure_links(data):
    blocks = data.get('source_blocks', []) + data.get('source_context_blocks', [])
    rows=[]
    for figure in data.get('source_figure_blocks', []):
        caption=figure.get('caption') or ''
        match=LABEL.search(caption)
        key=(('figure' if match[1].lower().startswith('fig') else match[1].lower().rstrip('s')),match[2].upper()) if match else None
        mentions=[{'block_id':b['block_id'],'text':b.get('text') or ''}
                  for b in blocks if key and key in references(b.get('text') or '')]
        mentioned_ids={b['block_id'] for b in mentions}
        observations=[r['observation_id'] for r in data.get('observations',[])
                      if r.get('source_block_id') in mentioned_ids]
        rows.append({'document_id':data['document_id'],'figure_block_id':figure['block_id'],
                     'figure_label':match[0] if match else None,'caption':caption,
                     'image_path':figure.get('image_path'),'page':figure.get('page'),
                     'asset_roots':data.get('source_asset_roots',[]),
                     'mention_blocks':mentions,'related_observation_ids':observations,
                     'relation_basis':'explicit_figure_reference_in_same_block' if mentions else 'figure_caption_inventory',
                     'evidence_mode':'figure_reference_only','value_extraction_required':False})
    return rows
