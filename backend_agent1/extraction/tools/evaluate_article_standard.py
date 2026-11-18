"""Property-value recall against the user workbook; no sample/condition matching.

Conservative numeric matching: explicit unit conversion, full range endpoints,
central values for uncertainty; never arbitrary power-of-ten rescaling.
"""
import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import html
import json
import math
from pathlib import Path
import re
import unicodedata


def clean(value):
    text=unicodedata.normalize('NFKC',str(value or '')).lower()
    text=re.sub(r'\\(?:mathrm|text|mathbf|operatorname)\s*\{([^{}]*)\}',r'\1',text)
    text=re.sub(r'[$_{}\\]',' ',text)
    return re.sub(r'\s+',' ',text.replace('-',' ').replace('η','eta').replace('λ','lambda')).strip()


def property_key(name, subtype=None):
    n=clean(name); sub=clean(subtype)
    if not n: return None
    if re.fullmatch(r'γ\s*s(?:\s*\^?\s*[pd])?',n):
        return 'surface_energy_polar' if sub=='polar' or n.endswith('p') else 'surface_energy_dispersive' if sub=='dispersive' or n.endswith('d') else 'surface_energy'
    if re.search(r'dispersity|polydispersity|molecular weight distribution|m\s*w\s*/\s*m\s*n|^pdi$',n): return 'dispersity'
    if n=='molecular weight' and sub in {'mn','mw','mz','mv'}: return sub
    if re.match(r'^m\s*[nwzv](?:\b|$)',n): return re.sub(r'\s+','',re.match(r'^m\s*[nwzv]',n)[0])
    if 'number average' in n and ('molecular' in n or 'molar' in n): return 'mn'
    if 'weight average' in n and ('molecular' in n or 'molar' in n): return 'mw'
    if 'molecular weight' in n or 'molar mass' in n: return 'molecular_weight'
    if 'contact angle' in n: return 'contact_angle'
    if 'surface' in n and any(x in n for x in ('tension','free energy','energy')):
        base='surface_energy' if 'energy' in n else 'surface_tension'
        if 'polar' in n and 'dispers' in n: return base+'_components'
        if 'polar' in n or sub=='polar': return base+'_polar'
        if 'dispers' in n or sub in {'dispersive','dispersion'}: return base+'_dispersive'
        return base
    if 'viscosity' in n or n.startswith('eta'):
        if 'intrinsic' in n or sub=='intrinsic' or n=='[eta]': return 'viscosity_intrinsic'
        if 'inherent' in n or sub=='inherent' or re.search(r'eta\s*inh',n): return 'viscosity_inherent'
        if 'reduced' in n or sub=='reduced': return 'viscosity_reduced'
        if 'specific' in n or sub=='specific': return 'viscosity_specific'
        if 'melt' in n: return 'melt_viscosity'
        if 'dynamic' in n: return 'dynamic_viscosity'
        return 'solution_viscosity'
    if re.search(r'glass transition|^tg\s*\d*$',n): return 'tg'
    if 'vicat' in n or n=='vst': return 'vicat'
    if 'softening temperature' in n: return 'softening'
    if re.search(r'heat of fusion|fusion enthalpy|melting enthalpy|enthalpy of (?:fusion|melting)',n) or re.fullmatch(r'δ\s*h\s*m',n): return 'heat_fusion'
    if 'melting' in n and ('temperature' in n or 'point' in n) or n=='tm': return 'tm'
    if 'crystallization temperature' in n or n=='tc': return 'tc'
    if 'crystallinity' in n or 'crystalline fraction' in n: return 'crystallinity'
    if 'degree of polymerization' in n or re.fullmatch(r'dp\s*n?',n): return 'dp'
    if re.search(r'decomposition.*(?:temperature|temp)|degradation.*temperature|(?:weight|mass) loss temperature|temperature.*(?:weight|mass) loss|^t[d5]|^t10',n): return 'td'
    if re.search(r'(?:weight|wt|mass).*loss|loss.*(?:weight|mass)',n): return 'weight_loss'
    if re.search(r'residual mass fraction|(?:%\s*)?residue|char yield',n): return 'residual_mass_fraction'
    if re.search(r'lc phase transition|liquid crystal.*transition|isotropization|clearing temperature',n): return 'lc_transition'
    if 'tensile' in n and ('strength' in n or 'stress' in n):
        return 'tensile_yield' if 'yield' in n else 'tensile_break' if 'break' in n else 'tensile_strength'
    if 'elongation' in n: return 'elongation_yield' if 'yield' in n else 'elongation_break'
    if 'tensile modulus' in n or "young's modulus" in n: return 'tensile_modulus'
    if 'izod' in n: return 'izod'
    if 'impact' in n and 'strength' in n: return 'impact'
    if 'conductivity' in n and 'thermal' not in n: return 'conductivity'
    if 'dielectric constant' in n or 'permittivity' in n:
        return 'dielectric_ac' if re.search(r'\bac\b',n+' '+sub) else 'dielectric_dc' if re.search(r'\bdc\b',n+' '+sub) else 'dielectric_unspecified'
    if 'oxygen index' in n or n=='loi': return 'oxygen_index'
    if 'water absorption' in n or 'water uptake' in n: return 'water_absorption'
    if re.search(r'lattice spacing|d spacing|interplanar|interlayer spacing',n) or n=='d': return 'd_spacing'
    if re.search(r'emission|photoluminescence|\bpl\b',n) and ('absorption' in n or 'uv' in n): return 'optical_combined'
    if re.search(r'emission|photoluminescence|lambda em|^pl',n): return 'emission'
    if re.search(r'absorption.*(?:wavelength|maximum|peak|band)|uv vis.*(?:max|lambda)|lambda (?:max|abs)',n): return 'absorption'
    if n=='treatment condition': return 'treatment_condition'
    return n


def compatible(g,p):
    if g==p: return 'same_property'
    if g=='molecular_weight' and p in {'mn','mw','mz','mv'}: return 'standard_unspecified_subtype'
    if g=='solution_viscosity' and p.startswith('viscosity_'): return 'standard_unspecified_subtype'
    if g=='tensile_strength' and p=='tensile_break': return 'standard_unspecified_endpoint'
    if g=='impact' and p=='izod': return 'standard_unspecified_method'
    if g=='optical_combined' and p in {'absorption','emission'}: return 'standard_combined_property'
    if g.endswith('_components') and p in {g[:-11]+'_polar',g[:-11]+'_dispersive'}: return 'standard_combined_property'
    return None


NUM=r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
def numbers(raw):
    if raw is None: return [],'unparsed'
    text=str(raw)
    text=re.sub(r'([⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+)',lambda m:'^'+m[0].translate(str.maketrans('⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻','0123456789+-')),text)
    text=unicodedata.normalize('NFKC',text).replace('−','-').replace('–','~').replace('—','~')
    text=text.replace('\\times','×').replace('\\cdot','×').replace('\\pm','±').replace('\\sim','~')
    text=re.sub(r'\\(?:mathrm|text|mathbf)\s*\{([^{}]*)\}',r'\1',text)
    text=re.sub(r'[${}]','',text)
    text=re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))','',text)
    text=re.sub(r'(?<![\w.])\d{1,3}(?:[ \u2009\u202f]\d{3})+(?!\d)',lambda m:re.sub(r'\s','',m[0]),text)
    text=re.sub(r'(?<=\d)\s*\.\s*(?=\d)', '.',text)
    text=re.sub(r'(?<=\d)[eE]\s*\(\s*([-+]?\d+)\s*\)',r'e\1',text)
    text=re.sub(r'('+NUM+r')\s*[×x*]\s*10\s*\^\s*([-+]?\s*\d+)',
                lambda m:str(float(m[1])*10**int(m[2].replace(' ',''))),text)
    text=re.sub(r'(?<![\w.])10\s*\^\s*([-+]?\s*\d+)',lambda m:str(10**int(m[1].replace(' ',''))),text)
    text=re.sub(r'(?<=\d)\s+-\s+(?=\d)',' ~ ',text)
    text=re.sub(r'(?<=\d)-(?=\d)','~',text)
    kind='less' if re.search(r'<|≤|less than|below',text,re.I) else 'greater' if re.search(r'>|≥|greater than|above',text,re.I) else 'scalar'
    if '±' in text: text=text.split('±',1)[0]
    # Exponents in unit suffixes are not measured values.
    text=re.split(r'(?<=[0-9)])\s*(?:°|deg|nm|mm|cm|mN|mJ|MPa|GPa|kPa|Pa|g/mol|kg/mol|dL|mL|S/|J/|kJ/|kcal/)',text,1)[0]
    vals=[float(m[0]) for m in re.finditer(NUM,text)]
    vals=[v for v in vals if math.isfinite(v)]
    if kind in {'less','greater'}: return vals[:1],kind
    if re.search(r'~|\bto\b',text) and len(vals)==2: return vals,'range'
    if len(vals)>1:
        if re.search(r'[,;/]|\band\b',text): return vals,'multiple'
        return [],'unparsed'
    return vals,'scalar' if vals else 'unparsed'


def unit_key(unit):
    s=unicodedata.normalize('NFKC',str(unit or '')).lower().strip().replace('−','-')
    s=re.sub(r'[$\s{}\\]','',s).replace('^','').replace('°','').replace('·','').replace('*','')
    aliases={'degrees':'degree','deg':'degree','wt%':'%','wt.%':'%','percent':'%',
             'celsius':'c','kelvin':'k','å':'angstrom','a':'angstrom','1/(ohmcm)':'s/cm',
             'ohm-1cm-1':'s/cm','scm-1':'s/cm','sm-1':'s/m','mjm-2':'mj/m2',
             'mnm-1':'mn/m','dlg-1':'dl/g','mlg-1':'ml/g','gmol-1':'g/mol','kgmol-1':'kg/mol',
             'dimensionless':'','none':''}
    return aliases.get(s,s)


def convert(vals,source_unit,target_unit):
    a,b=unit_key(source_unit),unit_key(target_unit)
    if not a or not b: return vals,'unit_not_required_or_missing'
    if a==b: return vals,'same_unit'
    groups=[{'pa':1,'kpa':1e3,'mpa':1e6,'gpa':1e9}, {'j/m':1,'kj/m':1000},
            {'j/g':1,'kj/g':1000,'cal/g':4.184,'kcal/g':4184},
            {'nm':1,'angstrom':.1,'um':1000}, {'g/mol':1,'kg/mol':1000},
            {'s/cm':1,'s/m':.01}, {'dl/g':1,'ml/g':.01}, {'mn/m':1,'mj/m2':1,'n/m':1000}]
    if a in {'c','k'} and b in {'c','k'}:
        return [v+(273.15 if a=='c' else -273.15) for v in vals],a+'_to_'+b
    for group in groups:
        if a in group and b in group: return [v*group[a]/group[b] for v in vals],a+'_to_'+b
    return None,'incompatible_or_unrecognized_unit'


def scaled_unit(unit):
    text=unicodedata.normalize('NFKC',str(unit or '')).replace('−','-')
    m=re.fullmatch(r'\s*(?:[×x*]\s*)?10\s*\^\s*\{?([-+]?\d+)\}?\s*(.*)',text)
    return (10**int(m[1]),m[2]) if m else (1,unit)


def close(a,b): return math.isclose(a,b,rel_tol=1e-6,abs_tol=1e-15)


def value_match(g,p):
    values,kind=numbers(p.get('value_raw'))
    factor,unit=scaled_unit(p.get('unit_raw'))
    values,operation=convert([v*factor for v in values],unit,g['unit'])
    if factor!=1: operation='explicit_unit_scale_'+str(factor)+';'+operation
    if values is None: return False,operation
    _,gold_kind=numbers(g.get('raw_value'))
    if kind in {'less','greater'} or gold_kind in {'less','greater'}:
        return kind==gold_kind and len(values)==1 and g['minimum'] is not None and close(values[0],g['minimum']), 'same_inequality' if kind==gold_kind else 'inequality_mismatch'
    if kind=='unparsed': return False,'inequality_or_unparsed'
    lo,hi=g['minimum'],g['maximum']
    if lo is None or hi is None: return False,'standard_value_unparsed'
    if not close(lo,hi):
        return kind=='range' and len(values)==2 and close(values[0],lo) and close(values[1],hi),operation
    if kind=='range': return False,'range_not_scalar'
    if operation in {'c_to_k','k_to_c'} and any(abs(v-lo)<=.05000001 for v in values):
        return True,operation+'_reporting_rounding_0.05'
    if '_to_' in operation and operation not in {'c_to_k','k_to_c'}:
        rounding=.5*10**Decimal(str(lo)).as_tuple().exponent
        if any(abs(v-lo)<=rounding+1e-15 for v in values):
            return True,operation+'_standard_reported_precision'
    return any(close(v,lo) for v in values),operation


def source_confirmed_keys(p):
    """Limited evidence-assisted naming; never search evidence for result numbers."""
    keys=pred_keys(p)
    quote=str(p.get('model_source_reference',{}).get('quote') or '')
    excerpt=str(p.get('source_excerpt') or '')
    name=clean(p.get('property_name_raw'))
    if keys=={'molecular_weight'}:
        found=set(re.findall(r'\bM([nwzv])\b',quote))
        if len(found)==1: keys.add('m'+next(iter(found)))
    if re.fullmatch(r'lambda\s*max',name) and re.search(r'absorption|uv.?vis',quote+' '+excerpt,re.I):
        keys.add('absorption')
    return keys


def source_standard_key(g):
    key=g['property_key']
    if key.startswith('surface_tension') and re.search(r'surface free energ',g.get('evidence_excerpt',''),re.I):
        return key.replace('surface_tension','surface_energy')
    return key


def read_standard(path):
    import openpyxl
    book=openpyxl.load_workbook(path,read_only=True,data_only=True)
    it=book['Sheet1'].iter_rows(values_only=True); headers=next(it); rows=[]
    def number(v):
        try: return float(v)
        except (ValueError,TypeError): return None
    for row_no,values in enumerate(it,2):
        r=dict(zip(headers,values))
        if not r.get('论文编号'): continue
        name=r.get('规范性质名_v3') or r.get('原文复核后规范性质名') or r.get('规范性质名称') or r.get('性质名称')
        key=property_key(name)
        notes=[]; raw=str(r.get('原始值') or '')
        if key=='optical_combined':
            # Workbook explicitly enumerates UV-vis then PL and records component index.
            if 'UV-vis' in raw and 'PL' in raw and r.get('数值分量序号') in (0,1):
                key=['absorption','emission'][int(r['数值分量序号'])]; notes.append('standard_component_index')
        if key in {'surface_tension_components','surface_energy_components'} and 'polar and dispersive' in raw.lower() and r.get('数值分量序号') in (0,1):
            key=key.replace('_components',['_polar','_dispersive'][int(r['数值分量序号'])]); notes.append('standard_component_index')
        v3=bool(r.get('标准集版本'))
        low=r.get('数值最小_v3') if v3 else r['数值最小']
        high=r.get('数值最大_v3') if v3 else r['数值最大']
        rows.append({'excel_row':row_no,'global_id':r['全局序号'],'document_id':r['论文编号'],
                     'property':name,'property_key':key,'minimum':number(low),
                     'maximum':number(high) if high is not None else number(low),
                     'raw_value':r.get('原始值_v3') if v3 else r.get('原始值'),
                     'unit':r.get('规范单位_v3') if v3 else r.get('原文复核后规范单位') or r.get('规范单位'),
                     'main_include_v3':r.get('主评估纳入_v3'), 'evaluation_category_v3':r.get('评估类别_v3'),
                     'old_main_include':r.get('主评估纳入_v2'),'standard_notes':notes,
                     'evidence_excerpt':r.get('证据摘录') or ''})
    return rows


def pred_keys(p):
    direct=property_key(p.get('property_name_raw'),p.get('property_subtype'))
    catalog=property_key(p.get('standard_property_name'),p.get('property_subtype'))
    # A broad catalog parent never erases an explicitly extracted subtype.
    if direct in {'mn','mw','mz','mv','dispersity','dielectric_ac','dielectric_dc'} or (direct or '').startswith('viscosity_'):
        return {direct}
    return {k for k in (direct,catalog) if k}


def semantic_value_match(g,p):
    ok,operation=value_match(g,p)
    if ok: return ok,operation
    # Only temperature conversions use the integer/decimal precision of the gold
    # value. Inequalities, ranges and missing units never get this relaxation.
    values,kind=numbers(p.get('value_raw'))
    if kind!='scalar' or numbers(g.get('raw_value'))[1] in {'less','greater'} or len(values)!=1 or g['minimum'] is None or g['minimum']!=g['maximum']:
        return False,operation
    converted,op=convert(values,p.get('unit_raw'),g['unit'])
    if op not in {'c_to_k','k_to_c'}:return False,operation
    lo=g['minimum']; exponent=0 if float(lo).is_integer() else Decimal(str(lo)).as_tuple().exponent
    return abs(converted[0]-lo)<=.5*10**exponent+1e-10,op+'_gold_reporting_precision'


def evaluate(standard,batch_root,output_dir,prior_summary=None,semantic=False):
    standard,batch_root,output_dir=map(Path,(standard,batch_root,output_dir))
    original=standard.read_bytes(); gold=read_standard(standard)
    predictions=defaultdict(list); status={}; versions={}; input_hashes={}
    batch_summary=batch_root/'summary.json'
    if batch_summary.is_file():
        for item in json.loads(batch_summary.read_text(encoding='utf8')).get('documents',[]):
            status[item['document_id']]=item['status']
            versions[item['document_id']]='catalog_subtype_v2'
    loaded=set()
    paths=sorted(batch_root.glob('runs/*/summary.json'))
    if prior_summary: paths.append(Path(prior_summary))
    for path in paths:
        s=json.loads(path.read_text(encoding='utf8'))
        doc=s['documents'][0]['document_id']
        if doc in loaded: raise ValueError('Duplicate article result')
        loaded.add(doc)
        status[doc]=s['status']; versions[doc]='prior_article_once' if prior_summary and path==Path(prior_summary) else 'catalog_subtype_v2'
        p=Path(s['export_dir'])/'model_extractions.jsonl'
        predictions[doc]=[json.loads(line) for line in p.read_text(encoding='utf8').splitlines()]
        input_hashes[str(p.resolve())]=hashlib.sha256(p.read_bytes()).hexdigest()
    details=[]
    for g in gold:
        same=[]; matches=[]; source_matches=[]; near=[]; unit_issues=[]
        for p in predictions[g['document_id']]:
            keys=pred_keys(p)
            relation=next((compatible(g['property_key'],k) for k in keys if compatible(g['property_key'],k)),None)
            ok,operation=value_match(g,p)
            if relation:
                same.append(p)
                if ok: matches.append((p,relation,operation))
                elif operation in {'incompatible_or_unrecognized_unit','inequality_or_unparsed'}: unit_issues.append(operation)
            elif ok:
                # Retain same-value candidates for review, never count unrelated numbers.
                near.append(p)
            if ok and not relation:
                relation2=next((compatible(source_standard_key(g),k) for k in source_confirmed_keys(p)
                                if compatible(source_standard_key(g),k)),None)
                if relation2: source_matches.append((p,'source_confirmed_property',operation))
            if g['property_key']=='weight_loss' and g['minimum'] is not None and g['maximum'] is not None and close(g['minimum'],g['maximum']) and unit_key(g['unit'])=='%' and 'td' in keys:
                sub=clean(p.get('property_subtype'))
                threshold=re.fullmatch(r't(?:d)?\s*\^?\s*(\d+(?:\.\d+)?)\s*%?',sub)
                if threshold and close(float(threshold[1]),g['minimum']):
                    projected={**p,'value_raw':threshold[1],'unit_raw':'%'}
                    source_matches.append((projected,'loss_threshold_explicit_in_subtype','explicit_percent_subtype'))
            if semantic:
                candidates=[(p,'reported_precision')]
                for v in p.get('semantic_normalization',{}).get('interpretations',[]):
                    if v.get('relation') not in {'measurement','threshold'}:continue
                    if v.get('relation')=='threshold' and g['property_key']!='weight_loss':continue
                    candidates.append(({**p,'property_name_raw':v['property_name'],
                        'standard_property_name':None,'property_subtype':None,
                        'value_raw':v['value'],'unit_raw':v['unit']},v['rule']))
                for candidate,rule in candidates:
                    relation3=next((compatible(source_standard_key(g),k) for k in pred_keys(candidate)
                                    if compatible(source_standard_key(g),k)),None)
                    if relation3:
                        hit,op=semantic_value_match(g,candidate)
                        if hit:source_matches.append((candidate,'semantic:'+rule,op))
        best=matches[0] if matches else None
        if best: outcome='matched'
        elif source_matches: best=source_matches[0]; outcome='matched_with_source'
        else: outcome='article_not_completed' if status.get(g['document_id'])!='text_scan_finished' else 'value_not_matched' if same else 'property_not_matched'
        row={k:v for k,v in g.items() if k!='evidence_excerpt'}
        row['source_confirmed_standard_key']=source_standard_key(g)
        row.update(status=outcome,run_status=status.get(g['document_id'],'not_run'),version=versions.get(g['document_id']),
                   matched_observation_id=best[0]['observation_id'] if best else None,
                   matched_property=best[0]['property_name_raw'] if best else None,
                   matched_subtype=best[0].get('property_subtype') if best else None,
                   matched_value=best[0]['value_raw'] if best else None,
                   matched_unit=best[0].get('unit_raw') if best else None,
                   property_match_basis=best[1] if best else None,unit_operation=best[2] if best else None,
                   same_property_candidates=[{'id':p['observation_id'],'property':p['property_name_raw'],'value':p['value_raw'],'unit':p.get('unit_raw')} for p in same],
                   same_value_other_properties=[{'id':p['observation_id'],'property':p['property_name_raw'],'subtype':p.get('property_subtype'),'value':p['value_raw']} for p in near],
                   parsing_or_unit_issues=sorted(set(unit_issues)))
        details.append(row)
    def tally(rows):
        unique={}; direct_unique={}
        for r in rows:
            qualifier=numbers(r.get('raw_value'))[1]
            key=(r['document_id'],r['property_key'],r['minimum'],r['maximum'],unit_key(r['unit']),qualifier if qualifier in {'less','greater'} else None)
            unique[key]=unique.get(key,False) or r['status'] in {'matched','matched_with_source'}
            direct_unique[key]=direct_unique.get(key,False) or r['status']=='matched'
        matched=sum(r['status'] in {'matched','matched_with_source'} for r in rows)
        direct=sum(r['status']=='matched' for r in rows)
        return {'standard_rows':len(rows),'matched_rows':matched,'row_recall':matched/len(rows) if rows else None,
                'field_only_matched_rows':direct,'field_only_recall':direct/len(rows) if rows else None,
                'unique_property_value_pairs':len(unique),'matched_unique_pairs':sum(unique.values()),
                'unique_recall':sum(unique.values())/len(unique) if unique else None,
                'field_only_matched_unique_pairs':sum(direct_unique.values()),
                'field_only_unique_recall':sum(direct_unique.values())/len(unique) if unique else None,
                'statuses':dict(Counter(r['status'] for r in rows))}
    docs=sorted({r['document_id'] for r in gold})
    summary={**tally(details),'evaluated_property_value_only':True,'sample_binding_evaluated':False,
             'standard_workbook':str(standard.resolve()),'standard_sha256':hashlib.sha256(original).hexdigest(),
             'standard_document_count':len(docs),'input_hashes':input_hashes,
             'completed_standard_documents':sum(status.get(d)=='text_scan_finished' for d in docs),
             'new_version_only':tally([r for r in details if r['version']=='catalog_subtype_v2']),
             'successful_articles_only':tally([r for r in details if r['run_status']=='text_scan_finished']),
             'property_scope_excluding_process_conditions':tally([r for r in details if r['property_key']!='treatment_condition']),
             'documents':[{'document_id':d,'run_status':status.get(d,'not_run'),'version':versions.get(d),
                           'model_rows':len(predictions[d]),**tally([r for r in details if r['document_id']==d])} for d in docs],
             'properties':[{'property_key':p,**tally([r for r in details if r['property_key']==p])} for p in sorted({r['property_key'] for r in details})],
             'no_standard_documents':sorted(set(status)-set(docs)),
             'limitations':['No sample or condition matching; repeated standard values may reuse one prediction.',
                 'Only explicit unit conversion; no arbitrary rescaling, approximate range overlap or reference-text number scanning.',
                 'Field-only matches and source/subtype-confirmed matches are recorded separately; unresolved name/unit variants remain unmatched.',
                 'All workbook rows retained, including process conditions outside extraction scope.'],
             'precision':None,'new_api_calls':0,'semantic_normalization_enabled':semantic,
             'v3_main_scope':tally([r for r in details if r.get('main_include_v3')=='是']) if any(r.get('main_include_v3') for r in details) else None,
             'v3_categories':{c:tally([r for r in details if r.get('evaluation_category_v3')==c]) for c in sorted({r['evaluation_category_v3'] for r in details if r.get('evaluation_category_v3')})}}
    if semantic:
        summary['limitations'][2]='Evidence-aware derived views are scored separately from raw fields; ambiguous OCR definitions remain unresolved.'
    if standard.read_bytes()!=original: raise ValueError('Standard workbook changed')
    output_dir.mkdir(parents=True,exist_ok=True)
    (output_dir/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    (output_dir/'details.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in details),encoding='utf8')
    render(summary,details,output_dir)
    return summary


def render(summary,details,out):
    lines=['# 整篇单次抽取：标准集性质和值对比','',
           f"标准集 {summary['standard_document_count']} 篇，完成抽取 {summary['completed_standard_documents']} 篇；只比较性质和值，不比较样品、条件和方法。",
           '',f"按标准集行（含明确来源/子类型确认）：{summary['matched_rows']}/{summary['standard_rows']} = {summary['row_recall']:.2%}。",
           f"其中仅字段直接匹配：{summary['field_only_matched_rows']}/{summary['standard_rows']} = {summary['field_only_recall']:.2%}。",
           f"按文章、性质和值去重：{summary['matched_unique_pairs']}/{summary['unique_property_value_pairs']} = {summary['unique_recall']:.2%}。",
           '', '标准集分母全部保留，旧表“主评估不纳入”不自动剔除；失败文章单独标记。精确数值允许明确单位换算和浮点误差，不使用任意倍率或范围重叠制造命中。',
           '', '0043541 沿用上一版结果，其余使用本轮完整性质目录和子类型版本。字段直接匹配包含确定的同义名、符号、千位分隔和显式倍率单位换算；来源/子类型确认只允许明确的分子量类型、标准证据明确的表面自由能名称，以及 T5/T10 等已提取的失重阈值，不从整段原文搜到数字就算命中。摄氏/开尔文换算容许 0.05 度报告舍入差，其他明确单位换算容许标准数值末位的半个单位舍入差。缺失单位时只能比数值，不能证明单位正确；来源确认属于有限规则对齐，不等同于逐条人工核实。',
           '', '|文章|运行状态|标准行|字段命中|含来源确认命中|含确认召回率|', '|---|---|---:|---:|---:|---:|']
    for r in summary['documents']: lines.append(f"|{r['document_id']}|{r['run_status']}|{r['standard_rows']}|{r['field_only_matched_rows']}|{r['matched_rows']}|{r['row_recall']:.1%}|")
    lines+=['','|统计范围|标准行|字段匹配召回率|含来源确认召回率|','|---|---:|---:|---:|']
    for key,label in [('new_version_only','本轮新版本（含失败）'),('successful_articles_only','成功文章（含上一版 0043541）'),('property_scope_excluding_process_conditions','全标准集排除处理条件')]:
        r=summary[key]
        if r['standard_rows']: lines.append(f"|{label}|{r['standard_rows']}|{r['field_only_recall']:.2%}|{r['row_recall']:.2%}|")
    lines+=['','范围外的处理条件另有排除后统计，但没有从以上主分母删除。没有标准记录的文章：'+', '.join(summary['no_standard_documents']),
            '', '模型结果多于标准集不等于误提；本次不计算精确率。旧流程未完整跑完，不能用这个绝对召回率证明新流程相对提升。']
    if summary.get('semantic_normalization_enabled'):
        lines=[line for line in lines if '0043541 沿用上一版结果，其余使用本轮完整性质目录' not in line]
        lines+=['','本轮启用带证据的语义视图；原始模型记录未改。温标换算按标准报告精度比较；不纠正原文单位冲突，不把条件自动当成测量。']
    if summary.get('v3_main_scope'):
        v=summary['v3_main_scope']
        lines+=['',f"v3 正文表格主评估：{v['matched_rows']}/{v['standard_rows']} = {v['row_recall']:.2%}。以上全1542行分数仍保留；分母分类变化不代表模型召回提升。"]
        lines+=['','|v3类别|记录数|匹配数|','|---|---:|---:|']
        lines += [f"|{c}|{v['standard_rows']}|{v['matched_rows']}|" for c,v in summary['v3_categories'].items()]
    (out/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    esc=lambda v:html.escape(str(v if v is not None else ''))
    parts=['<!doctype html><html lang="zh"><meta charset="utf-8"><title>性质和值召回对比</title>',
           '<style>body{font:15px/1.6 system-ui;margin:24px;color:#203045}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}th{position:sticky;top:0;background:#eaf1f8}td{max-width:400px;overflow-wrap:anywhere}input,select{padding:8px;margin:8px}</style>',
           '<h1>性质和值召回对比</h1>',f"<p>含来源/子类型确认命中 {summary['matched_rows']}/{summary['standard_rows']}（{summary['row_recall']:.2%}）；字段直接匹配 {summary['field_only_recall']:.2%}；去重后 {summary['matched_unique_pairs']}/{summary['unique_property_value_pairs']}（{summary['unique_recall']:.2%}）。</p>",
           '<p>忽略样品和条件。未匹配可能是漏提、名称或单位尚未确认；运行失败单列。0043541 是上一版结果，其他为本轮新版本。每行保留标准集 Excel 行号。</p>',
           '<p><a href="report.md">逐篇汇总</a> · <a href="summary.json">完整统计</a> · <a href="details.jsonl">对账明细</a></p>',
           '<input id="q" placeholder="文章、性质、数值"><select id="s"><option value="">全部</option><option value="matched">字段命中</option><option value="matched_with_source">来源或子类型确认</option><option value="value_not_matched">同性质，值未匹配</option><option value="property_not_matched">性质未匹配</option><option value="article_not_completed">文章未完成</option></select>',
           '<table><thead><tr><th>文章 / Excel 行</th><th>标准性质 / 值 / 单位</th><th>模型性质 / 值</th><th>状态和候选</th></tr></thead><tbody>']
    if summary.get('v3_main_scope'):
        v=summary['v3_main_scope']
        parts.insert(5,f"<p>v3正文表格范围：{v['matched_rows']}/{v['standard_rows']}（{v['row_recall']:.2%}）。其余类别保留在全量统计，分母分类变化不代表模型提升。</p>")
    for r in details:
        candidates=r['same_property_candidates'] if r['same_property_candidates'] else r['same_value_other_properties']
        candidates=candidates if r['status'] not in {'matched','matched_with_source'} else []
        parts.append(f'<tr data-status="{esc(r["status"])}"><td>{esc(r["document_id"])}<br>{r["excel_row"]}</td><td>{esc(r["property"])}<br>{esc(r["minimum"])}–{esc(r["maximum"])} {esc(r["unit"])}</td><td>{esc(r["matched_property"])} {esc(r["matched_subtype"])}<br>{esc(r["matched_value"])}</td><td>{esc(r["status"])}'+
                     ('<details><summary>候选对照</summary><pre>'+esc(json.dumps(candidates,ensure_ascii=False,indent=2))+'</pre></details>' if candidates else '')+'</td></tr>')
    parts.append('</tbody></table><script>function f(){let q=document.querySelector("#q").value.toLowerCase(),s=document.querySelector("#s").value;document.querySelectorAll("tbody tr").forEach(r=>r.hidden=!(r.textContent.toLowerCase().includes(q)&&(!s||r.dataset.status===s)))}document.querySelector("#q").oninput=f;document.querySelector("#s").onchange=f;</script></html>')
    (out/'report.html').write_text('\n'.join(parts),encoding='utf8')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--standard',type=Path,required=True); p.add_argument('--batch-root',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True); p.add_argument('--prior-summary',type=Path)
    p.add_argument('--semantic',action='store_true',help='Use evidence-aware derived views and reporting precision; retain raw all-row scores')
    result=evaluate(**vars(p.parse_args()))
    print(json.dumps({k:v for k,v in result.items() if k not in {'documents','properties','input_hashes'}},ensure_ascii=True))
