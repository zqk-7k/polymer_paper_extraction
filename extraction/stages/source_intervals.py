"""Read explicit reported intervals/bounds without splitting them into scalars."""
import math
import re

NUMBER=r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
VERSION='1.0.1'


def reported_interval(surface):
    text=str(surface or '').strip().replace('−','-')
    text=re.sub(r'\$|\\(?:left|right)', '',text)
    text=text.replace(r'\leq','≤').replace(r'\geq','≥').replace(r'\le','≤').replace(r'\ge','≥')
    approximate=bool(re.match(r'^(?:~|≈|\\sim|\\approx)\s*(?=[+\-\d.])',text))
    if approximate:text=re.sub(r'^(?:~|≈|\\sim|\\approx)\s*','',text)
    bound=re.fullmatch(rf'\s*(<=|>=|<|>|≤|≥)\s*({NUMBER})\s*',text)
    if bound:
        value=float(bound[2])
        if not math.isfinite(value):return None
        return {'minimum':value,'maximum':value,'kind':'bound','inequality':{'≤':'<=','≥':'>='}.get(bound[1],bound[1])}
    match=re.fullmatch(rf'\s*({NUMBER})\s*(?:–|—|~|〜|\bto\b)\s*({NUMBER})\s*',text,re.I)
    if not match:return None
    low,high=float(match[1]),float(match[2])
    if not math.isfinite(low) or not math.isfinite(high) or low>=high:return None
    return {'minimum':low,'maximum':high,'kind':'range','inequality':None,
            **({'approximate':True} if approximate else {})}
