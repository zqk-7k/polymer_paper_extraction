"""Optional display interpretation; raw text and old strict mapping remain untouched."""
import re

from stages.standard_mapping import normalize_source_notation, resolve_standard_property


def clean_header(text):
    text = normalize_source_notation(text)
    # A degree mark typeset as superscript o is attached to the unit, not Tg/Tm.
    # Require the whole named temperature header; do not rewrite ratios or powers.
    text = re.sub(r'^(T[gm])\s*\^\s*(?:\{o\}|o)\s*C$', r'\1 (°C)', text)
    # Footnotes on these named scalar symbols are presentation marks, not powers.
    text = re.sub(r'((?:T[gmc]|M[nw]|PDI)(?:[12])?)\s*\^\s*(?:\{[a-h](?:,[a-h])*\}?|[a-h])', r'\1', text)
    text = re.sub(r'\s*\^\s*\{[a-h](?:,[a-h])*\}\s*$', '', text)
    text = re.sub(r'(?<=\))\s*[a-h]$', '', text)
    text = text.replace('T_c','Tc').replace('T_{c}','Tc')
    return text.strip()


def unit_expression(text):
    text = clean_header(text)
    # Exact source substring retained separately; these are notation equivalences only.
    text = re.sub(r'\{([^{}]*)\}',r'\1',text).replace('\\','').replace('^','')
    forms = [(r'Ω-1\s*cm-1|Omega-1\s*cm-1|S\s*cm\s*-1|S/cm', 'S/cm'),
             (r'kJ\s*[.·]?\s*mol\s*-1|kJ/mol','kJ/mol'),
             (r'J\s*g\s*-1|J/g','J/g'),(r'cm\s*-1','cm-1'),
             (r'mJ/m2','mJ/m2'),(r'mN/m','mN/m'),(r'dL/g|dl/g','dL/g'),
             (r'g/mol','g/mol'),(r'GPa|MPa|kPa','stress'),
             (r'°\s*C|℃','°C'),(r'(?<![A-Za-z])nm(?![A-Za-z])','nm')]
    for pattern, unit in forms:
        match = re.search(pattern,text,re.I)
        if match:
            return match[0] if unit=='stress' else unit
    if re.search(r'(?<!\w)%(?!\w)',text):
        return '%'
    return None


def enrich_fields(headers, name, raw_unit, caption=''):
    cleaned=[clean_header(h) for h in headers]
    unit=raw_unit
    unit_basis='source_token' if unit else 'not_stated_or_not_parsed'
    if not unit:
        for h in reversed(headers):
            unit=unit_expression(h)
            if unit:
                unit_basis='source_notation_interpreted';break
    mapped=resolve_standard_property(name,unit) if name else {}
    if not mapped.get('standard_property_code'):
        for h in reversed(cleaned):
            candidate=resolve_standard_property(h,unit)
            if candidate.get('standard_property_code'):
                mapped={**candidate,'standard_status':'standard_candidate',
                        'mapping_reasons':candidate['mapping_reasons']+['source_header_notation_or_group_interpreted']}
                break
    if not mapped.get('standard_property_code') and cleaned:
        leaf=cleaned[-1]
        alias=None
        interpretation_reason='symbol_interpretation_requires_review'
        if re.fullmatch(r'Tg[12]?\s*:\s*[-+]?\d+(?:\.\d+)?\s*°C',leaf):
            alias='glass transition temperature'
            interpretation_reason='explicit_inline_temperature_assignment'
        elif re.match(r'^Tc\b',leaf) and re.search(r'crystalli',caption,re.I):
            alias='crystallization temperature'
        elif re.fullmatch(r'(?:\\theta|θ)\s*\(°\)',leaf) and re.search(r'Water Contact Angles',caption,re.I):
            alias='contact angle'
            interpretation_reason='contact_angle_symbol_defined_by_table_caption'
        elif re.match(r'^X_?\{?C[, ]',leaf):
            alias='crystallinity'
            if re.search(r'Comparison of Experimental and Calculated Crystallinities',caption,re.I):
                interpretation_reason='crystallinity_symbol_defined_by_table_caption'
        elif re.match(r'^DP\b',leaf):
            alias='degree of polymerization'
        if alias:
            mapped=resolve_standard_property(alias,unit)
            mapped['standard_status']='standard_candidate'
            mapped['mapping_reasons'].append(interpretation_reason)
    scale=[h for h in headers if re.search(r'10\s*\^\s*\{?\s*[-+]?\d+',h)]
    component = re.fullmatch(r'X_?\{?C,\s*(PEP|sPP)\}?\s*\((exp|cal)\)',cleaned[-1]) if cleaned else None
    return {'unit_raw':raw_unit, 'unit_interpreted':unit, 'unit_interpretation_status':unit_basis,
            'measured_component_raw':component[1] if component else None,
            'result_origin':({'exp':'experimental','cal':'calculated'}[component[2]] if component else 'not_classified'),
            'scale_source_texts':scale, 'scale_status':'requires_interpretation' if scale else 'not_explicit',
            'standard_property_code':mapped.get('standard_property_code'),
            'standard_status':mapped.get('standard_status','standard_unmapped'),
            'standard_mapping_reasons':mapped.get('mapping_reasons',[])}


def caption_material(caption):
    # Only explicit named blend/composite phrases, not a generic guess from paper topic.
    match=re.search(r'properties of\s+([A-Z][A-Z0-9/+-]+)\s+(?:blends|composites)',caption or '')
    return {'text':match[1],'start':match.start(1),'end':match.end(1)} if match else None
