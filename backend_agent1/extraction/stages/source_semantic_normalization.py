"""Evidence-aware derived views. Raw model records and publication status are immutable.

No gold rows, article IDs, or sample-specific values are used by these rules.
Definitions with an incomplete OCR symbol remain unresolved rather than guessed.
"""
from copy import deepcopy
import re
import unicodedata

VERSION = 'source_semantics.v1'
NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'


def plain(value):
    text = unicodedata.normalize('NFKC', str(value or '')).lower()
    text = re.sub(r'\\(?:mathrm|text|mathbf|overline|bar)\s*\{([^{}]*)\}', r'\1', text)
    text = text.replace('\\lambda', 'λ').replace('\\%', '%')
    text = re.sub(r'[$_{}\\]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def contexts(data):
    """Accept both source inventories and saved whole-article request packets."""
    blocks = data.get('evidence_blocks', data.get('source_blocks', []) + data.get('source_context_blocks', []))
    result = {b['block_id']: b.get('text') or '' for b in blocks}
    tables = {}
    for t in data.get('related_tables', data.get('tables', [])):
        headers=[]
        for c in t.get('cells', []):
            row, header, text = (c[1], c[5], c[6]) if isinstance(c, list) else (c.get('row_index',99), c.get('is_header'), c.get('text',''))
            if header or row < 2:
                headers.append(str(text))
        tables[t['table_id']] = ' '.join([str(t.get('caption') or ''), *map(str,t.get('table_notes') or []), *headers])
    return result, tables


def normalize_observations(observations, data):
    blocks, tables = contexts(data)
    definitions = []
    # Capture only explicit symbol definitions. Do not infer Ti == 0% or 2%.
    for bid, text in blocks.items():
        for match in re.finditer(r'(\d+(?:\.\d+)?)\s*%\s*(?:gravimetric|weight|mass)\s*loss\s*\(\s*(t\s*(?:i|\d+))\s*\)', plain(text)):
            definitions.append((re.sub(r'\s','',match[2]), float(match[1]), bid))
    output=[]
    for original in observations:
        row=deepcopy(original)
        prop=plain(row.get('property_name_raw')); compact=re.sub(r'\s','',prop)
        value=str(row.get('value_raw') or ''); unit=row.get('unit_raw')
        bid=row.get('source_block_id'); tid=row.get('table_id')
        local=' '.join([tables.get(tid,''), blocks.get(bid,''), row.get('source_excerpt') or '',
                        str(row.get('model_source_reference',{}).get('quote') or '')])
        local_plain=plain(local)
        variants=[]; unresolved=[]

        def add(name, val, u, rule, relation='measurement', evidence=None, component=None):
            record={'property_name':name,'value':val,'unit':u,'rule':rule,'relation':relation,
                    'evidence_ids':evidence or [x for x in (row.get('source_locator'),) if x]}
            if component: record['component']=component
            if record not in variants: variants.append(record)

        if re.fullmatch(r'(?:λ|lambda)em',compact):
            add('emission wavelength',value,unit,'emission_symbol')
        if re.fullmatch(r'(?:λ|lambda)(?:max|abs)',compact):
            # A standalone lambda-max is ambiguous between absorption and emission.
            absorption_context = re.search(r'absorption|uv.?vis|photophysical|log\s*(?:ε|epsilon)|(?:ε|epsilon).*max',local_plain)
            if absorption_context:
                add('absorption wavelength',value,unit,'absorption_symbol_with_context',evidence=[x for x in (tid,bid) if x])
            else: unresolved.append('lambda_max_context_missing')

        if re.search(r'dielectric constant|permittivity',prop):
            cond=' '.join(str(c.get('value_raw') or '') for c in row.get('condition_context_raw',[]) if isinstance(c,dict))
            sub=str(row.get('property_subtype') or '')
            positive_frequency = re.search(r'(?<![\d.])([0-9]+(?:\.[0-9]+)?)\s*[kmg]?\s*hz\b',cond+' '+sub,re.I)
            explicit_dc=re.search(r'\bdc\b',prop+' '+plain(sub)+' '+plain(cond))
            if positive_frequency and float(positive_frequency[1])>0:
                if explicit_dc: unresolved.append('dc_frequency_conflict')
                else: add('dielectric constant ac',value,unit,'positive_measured_frequency')

        if 'crystallinity' in prop or 'crystalline fraction' in prop:
            # Retain exp/cal and phase; never extract arbitrary digits from compound text.
            parts=re.findall(r'(X\s*_?\s*C\s*,\s*[^=;]+?)\s*=\s*('+NUMBER+r')(?=\s*(?:;|$))',value,re.I)
            for component,num in parts:
                if not (unit is None or str(unit).strip() in ('','1','dimensionless')):
                    continue
                if 0<=float(num)<=1:
                    add('degree of crystallinity',format(float(num)*100,'.12g'),'%','explicit_crystallinity_fraction',component=component.strip())
            if not parts and re.fullmatch(NUMBER,value.strip()) and str(unit).lower() in ('fraction','mass fraction','volume fraction','1','dimensionless') and 0<=float(value)<=1:
                add('degree of crystallinity',format(float(value)*100,'.12g'),'%','explicit_fraction_unit')

        subtype=re.sub(r'\s','',plain(row.get('property_subtype')))
        temperature_name=re.fullmatch(r't(?:d)?(\d+(?:\.\d+)?)%?',compact) or re.fullmatch(r't(?:d)?(\d+(?:\.\d+)?)%?',subtype)
        if temperature_name and str(unit).lower() in ('c','°c','k','kelvin'):
            percent=float(temperature_name[1])
            if 0<percent<=100:
                add('weight loss',str(percent),'%','explicit_loss_temperature_subtype',relation='threshold')
        if compact in ('ti','tdi'):
            matches=[(v,b) for symbol,v,b in definitions if symbol==compact]
            amounts={v for v,_ in matches}
            if len(amounts)==1:
                add('weight loss',str(next(iter(amounts))),'%','source_defined_loss_threshold','threshold',[b for _,b in matches])
            else: unresolved.append('initial_loss_threshold_not_explicit')

        if str(unit).strip().lower() in ('k','kelvin') and re.fullmatch(NUMBER,value.strip()) and re.search(r'temperature|^t\s*[gmcdi]|melting point',prop):
            add(row['property_name_raw'],format(float(value)-273.15,'.12g'),'°C','kelvin_to_celsius')

        # Generic conditions remain conditions. They never become a measured peak.
        condition_views=[]
        for c in row.get('condition_context_raw',[]):
            if isinstance(c,dict) and plain(c.get('name_raw')) in ('tc','crystallization temperature'):
                condition_views.append({'property_name':'crystallization temperature','value':c.get('value_raw'),
                                        'relation':'condition','rule':'crystallization_condition'})
        row['semantic_normalization']={'version':VERSION,'interpretations':variants,
            'condition_views':condition_views,'unresolved':unresolved}
        output.append(row)
    return output
