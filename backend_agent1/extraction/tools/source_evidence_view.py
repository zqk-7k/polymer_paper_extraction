"""Local-only source table viewer. All source text is inserted as text, never HTML."""
import json


def evidence_view(data):
    tables=data.get('tables',[])
    rows=[{k:r.get(k) for k in ('document_id','table_id','source_cell_id','property_header_cell_ids','sample_axis_cell_ids','condition_context_raw','source_kind','source_block_id','source_spans','source_support','citation_verification','model_source_reference')} for r in data['observations']]
    payload=json.dumps({'tables':tables,'blocks':data.get('source_blocks',[])+data.get('source_context_blocks',[]),'rows':rows},ensure_ascii=False).replace('<',r'\u003c').replace('\u2028',r'\u2028').replace('\u2029',r'\u2029')
    return '''<style>dialog{width:90vw;max-width:1200px;max-height:85vh;border:1px solid #cbd5e1;border-radius:8px;padding:24px}dialog::backdrop{background:#0005}.source-scroll{overflow:auto;max-height:52vh}.source-value{background:#ffe18d}.source-axis{background:#dcecff}.source-condition{background:#e1f4de}button{padding:7px 10px;cursor:pointer}#source-title{font-size:20px}#source-context{white-space:pre-wrap}#source-close{float:right}dialog th{position:static}</style>
<dialog id="source-dialog"><button id="source-close" type="button">关闭来源</button><h2 id="source-title"></h2><p>黄色：当前值；蓝色：性质/材料依据；绿色：条件或单位。来源文字保持原样。</p><p id="source-caption"></p><div class="source-scroll"><div id="source-text" style="white-space:pre-wrap"></div><table id="source-grid"></table></div><p id="source-notes"></p><details><summary>查看相邻正文（上下文参考，未自动认定为测量条件）</summary><div id="source-context"></div></details></dialog>
<script type="application/json" id="source-evidence">'''+payload+r'''</script>
<script>(()=>{const data=JSON.parse(document.getElementById('source-evidence').textContent),dialog=document.getElementById('source-dialog');
const tables=new Map(data.tables.map(t=>[(t.document_id||'')+'|'+t.table_id,t]));
const blocks=new Map(data.blocks.map(b=>[(b.document_id||'')+'|'+b.block_id,b]));
document.querySelectorAll('button[data-observation]').forEach(button=>button.onclick=()=>{const r=data.rows[Number(button.dataset.observation)],t=tables.get(r.document_id+'|'+r.table_id)||tables.get('|'+r.table_id);
const sourceText=document.getElementById('source-text');sourceText.replaceChildren();document.getElementById('source-grid').replaceChildren();
if(r.source_kind==='text'&&!r.table_id){const b=blocks.get(r.document_id+'|'+r.source_block_id)||blocks.get('|'+r.source_block_id);if(!b){document.getElementById('source-title').textContent=r.document_id+' / 来源位置未定位';document.getElementById('source-caption').textContent='模型结果已保留，精确引用未核对。';document.getElementById('source-notes').textContent='';document.getElementById('source-context').textContent='';sourceText.textContent=JSON.stringify(r.model_source_reference||{},null,2);dialog.showModal();return;}
document.getElementById('source-title').textContent=r.document_id+' / '+b.block_id+' / 页 '+(b.page??'未注明');
document.getElementById('source-caption').textContent=r.citation_verification==='best_effort'?'模型提供或程序定位的来源；对应关系未独立核实':'正文中的明确对应关系';document.getElementById('source-notes').textContent='每条为一次原文提及；重复提及尚未合并为独立测量。';document.getElementById('source-context').textContent='';
const spans=Object.entries(r.source_spans),edges=[...new Set([0,b.text.length,...spans.flatMap(([,s])=>[s.start,s.end])])].sort((a,b)=>a-b);for(let i=1;i<edges.length;i++){const start=edges[i-1],end=edges[i],cover=spans.filter(([,s])=>s.start<=start&&s.end>=end),name=cover.find(([n])=>n==='value')?.[0]||cover.find(([n])=>n==='unit')?.[0]||cover[0]?.[0],part=b.text.slice(start,end);if(!name){sourceText.append(document.createTextNode(part));continue}const mark=document.createElement('mark');mark.className=name==='value'?'source-value':name==='unit'?'source-condition':'source-axis';mark.textContent=part;sourceText.append(mark)}
for(const support of r.source_support||[]){const extra=blocks.get(r.document_id+'|'+support.block_id)||blocks.get('|'+support.block_id);if(extra){const p=document.createElement('p');p.textContent=(support.role&&support.role!=='material'?'引用依据 ':'材料依据 ')+support.block_id+'：'+extra.text;sourceText.append(p)}}dialog.showModal();return}
if(!t)return;document.getElementById('source-title').textContent=r.document_id+' / '+t.table_id+' / 页 '+(t.page??'未注明');
document.getElementById('source-caption').textContent=t.caption||'表题未保存';
document.getElementById('source-notes').textContent='表注：'+(t.table_notes?.join('\n')||'未保存；可展开相邻正文核对');
document.getElementById('source-context').textContent=(t.nearby_text_blocks||[]).map(b=>b.block_id+'\n'+(b.text||'')).join('\n\n');
const grid=document.getElementById('source-grid');grid.replaceChildren();const axes=new Set([...(r.property_header_cell_ids||[]),...(r.sample_axis_cell_ids||[])]),conditions=new Set((r.condition_context_raw||[]).map(c=>c.cell_id));
let rowIndex=-1,tr;for(const c of [...t.cells].sort((a,b)=>a.row_index-b.row_index||a.column_index-b.column_index)){if(c.row_index!==rowIndex){tr=document.createElement('tr');grid.append(tr);rowIndex=c.row_index}const td=document.createElement('td');td.textContent=c.text;td.rowSpan=c.row_span;td.colSpan=c.column_span;td.title=c.cell_id;
if(c.cell_id===r.source_cell_id)td.className='source-value';else if(axes.has(c.cell_id))td.className='source-axis';else if(conditions.has(c.cell_id))td.className='source-condition';tr.append(td)}dialog.showModal();grid.querySelector('.source-value')?.scrollIntoView({block:'nearest'})});
document.getElementById('source-close').onclick=()=>dialog.close();})();</script>'''
