from __future__ import annotations
from collections import Counter
import math,re
from rdkit import Chem
from .common import fail

def parse_formula(text):
    if not isinstance(text,str) or not text or len(text)>300:return None
    tokens=re.findall(r'[A-Z][a-z]?\d*',text)
    if ''.join(tokens)!=text:return None
    out=Counter();pt=Chem.GetPeriodicTable();elements={pt.GetElementSymbol(i) for i in range(1,119)}
    for tok in tokens:
        m=re.fullmatch(r'([A-Z][a-z]?)(\d*)',tok)
        if m[1] not in elements:return None
        try:z=pt.GetAtomicNumber(m[1])
        except RuntimeError:return None
        if z<=0:return None
        n=int(m[2] or 1)
        if n<=0:return None
        out[m[1]]+=n
    return dict(out)

def validate_formula(inputs):
    a=inputs.get('observed');b=inputs.get('reference_formulas');scope=inputs.get('scope')
    if not a:return fail('FORMULA_MISSING','NEEDS_DETAILS',decision='INDETERMINATE',hard_filter_allowed=False)
    if not isinstance(a,list) or not isinstance(b,list):return fail('FORMULA_LIST_REQUIRED','INVALID',decision='INDETERMINATE',hard_filter_allowed=False)
    if scope!='same_explicit_unit':return fail('FORMULA_SCOPE_OR_COMPONENT_BINDING_REQUIRED','NEEDS_DETAILS',decision='INDETERMINATE',hard_filter_allowed=False)
    aa=[parse_formula(x) for x in a];bb=[parse_formula(x) for x in b]
    if not all(x is not None for x in aa+bb):return fail('SYMBOLIC_OR_UNSUPPORTED_FORMULA','NEEDS_DETAILS',decision='INDETERMINATE',hard_filter_allowed=False)
    same=aa==bb
    return {'status':'PARSED' if same else 'CONFLICT','decision':'MATCH' if same else 'MISMATCH','hard_filter_allowed':True,'formula_match':same,'scope':scope,'no_period_multiple_inferred_from_formula':True}

def validate_composition(inputs):
    basis=inputs.get('basis');vals=inputs.get('values');tol=inputs.get('tolerance',1e-8)
    if basis not in ('mole_fraction','mass_fraction','feed_mole_fraction','feed_mass_fraction'):
        return fail('COMPOSITION_BASIS_REQUIRED','NEEDS_DETAILS',valid=False)
    if isinstance(vals,dict):vals=list(vals.values())
    if not isinstance(vals,list) or not vals:return fail('COMPOSITION_VALUES_REQUIRED','INVALID',valid=False)
    if not isinstance(tol,(int,float)) or not math.isfinite(tol) or not 0<=tol<=0.01:return fail('INVALID_COMPOSITION_TOLERANCE','INVALID',valid=False)
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 or v>1 for v in vals):return fail('FRACTION_OUT_OF_RANGE','INVALID',valid=False)
    total=sum(vals);complete=inputs.get('completeness','complete')=='complete'
    if (complete and abs(total-1)>tol) or (not complete and total>1+tol):return fail('FRACTION_SUM_INVALID','INVALID',valid=False,total=total)
    return {'status':'PARSED','valid':True,'basis':basis,'total':total,'is_feed_not_product':basis.startswith('feed_'),'completeness':'complete' if complete else 'partial'}

def bind_composition(composition,components):
    """Bind fractions to actual occurrence IDs; duplicate names need explicit IDs.
    A feed composition stays feed composition. No automatic name-order zip.
    """
    check=validate_composition(composition)
    if check['status']!='PARSED':return check
    values=composition.get('values')
    if not isinstance(values,dict):return fail('NAMED_OR_OCCURRENCE_COMPOSITION_REQUIRED','NEEDS_DETAILS')
    by_id={c['occurrence_id']:c for c in components};by_name={}
    for c in components:by_name.setdefault(c['raw'].strip(),[]).append(c)
    resolved={}
    for ref,value in values.items():
        candidates=[by_id[ref]] if ref in by_id else by_name.get(ref,[])
        if len(candidates)!=1:return fail('COMPOSITION_REFERENCE_UNKNOWN_OR_AMBIGUOUS','NEEDS_DETAILS',reference=ref)
        ident=candidates[0]['occurrence_id']
        if ident in resolved:return fail('DUPLICATE_COMPOSITION_TARGET','INVALID')
        resolved[ident]=value
    if composition.get('completeness','complete')=='complete' and set(resolved)!=set(by_id):
        return fail('COMPLETE_COMPOSITION_DOES_NOT_BIND_ALL_OCCURRENCES','NEEDS_DETAILS')
    return {**check,'binding_scope':'explicit_component_occurrences','bound_values':resolved}
