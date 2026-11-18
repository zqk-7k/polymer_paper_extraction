"""Read saved PDF page images; no extraction or chemical inference."""
from html import escape
from urllib.parse import quote

def render_source_pages(job_id, title, filenames, page=1):
    if not filenames:
        raise ValueError('SOURCE_PAGE_IMAGES_MISSING')
    selected=max(1,min(int(page),len(filenames)))
    prefix='/source/'+quote(job_id,safe='')+'/'
    links=''.join(f'<a'+(' aria-current="page"' if i==selected else '')+f' href="#p{i}">第 {i} 页</a>' for i in range(1,len(filenames)+1))
    figures=''
    for i,entry in enumerate(filenames,1):
        name=entry['name'] if isinstance(entry,dict) else entry
        dimensions=(f' width="{entry["width"]}" height="{entry["height"]}"' if isinstance(entry,dict) and entry.get('width') and entry.get('height') else '')
        figures+=f'<figure id="p{i}"><figcaption>原文第 {i} 页</figcaption><img src="{prefix}pages/{quote(name,safe="")}" alt="原文第 {i} 页"{dimensions} loading="lazy"></figure>'
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>阅读原文 · Polymer Identity</title><style>body{margin:0;background:#f0f5f8;color:#203d50;font:14px/1.6 system-ui,sans-serif}header{position:sticky;top:0;background:#fff;border-bottom:1px solid #dce4ec;padding:12px 20px;z-index:1}header strong{display:block;overflow-wrap:anywhere}nav{display:flex;gap:12px;flex-wrap:wrap}a{color:#245e83}main{max-width:1100px;margin:auto;padding:20px}figure{margin:0 0 24px;scroll-margin-top:125px}figcaption{padding:8px 0}img{display:block;width:100%;height:auto;background:#fff;box-shadow:0 1px 5px #cad6df}</style>'
        '<header><strong>'+escape(title or '来源文献')+'</strong><nav><a href="/paper/'+quote(job_id,safe='')+'">返回身份证</a><a href="'+prefix+'source.pdf">原始 PDF</a>'+links+'</nav></header><main>'+figures+'</main>'
        '</html>').encode('utf-8')
