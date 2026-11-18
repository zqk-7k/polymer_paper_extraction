"""Reversible range glyph and closing-math punctuation evidence compatibility."""
import re,sys
import evidence_text

_original_span=evidence_text.original_span
_original_view=evidence_text.view


def closing_dollars(source):
    result=set();opened=None
    for match in re.finditer(r'\$+',source):
        start=match.start();slashes=0
        while start-slashes-1>=0 and source[start-slashes-1]=='\\':slashes+=1
        if slashes%2 or len(match[0])>2:continue
        if opened is None:opened=len(match[0])
        elif opened==len(match[0]):
            result.update(range(match.start(),match.end()));opened=None
    return result


def range_view(source):
    source=str(source)
    text,offsets=_original_view(source);chars=list(text)
    for i,char in enumerate(chars):
        if char in ('–','—') and i and i+1<len(chars) and chars[i-1].isdigit() and chars[i+1].isdigit():
            chars[i]='-'
    closing=closing_dollars(source);result=[];positions=[]
    for char,span in zip(chars,offsets):
        if char==',' and result and result[-1]==',':
            gap=source[positions[-1][1]:span[0]]
            dollars={i for i in range(positions[-1][1],span[0]) if source[i]=='$'}
            if re.fullmatch(r'[\s}]*\${1,2}\s*',gap) and dollars and dollars.issubset(closing):
                positions[-1]=(positions[-1][0],span[1]);continue
        result.append(char);positions.append(span)
    return ''.join(result),positions


def original_span(source,quote):
    exact=_original_span(source,quote)
    if exact:return exact
    if not isinstance(quote,str) or not quote:return None
    text,offsets=range_view(source);wanted,_=range_view(quote)
    if not wanted or not any(c.isalnum() for c in wanted):return None
    positions=[]
    for match in re.finditer('(?='+re.escape(wanted)+')',text):
        a=match.start();b=a+len(wanted)
        if wanted[0].isdigit() and a and text[a-1] in '0123456789.,+-':continue
        if wanted[-1].isdigit() and b<len(text) and text[b] in '0123456789.,':continue
        positions.append(a)
    if len(positions)!=1:return None
    a=positions[0];start=offsets[a][0];end=offsets[a+len(wanted)-1][1]
    return {'quote':str(source)[start:end],'source_start':start,'source_end':end,
        'matching_policy':'unique_original_display_equivalence.v2.2'}


def install():
    if getattr(evidence_text,'numeric_range_extension_installed',False):return
    evidence_text.original_span=original_span
    # Some intake modules import the function by value; keep their references aligned.
    for name in ('intake_v2','legend_scope'):
        module=sys.modules.get(name)
        if module is not None:module.original_span=original_span
    evidence_text.numeric_range_extension_installed=True
