"""Parse a complete printed scientific-notation literal, never an equation."""
import math
import re


def scientific_literal(surface: str) -> float | None:
    text=str(surface).replace('\\times','×')
    supers='⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻'
    table=str.maketrans(supers,'0123456789+-')
    text=re.sub(r'10(['+supers+r']+)',lambda m:'10^'+m[1].translate(table),text)
    text=re.sub(r'\s+','',text).replace('{','').replace('}','').replace('$','')
    match=re.fullmatch(r'([+-]?(?:\d+(?:\.\d*)?|\.\d+))[×x·]10\^([+-]?\d+)',text)
    if not match:return None
    mantissa=float(match[1]);exponent=int(match[2])
    if abs(exponent)>308:return None
    value=mantissa * 10.**exponent
    if not math.isfinite(value) or (value==0 and mantissa!=0):return None
    return value
