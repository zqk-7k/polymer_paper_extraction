"""Reversible typography view used only for evidence matching, never output values."""
import re,unicodedata,html

COMMANDS={'circ':'°','times':'×','cdot':'·','pm':'±','mu':'μ','alpha':'α','beta':'β','gamma':'γ'}
LAYOUT={'mathrm','textrm','text','operatorname','mathbf','mathit','left','right','displaystyle'}

def view(source):
    text=str(source or '');chars=[];offsets=[];i=0
    while i<len(text):
        start=i;c=text[i]
        if c=='<':
            m=re.match(r'</?(?:sup|sub|span|i|b|em|strong)(?:\s[^>]*)?>',text[i:])
            if m:i+=len(m[0]);continue
        if c=='&':
            m=re.match(r'&(?:#[0-9]+|#x[0-9a-fA-F]+|[a-zA-Z]+);',text[i:])
            if m:
                value=html.unescape(m[0]);i+=len(m[0])
                for z in value:chars.append(z);offsets.append((start,i))
                continue
        if c=='\\':
            m=re.match(r'\\([A-Za-z]+|[,;! ])',text[i:])
            if m:
                word=m[1]
                if word in COMMANDS:
                    i+=len(m[0]);chars.append(COMMANDS[word]);offsets.append((start,i));continue
                if word in LAYOUT or word in ',;! ':
                    i+=len(m[0]);continue
        if c.isspace() or c in '${}^_':i+=1;continue
        if c=='~' and re.match(r'~\s*\^\s*\{\s*\\circ',text[i:]):i+=1;continue
        value=unicodedata.normalize('NFKC',c).replace('−','-')
        for z in value:chars.append(z);offsets.append((i,i+1))
        i+=1
    return ''.join(chars),offsets

def original_span(source,quote):
    if not isinstance(quote,str) or not quote:return None
    text,offsets=view(source);wanted,_=view(quote)
    if not wanted:return None
    positions=[]
    for m in re.finditer('(?='+re.escape(wanted)+')',text):
        a=m.start();b=a+len(wanted)
        if wanted[0].isdigit() and a and text[a-1] in '0123456789.,+-':continue
        if wanted[-1].isdigit() and b<len(text) and text[b] in '0123456789.,':continue
        positions.append(a)
    if len(positions)!=1:return None
    a=positions[0];start=offsets[a][0];end=offsets[a+len(wanted)-1][1]
    return {'quote':str(source)[start:end],'source_start':start,'source_end':end,
            'matching_policy':'unique_reversible_typography.v2'}

def matches(source,quote):return original_span(source,quote) is not None
