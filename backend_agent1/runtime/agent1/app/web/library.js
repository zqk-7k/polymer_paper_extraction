/* The library reads sealed source records; it does not alter chemical identities. */
const libraryGroups={monomer:'单体与命名来源',polymer:'聚合物组分',precursor:'前体与中间体',solvent:'溶剂与介质',catalyst:'催化剂与引发剂',additive:'添加与固化组分',reagent:'反应试剂',other:'其他组分'};
const libraryAssociationLabels={composition:'明确组成',precursor:'前体与来源',process:'工艺辅助',naming:'命名来源',other:'其他关联'};
let libraryPassport=null,librarySelectedRecord=null,librarySourceSelected=false,libraryActiveKey='',libraryActiveTab='identity',libraryDialogSeq=0,libraryFetchSeq=0,libraryPaneTimer=null;
let librarySourceQuery='',libraryAssociationQuery='',libraryAssociationCategory='all';
let libraryRevision='',libraryRefreshPending=false;
const libraryIcons={search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',paper:'<path d="M7 3h8l4 4v14H5V3h2Z M14 3v5h5 M8 12h8 M8 16h6"/>',arrow:'<path d="M7 17 17 7 M7 7h10v10"/>',close:'<path d="m6 6 12 12 M6 18 18 6"/>',identity:'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 9h5 M7 13h10 M7 16h7"/>'};
function libraryIcon(name){return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">'+libraryIcons[name]+'</svg>'}
function libraryRole(role){return ({actual_source_monomer:'实际来源单体',source_monomer:'来源单体',naming_source:'命名来源',nomenclature_source:'命名来源',naming_source_monomer:'命名来源单体',nomenclature_source_monomer:'命名来源单体',solvent:'溶剂',purification_solvent:'纯化溶剂',reaction_solvent:'反应溶剂',polycondensation_catalyst:'缩聚催化剂',catalyst:'催化剂',filler:'填料',decomposition_product:'分解产物',workup_and_recrystallization:'后处理与重结晶',preparation_agent_not_product_constituent:'制备辅助，不属于产物组成',process_catalyst_not_polymer_constituent:'工艺催化剂，不属于聚合物组成'})[role]||words[role]||String(role||'原文未说明').replaceAll('_',' ')}
function libraryLink(e,id=e.id){return '/paper/'+encodeURIComponent(e.job_id)+'?material='+encodeURIComponent(id)}
function libraryExternal(href,text,cls=''){return '<a class="'+cls+'" href="'+href+'" target="_blank" rel="noopener noreferrer">'+text+libraryIcon('arrow')+'</a>'}

function libraryNameCheckBadge(v){
 if(!v||['NOT_CHECKED','NOT_APPLICABLE','NO_FINITE_GRAPH'].includes(v.status))return '';
 const tone=['GRAPH_MATCH','PREPARED_GRAPH_MATCH'].includes(v.status)?'matched':v.status==='MISMATCH'?'mismatch':'pending';
 return '<span class="name-check-badge '+tone+'">OPSIN · '+esc(v.status_label||v.status)+'</span>';
}
function libraryNameCheckPanel(v){
 if(!v)return '';
 const mismatch=v.status==='MISMATCH',matched=['GRAPH_MATCH','PREPARED_GRAPH_MATCH'].includes(v.status);
 return '<section class="name-check-panel '+(mismatch?'mismatch':'')+'"><div class="tool-section-heading"><h3>名称与结构核验</h3>'+libraryNameCheckBadge(v)+'</div>'+
 '<p>'+esc(v.primary_name||'当前来源名称')+'</p>'+
 (v.status==='PREPARED_GRAPH_MATCH'?'<p class="name-check-note">原记录名称未被解析；以下补充写法与保存图一致：'+esc((v.matching_names||[]).join('；'))+'</p>':'')+
 '<p class="tool-method-note">'+esc(mismatch?'名称解析结果与保存图不同，需复核；不会按分子式相同或删除立体信息放行。':v.status==='PARSER_GRAPH_BOUNDARY'?'OPSIN 已输出元素原子；现有有限分子工具不接受这类自由基图，未标为分子核验通过。':matched?'核对范围是本来源名称与已编码有限分子图；不代表文献事实或完整名称已确定。':v.status_label||'尚无补充核验')+'</p>'+
 ((v.checks||[]).length?'<details><summary>查看 '+v.checks.length+' 条真实工具结果</summary>'+v.checks.map(ch=>'<div class="name-check-receipt"><strong>'+esc(ch.name)+'</strong><span>'+esc(({GRAPH_MATCH:'结构一致',MISMATCH:'结构不同',UNSUPPORTED:'未通过有限分子核对'})[ch.status]||ch.status)+'</span><p>OPSIN：'+esc(ch.parser_result?.parser_status||ch.parser_result?.status||'未运行')+(ch.reason_code?' · '+esc(ch.reason_code):'')+'</p>'+(ch.parser_result?.candidate_smiles?'<code>'+esc(ch.parser_result.candidate_smiles)+'</code>':'')+'</div>').join('')+'<small>OPSIN '+esc(v.provider?.opsin_version||'2.9.0')+' · 核验时间 '+esc((v.checked_at||'').replace('T',' ').slice(0,19))+' UTC · 回执 '+esc(v.receipt_sha256||'')+'</small></details>':'')+'</section>';
}

function libraryShell(){
 $('.workspace').classList.toggle('library-view',true);$('.workspace').classList.toggle('paper-directory',false);
 $('#reader').innerHTML='<div class="catalog-heading"><div><p class="catalog-eyebrow">文献中的化学组分</p><h1>组分库</h1><p>从化学身份出发，查看每一篇来源与每一种关联。</p></div><div id="library-summary" class="catalog-statistics"></div></div>'+
 '<div class="catalog-controls"><div class="catalog-search">'+libraryIcon('search')+'<input id="library-search" type="search" placeholder="搜索名称、文献写法或分子式" aria-label="搜索组分"></div><div class="catalog-filter-row"><div id="library-groups" class="catalog-groups" aria-label="组分用途筛选"></div><details class="catalog-options"><summary>更多筛选</summary><div><label>记录类型<select id="library-kind" aria-label="组分类型"><option value="all">全部类型</option></select></label><label>显示方式<select id="library-view" aria-label="组分显示方式"><option value="components">组分汇总</option><option value="records">逐篇记录</option></select></label></div></details></div></div>'+
 '<div class="catalog-result-bar"><div><span id="library-result-count"></span><button id="library-reset" class="catalog-reset">清除筛选</button></div><div><label class="catalog-shared"><input id="library-shared" type="checkbox">跨文献共享</label><select id="library-sort" aria-label="组分排序"><option value="recent">最近收录</option><option value="sources">文献数最多</option><option value="name">名称 A–Z</option></select></div></div><div id="library-update-note" aria-live="polite"></div><div id="library-scope"></div><div id="library-results" aria-live="polite"></div><div id="library-pagination" class="catalog-pagination"></div>';
 $('#jobs').innerHTML='';$('#library-search').value=libraryState.q;$('#library-sort').value=libraryState.sort;$('#library-view').value=libraryState.view;$('#library-shared').checked=libraryState.shared==='1';
 $('#library-search').oninput=()=>{libraryState.q=$('#library-search').value;libraryState.offset=0;clearTimeout(libraryTimer);libraryTimer=setTimeout(()=>loadLibrary().catch(showError),250)};
 for(const k of ['kind','sort','view'])$('#library-'+k).onchange=()=>{libraryState[k]=$('#library-'+k).value;libraryState.offset=0;loadLibrary().catch(showError)};
 $('#library-shared').onchange=()=>{libraryState.shared=$('#library-shared').checked?'1':'0';libraryState.offset=0;loadLibrary().catch(showError)};
 $('#library-reset').onclick=()=>{Object.assign(libraryState,{q:'',kind:'all',role:'all',group:'all',owner:'',offset:0,paperQuery:'',sort:'recent',view:'components',shared:'0'});libraryMounted=false;loadLibrary().catch(showError)};
 $('#component-passport').onclose=()=>{++libraryDialogSeq;++libraryFetchSeq;libraryPassport=null;librarySelectedRecord=null;clearTimeout(libraryPaneTimer);if(libraryRefreshPending)refreshLibrary().catch(showError)};
 libraryMounted=true;
}

function libraryCard(e){
 const labels=(e.source_labels||[e.label]).filter(x=>x!==e.name),groups=e.role_groups||[e.role_group];
 const categories=groups.map(x=>libraryGroups[x]).filter(Boolean);
 const binding=libraryState.view==='records'?' data-library-version="'+esc(e.version)+'" data-library-record="'+esc(e.id)+'"':'';
 return '<section class="catalog-card"><div class="catalog-card-top"><span>'+esc(e.identity_basis==='finite_graph'?'有限分子':'来源记录')+'</span><span title="'+esc(categories.join(' · '))+'">'+esc(categories.length>1?'多种文献角色':categories[0]||'其他组分')+'</span></div>'+
 '<button class="catalog-name" data-library-open="'+esc(e.identity_key)+'"'+binding+' aria-label="打开 '+esc(e.name||e.label)+' 的组分身份证"><strong>'+esc(e.name||e.label)+'</strong></button><p class="catalog-written" title="'+esc(labels.join('；'))+'">'+esc(labels.slice(0,3).join(' · ')||'文献名称与当前名称一致')+'</p><div class="catalog-formula">'+esc((e.formulas||[]).filter(Boolean).join(' / ')||'分子式未确定')+'</div>'+
 libraryNameCheckBadge(e.name_verification)+
 '<div class="catalog-card-footer"><button class="catalog-paper-count" data-library-sources="'+esc(e.identity_key)+'" aria-label="在身份证中查看 '+esc(e.name||e.label)+' 的来源文献">'+libraryIcon('paper')+'<strong>'+e.paper_count+'</strong><span>篇文献</span></button><span title="出现次数按已抽取组分记录计，非全文提及次数">'+e.occurrence_count+' 条记录</span><button class="catalog-open" data-library-open="'+esc(e.identity_key)+'"'+binding+' aria-label="查看 '+esc(e.name||e.label)+' 的身份详情">'+libraryIcon('identity')+'</button></div></section>';
}

async function loadLibrary(){
 clearTimeout(libraryTimer);const token=++generation;++libraryDetailGeneration;selected=null;bundle=null;
 if($('#component-passport').open)$('#component-passport').close();
 if(!libraryMounted)libraryShell();$('#status').textContent='正在读取组分库…';$('#library-results').setAttribute?.('aria-busy','true');
 const params=new URLSearchParams();for(const [k,v] of Object.entries(libraryState))if(k!=='paperQuery')params.set(k,v);params.set('compact','1');
 const r=await fetch('/api/library?'+params),data=await r.json();if(token!==generation)return;if(!r.ok)throw Error(data.error||'组分库读取失败');
 if(data.contract!=='component-library/4.0')throw Error('当前服务尚未加载新版组分身份证，请使用新版应用地址。');
 libraryData=data;libraryState.offset=data.offset;libraryRevision=data.revision||'';libraryRefreshPending=false;$('#library-update-note').textContent='';
 if(typeof history!=='undefined'){const url=new URLSearchParams();for(const k of ['q','kind','group','owner','sort','offset','view','shared'])if(libraryState[k]!==''&&libraryState[k]!=='all'&&libraryState[k]!=='recent'&&libraryState[k]!=='components'&&libraryState[k]!=='0'&&libraryState[k]!==0)url.set(k,libraryState[k]);history.replaceState(null,'',location.pathname+(url.size?'?'+url:''))}
 $('#library-summary').innerHTML='<div><strong>'+data.library_identity_total.toLocaleString()+'</strong><span>组分档案</span></div><div><strong>'+data.papers.length+'</strong><span>来源文献</span></div><div><strong>'+data.cross_paper_identity_total+'</strong><span>跨文献共享</span></div>';
 $('#library-result-count').textContent=data.total.toLocaleString()+' 项'+(libraryState.q?'搜索结果':'组分');
 $('#library-reset').hidden=!libraryState.q&&libraryState.kind==='all'&&libraryState.group==='all'&&!libraryState.owner&&libraryState.shared==='0';
 $('#library-kind').innerHTML='<option value="all">全部类型</option>'+Object.entries(data.kinds).map(([k,n])=>'<option value="'+esc(k)+'">'+esc(types[k]||k)+'</option>').join('');$('#library-kind').value=libraryState.kind;
 $('#library-groups').innerHTML=[['all','全部'],...Object.entries(libraryGroups)].filter(([k])=>k==='all'||data.groups?.[k]>0).map(([k,label])=>'<button data-library-group="'+k+'" aria-pressed="'+(libraryState.group===k)+'" class="'+(libraryState.group===k?'selected':'')+'">'+label+'</button>').join('');
 document.querySelectorAll('[data-library-group]').forEach(b=>b.onclick=()=>{libraryState.group=b.dataset.libraryGroup;libraryState.offset=0;loadLibrary().catch(showError)});
 const paper=data.papers.find(p=>p.job_id===libraryState.owner);
 $('#library-scope').innerHTML=paper?'<div class="catalog-source-filter">来源范围：'+esc(paper.title)+'<button id="library-clear-source">移除</button></div>':'';
 if($('#library-clear-source'))$('#library-clear-source').onclick=()=>{libraryState.owner='';libraryState.offset=0;loadLibrary().catch(showError)};
 $('#library-results').innerHTML=data.entries.length?'<div class="catalog-grid">'+data.entries.map(libraryCard).join('')+'</div>':'<div class="catalog-empty"><h2>没有找到匹配的组分</h2><p>试试其他名称、文献写法或分子式。</p></div>';
 const pages=Math.max(1,Math.ceil(data.total/data.limit)),current=Math.floor(data.offset/data.limit)+1;
 $('#library-pagination').innerHTML='<button id="library-prev" '+(current===1?'disabled':'')+'>← 上一页</button><span>'+current+' / '+pages+'</span><button id="library-next" '+(current===pages?'disabled':'')+'>下一页 →</button>';
 $('#library-prev').onclick=()=>{libraryState.offset=Math.max(0,data.offset-data.limit);loadLibrary().catch(showError)};$('#library-next').onclick=()=>{libraryState.offset=data.offset+data.limit;loadLibrary().catch(showError)};
 document.querySelectorAll('[data-library-open]').forEach(b=>b.onclick=()=>openLibraryPassport(b.dataset.libraryOpen,'identity',b.dataset.libraryVersion,b.dataset.libraryRecord).catch(libraryPaneError));
 document.querySelectorAll('[data-library-sources]').forEach(b=>b.onclick=()=>openLibraryPassport(b.dataset.librarySources,'sources').catch(libraryPaneError));
 $('#library-results').setAttribute?.('aria-busy','false');$('#status').textContent='';
}

async function refreshLibrary(){
 if(!libraryMounted||document.hidden)return;
 const view=generation,r=await fetch('/api/library-update-status'),data=await r.json();if(!r.ok||view!==generation||!isLibrary())return;
 const progress=document.querySelector('.tool-properties-intro>span');if(progress)progress.textContent=libraryCoverageText(data.coverage);
 if($('#component-passport').open&&libraryActiveTab==='identity'&&(libraryPropertyPending(libraryPassport?.tool_properties)||data.revision!==libraryRevision)){
  const seq=++libraryFetchSeq,dialog=libraryDialogSeq;
  const result=await fetch('/api/library-passport/'+encodeURIComponent(libraryActiveKey)),passport=await result.json();
  if(seq!==libraryFetchSeq||dialog!==libraryDialogSeq||view!==generation)return;
  if(result.ok&&$('#component-passport').open&&libraryActiveTab==='identity'){
   const changed=libraryPropertySignature(passport.tool_properties)!==libraryPropertySignature(libraryPassport.tool_properties)||passport.name_verification?.receipt_sha256!==libraryPassport.name_verification?.receipt_sha256;
   libraryPassport.tool_properties=passport.tool_properties;
   libraryPassport.name_verification=passport.name_verification;
   if(changed){
    const pane=$('#library-passport-content'),top=pane.scrollTop,expanded=Array.from(pane.querySelectorAll?.('details')||[]).map(d=>d.open);
    renderLibraryIdentity();Array.from(pane.querySelectorAll?.('details')||[]).forEach((d,i)=>{d.open=Boolean(expanded[i])});pane.scrollTop=top;
   }
  }
 }
 if(!data.revision||data.revision===libraryRevision)return;
 libraryRefreshPending=true;
 if($('#component-passport').open||document.activeElement?.id==='library-search'){
  $('#library-update-note').textContent='有新文献组分已入库，结束当前操作后自动更新列表。';return;
 }
 await loadLibrary();
}

function libraryPropertyPending(info){
 return Boolean(info&&((info.structures||[]).some(s=>['NOT_QUERIED','FAILED'].includes(s.status)||s.database.some(db=>['NOT_QUERIED','FAILED'].includes(db.annotation_status)))||
  info.name_lookup&&(!info.name_lookup.status||['NOT_QUERIED','FAILED'].includes(info.name_lookup.status)||(info.name_lookup.database||[]).some(db=>['NOT_QUERIED','FAILED'].includes(db.annotation_status)))));
}
function libraryPropertySignature(info){
 return JSON.stringify([(info?.structures||[]).map(s=>[s.graph_id,s.status,s.database.map(db=>[db.cid,db.annotation_status,db.annotations.length])]),
  info?.name_lookup?.status,(info?.name_lookup?.database||[]).map(db=>[db.cid,db.annotation_status,db.annotations.length])]);
}

function libraryCoverageText(coverage={}){
 if(coverage.status==='RUNNING'||coverage.status==='RATE_LIMITED')return 'PubChem '+(coverage.provider_wait||coverage.status==='RATE_LIMITED'?'等待服务限流重试':'全库检索中')+' · '+coverage.completed+' / '+coverage.query_total;
 if(coverage.status==='COMPLETED_WITH_FAILURES')return 'PubChem 全库已查询 · 部分请求待重试';
 if(coverage.status==='COMPLETED')return 'PubChem 全库检索已完成';
 return 'PubChem 查询状态随记录保存';
}

function libraryPassportFrame(e){
 $('#component-passport').innerHTML='<div class="passport-header"><div><p>组分身份证</p><h2 id="library-passport-title">'+esc(e.name||e.label)+'</h2><span>'+e.paper_count+' 篇文献 · '+e.occurrence_count+' 条来源记录</span></div><button id="close-library-passport" aria-label="关闭组分身份证">'+libraryIcon('close')+'</button></div><nav class="passport-tabs" role="tablist" aria-label="组分身份证章节"><button role="tab" data-passport-tab="identity">化学性质</button><button role="tab" data-passport-tab="sources">来源文献 <span>'+e.paper_count+'</span></button><button role="tab" data-passport-tab="associations">文献关联 <span>'+(e.association_count||0)+'</span></button>'+(librarySourceSelected?'<button role="tab" data-passport-tab="source-identity">来源身份</button>':'')+'</nav><div id="library-passport-content" class="passport-content" role="tabpanel"></div>';
 $('#close-library-passport').onclick=()=>$('#component-passport').close();
 document.querySelectorAll('[data-passport-tab]').forEach(b=>{
  b.onclick=()=>switchLibraryTab(b.dataset.passportTab).catch(libraryPaneError);
  b.onkeydown=event=>{const tabs=['identity','sources','associations',...(librarySourceSelected?['source-identity']:[])],i=tabs.indexOf(b.dataset.passportTab);let next;
   if(event.key==='ArrowRight')next=tabs[(i+1)%tabs.length];else if(event.key==='ArrowLeft')next=tabs[(i+tabs.length-1)%tabs.length];else if(event.key==='Home')next=tabs[0];else if(event.key==='End')next=tabs[tabs.length-1];else return;
   event.preventDefault();switchLibraryTab(next).catch(libraryPaneError);document.querySelector('[data-passport-tab="'+next+'"]').focus();
  };
 });
}
function libraryPaneError(error){$('#library-passport-content').innerHTML='<div class="catalog-empty">'+esc(error.message||error)+'</div>'}
async function openLibraryPassport(key,tab='identity',version,id){
 const seq=++libraryDialogSeq,view=generation;libraryActiveKey=key;libraryActiveTab=tab;libraryPassport=null;librarySelectedRecord=null;librarySourceSelected=false;librarySourceQuery='';libraryAssociationQuery='';libraryAssociationCategory='all';++libraryFetchSeq;
 const e=libraryData?.entries.find(x=>x.identity_key===key)||{label:'读取组分身份证…',paper_count:0,occurrence_count:0};libraryPassportFrame(e);
 $('#library-passport-content').innerHTML='<p class="passport-loading">正在读取身份与来源…</p>';if(!$('#component-passport').open)$('#component-passport').showModal();
 const r=await fetch('/api/library-passport/'+encodeURIComponent(key)),data=await r.json();if(seq!==libraryDialogSeq||view!==generation||!$('#component-passport').open)return;if(!r.ok){libraryPaneError(Error(data.error));return}
 libraryPassport=data;librarySelectedRecord=data;libraryPassportFrame(data.entry);
 if(tab==='identity'&&version&&id){
  if(data.entry.version!==version||data.entry.id!==id){await selectLibraryRecord(version,id);return}
  librarySourceSelected=true;libraryPassportFrame(data.entry);await switchLibraryTab('source-identity');return;
 }
 await switchLibraryTab(tab);
}
async function switchLibraryTab(tab,offset=0){
 if(!libraryPassport)return;const previous=libraryActiveTab;libraryActiveTab=tab;const seq=++libraryFetchSeq,dialog=libraryDialogSeq;
 document.querySelectorAll('[data-passport-tab]').forEach(b=>{b.setAttribute('aria-selected',b.dataset.passportTab===tab);b.tabIndex=b.dataset.passportTab===tab?0:-1});
 if(tab==='identity'){renderLibraryIdentity();return}
 if(tab==='source-identity'){renderLibrarySourceIdentity();return}
 const samePane=previous===tab&&!!document.querySelector('#passport-pane-search');
 if(!samePane)$('#library-passport-content').innerHTML='<p class="passport-loading">正在读取'+(tab==='sources'?'来源文献':'文献关联')+'…</p>';
 $('#library-passport-content').setAttribute('aria-busy','true');
 const params=new URLSearchParams({limit:12,offset,q:tab==='sources'?librarySourceQuery:libraryAssociationQuery});if(tab==='associations')params.set('category',libraryAssociationCategory);
 const r=await fetch('/api/library-'+tab+'/'+encodeURIComponent(libraryActiveKey)+'?'+params),v=await r.json();if(seq!==libraryFetchSeq||dialog!==libraryDialogSeq||!$('#component-passport').open)return;if(!r.ok){libraryPaneError(Error(v.error));return}
 const active=document.activeElement,editing=active?.id==='passport-pane-search',start=active?.selectionStart,end=active?.selectionEnd;
 if(tab==='sources')renderLibrarySources(v);else renderLibraryAssociations(v);
 $('#library-passport-content').setAttribute('aria-busy','false');$('#library-passport-content').scrollTop=0;
 if(editing){$('#passport-pane-search').focus();$('#passport-pane-search').setSelectionRange?.(start,end)}
}
function libraryToolLink(url,label){
 try{const parsed=new URL(url);if(!['http:','https:'].includes(parsed.protocol))return esc(label);return libraryExternal(esc(parsed.href),esc(label))}catch{return esc(label)}
}
function libraryPropertyTiles(properties){
 return '<dl class="tool-property-grid">'+properties.filter(p=>p.value!==null&&p.value!==undefined).map(p=>'<div><dt>'+esc(p.label)+'</dt><dd>'+esc(typeof p.value==='number'?Number(p.value.toPrecision(7)):p.value)+(p.unit?'<small>'+esc(p.unit)+'</small>':'')+'</dd></div>').join('')+'</dl>';
}
function libraryAnnotationRow(row){
 const ref=row.reference||{};
 const unitMissing=!row.unit&&['Boiling Point','Melting Point','Density','Solubility','Vapor Pressure','Flash Point','Autoignition Temperature','Viscosity'].includes(row.key)&&row.values.every(v=>/^[\s+\-\d.eE]+$/.test(v));
 return '<div class="tool-annotation-row">'+(row.name&&row.name!==row.key?'<p class="tool-annotation-description">'+esc(row.name)+'</p>':'')+'<p>'+row.values.map(esc).join('；')+(row.unit?' <span>'+esc(row.unit)+'</span>':'')+'</p>'+((row.description||unitMissing)?'<p class="tool-annotation-description">'+esc(row.description||'来源未标注单位')+'</p>':'')+'<small>'+libraryToolLink(ref.URL,ref.SourceName||ref.Name||'PubChem 汇编来源')+(ref.Name&&ref.Name!==ref.SourceName?' · '+esc(ref.Name):'')+'</small></div>';
}
function libraryAnnotationGroup(group){
 const seen=new Set(),visible=[],extra=[];
 for(const row of group.rows){const key=JSON.stringify([row.values,row.unit,row.name,row.description]);if(visible.length<2&&!seen.has(key)){visible.push(row);seen.add(key)}else extra.push(row)}
 return '<section class="tool-physical-property"><h4>'+esc(group.label)+'</h4>'+visible.map(libraryAnnotationRow).join('')+(extra.length?'<details><summary>其余 '+extra.length+' 条来源数据</summary>'+extra.map(libraryAnnotationRow).join('')+'</details>':'')+'</section>';
}
function libraryDatabaseProfile(db,status){
 const matched=status==='MATCHED'||status==='COMPUTED_ONLY',computedOnly=db.registered_record===false,notes=Object.values(db.annotations.filter(row=>row.values.some(v=>String(v).trim())).reduce((acc,row)=>{(acc[row.key]||= {label:row.label,key:row.key,rows:[]}).rows.push(row);return acc},{}));
 const order=['Boiling Point','Melting Point','Density','Solubility','Vapor Pressure','Flash Point','Autoignition Temperature','Viscosity','Refractive Index','Dissociation Constants','LogP','Decomposition','Physical Description','GHS Classification'];
 const physical=notes.filter(g=>!['CAS','IUPAC Name','Depositor-Supplied Synonyms'].includes(g.key)).sort((a,b)=>order.indexOf(a.key)-order.indexOf(b.key));
 const identifiers=notes.filter(g=>['CAS','Depositor-Supplied Synonyms'].includes(g.key));
 return '<section class="tool-database"><div class="tool-section-heading"><h3>PubChem'+(computedOnly?' 在线结构计算':'')+'</h3>'+(computedOnly?'<span>无登记 CID</span>':libraryToolLink(db.url,'CID '+db.cid))+'</div><p class="tool-method-note">'+esc(computedOnly?(matched?'PubChem 从输入结构返回的计算资料，未关联到登记化合物。':'PubChem 返回的结构计算候选；结构未确认一致，未关联到登记化合物。'):matched?'数据库结构与已保存的有限分子图一致。':'以下是查询候选资料；结构未确认一致，不作为本组分的确定性质。')+'<span>获取时间 '+esc((db.retrieved_at||'').replace('T',' ').slice(0,19))+' UTC</span></p>'+
 '<div class="tool-database-name"><span>PubChem IUPAC 名称</span><strong>'+esc(db.iupac_name||'未返回名称')+'</strong></div>'+libraryPropertyTiles(db.properties.slice(0,9))+(db.properties.length>9?'<details class="tool-more-properties"><summary>更多数据库计算性质（'+(db.properties.length-9)+' 项）</summary>'+libraryPropertyTiles(db.properties.slice(9))+'</details>':'')+
 '<details class="tool-identifiers"><summary>结构编码、CAS 与数据库名称</summary><dl><dt>InChIKey</dt><dd>'+esc(db.inchikey||'未返回')+'</dd><dt>SMILES</dt><dd>'+esc(db.smiles||'未返回')+'</dd><dt>InChI</dt><dd>'+esc(db.inchi||'未返回')+'</dd></dl>'+identifiers.map(g=>'<h4>'+esc(g.label)+'</h4>'+g.rows.map(libraryAnnotationRow).join('')).join('')+'</details>'+
 (computedOnly?'<p class="tool-empty">没有对应的登记记录，未关联物性汇编。</p>':'<div class="tool-section-heading tool-physical-heading"><h3>物性与参考来源</h3><span>PubChem 汇编注释</span></div><p class="tool-method-note">温度、压力、溶剂和测量或预测说明按数据库原文保留；不同来源的值分别列出。</p>')+
 (computedOnly?'':physical.length?physical.map(libraryAnnotationGroup).join(''):'<p class="tool-empty">'+esc(db.annotation_status==='OK'?'该数据库记录没有收录所需物性。':db.annotation_status==='NOT_QUERIED'?'物性资料等待查询。':'物性资料尚未成功获取，查询状态与回执已保存。')+'</p>')+'</section>';
}
function renderLibraryIdentity(){
 const info=libraryPassport.tool_properties,graphs=libraryPassport.graphs||{};
 if(!info){$('#library-passport-content').innerHTML='<p class="tool-empty">当前服务尚未加载工具性质接口，请打开新版应用地址。</p>';return}
 const coverage=info.coverage||{};
 $('#library-passport-content').innerHTML='<div class="tool-properties-intro"><p>结构计算与数据库资料</p><span>'+esc(libraryCoverageText(coverage))+'</span></div>'+
 libraryNameCheckPanel(libraryPassport.name_verification)+info.structures.map(s=>{
  const g=graphs[s.graph_id]||{},local=s.local||{},finite=s.scope==='finite_molecule';
  const primary=['formula','molar_mass','exact_mass','formal_charge','logp','tpsa','hbd','hba','rotatable_bonds','rings','heavy_atoms','isotope_atoms'];
  const props=(local.properties||[]).filter(p=>primary.includes(p.key)).sort((a,b)=>primary.indexOf(a.key)-primary.indexOf(b.key));
  return '<section class="tool-structure-section"><div class="tool-structure-summary">'+(g.depiction?.image?'<img src="'+esc(g.depiction.image)+'" alt="已保存的组分结构" data-passport-zoom>':'')+'<div><span class="passport-section-label">'+esc(finite?'有限分子结构':'保存图的局部范围')+'</span><h3>'+esc(graphFormula(g)||'结构未确定')+'</h3><p>'+esc(scopes[s.scope]||s.scope)+'</p><span class="tool-lookup-status '+(s.status==='MATCHED'?'matched':'')+'">PubChem · '+esc(s.status_label)+'</span></div></div>'+
 '<div class="tool-section-heading"><h3>本地结构计算</h3><span>'+esc(local.method||'RDKit')+'</span></div>'+(!finite?'<p class="tool-scope-notice">以下只适用于保存的单元或局部图；单元质量不作为聚合物 Mn/Mw，局部图不赋予完整材料物性。</p>':'<p class="tool-method-note">从已保存的有限结构计算；LogP、极性表面积等是计算值。</p>')+libraryPropertyTiles(props.slice(0,9))+(props.length>9?'<details class="tool-more-properties"><summary>更多结构计算（'+(props.length-9)+' 项）</summary>'+libraryPropertyTiles(props.slice(9))+'</details>':'')+
 ((local.functional_groups||[]).length?'<div class="tool-functional-groups"><span>官能团图匹配</span>'+local.functional_groups.map(f=>'<span>'+esc(f.label)+' × '+f.count+'</span>').join('')+'</div>':'')+
 (['MATCHED','COMPUTED_ONLY'].includes(s.status)?s.database.map(db=>libraryDatabaseProfile(db,s.status)).join(''):s.database.length?'<details class="tool-unmatched"><summary>查看数据库候选（结构尚未匹配）</summary>'+s.database.map(db=>libraryDatabaseProfile(db,s.status)).join('')+'</details>':'')+(!s.database.length?'<p class="tool-empty">'+esc(s.status_label)+(s.lookup.error?' · '+esc(s.lookup.error):'')+'</p>':'')+'</section>';
 }).join('')+
 (!info.structures.length?'<div class="tool-empty"><h3>尚无确定的有限结构</h3><p>此记录的来源定义见“来源文献”。</p></div>':'')+
 (info.name_lookup?'<section class="tool-name-only"><p class="tool-scope-notice">名称检索资料：当前缺少可核对的有限结构，结果作为候选单独保留。</p>'+info.name_lookup.database.map(db=>libraryDatabaseProfile(db,info.name_lookup.status)).join('')+(!info.name_lookup.database.length?'<p class="tool-empty">'+esc(info.name_lookup.status||'等待名称查询')+'</p>':'')+'</section>':'');
 document.querySelectorAll('[data-passport-zoom]').forEach(img=>img.onclick=()=>{$('#zoom-img').src=img.src;$('#zoom').showModal()});
}
function renderLibrarySourceIdentity(){
 const v=librarySelectedRecord,e=v.entry,m=v.material,name=m.most_likely_name||{},graphs=Object.values(v.graphs||{}),summary=libraryPassport.entry;
 const sourceLabels=[e.label];
 $('#library-passport-content').innerHTML='<div class="passport-identity-layout"><div class="passport-structure">'+graphs.map(g=>'<figure>'+(g.depiction?.image?'<img src="'+esc(g.depiction.image)+'" alt="'+esc(e.label)+' 的已保存结构" data-passport-zoom>':'<p>此来源未保存结构图</p>')+'<figcaption>'+esc(graphFormula(g)||'')+'<span>'+esc(scopes[g.scope]||g.scope)+'</span></figcaption></figure>').join('')+(!graphs.length?'<div class="passport-structure-empty">结构未确定<p>来源中的假设与未知信息保留在下方。</p></div>':'')+'</div><div class="passport-name-info"><span class="passport-section-label">最可能名称</span><h3>'+esc(name.text||e.label)+'</h3><p>'+esc(words[name.basis]||name.basis||'名称依据未记录')+' · '+esc(checks[e.name_check]||e.name_check||'未执行名称核对')+'</p><dl><div><dt>文献写法</dt><dd>'+esc(sourceLabels.slice(0,6).join('；'))+(sourceLabels.length>6?'<details><summary>其余 '+(sourceLabels.length-6)+' 种写法</summary>'+esc(sourceLabels.slice(6).join('；'))+'</details>':'')+'</dd></div><div><dt>汇总范围</dt><dd>'+esc(summary.identity_basis==='finite_graph'?'相同的已保存有限结构；各篇的纯度、相态与未知信息分别保留。':'按本篇来源记录保留，尚未跨文献合并。')+'</dd></div></dl><button id="passport-see-sources" class="passport-text-button">查看 '+summary.paper_count+' 篇来源文献 →</button></div></div>'+
 '<section class="passport-record-context"><div><span class="passport-section-label">当前身份说明来自</span><p>'+esc(e.source_title)+'</p><small>原文名称：'+esc(e.label)+' · '+esc(libraryRole(e.role))+'</small></div>'+libraryExternal(libraryLink(e),'在文献中查看','passport-paper-link')+'</section><div class="passport-evidence"><h3>命名依据与保留信息</h3><p>'+esc(name.reason||m.description||'命名依据见此来源的完整身份证。')+'</p><details><summary>假设、未知与原记录写法</summary>'+records(m.assumptions||[])+records(name.assumptions||[])+records(m.unknowns||[])+records(name.unknowns||[])+records(e.aliases||[])+'</details><p class="passport-review-note">'+esc(v.independent_review==='NOT_REVIEWED'?'独立化学审核尚未完成。':'审核状态按原记录保留。')+'</p></div>';
 $('#library-passport-content').insertAdjacentHTML('afterbegin',libraryNameCheckPanel(v.name_verification));
 $('#passport-see-sources').onclick=()=>switchLibraryTab('sources').catch(libraryPaneError);
 document.querySelectorAll('[data-passport-zoom]').forEach(img=>img.onclick=()=>{$('#zoom-img').src=img.src;$('#zoom').showModal()});
}
function libraryPaneSearch(tab){
 const source=tab==='sources';return '<div class="passport-pane-search">'+libraryIcon('search')+'<input id="passport-pane-search" type="search" aria-label="'+(source?'搜索此组分的来源文献':'搜索关联对象')+'" placeholder="'+(source?'搜索文献标题或原文写法':'搜索关联对象或文献标题')+'" value="'+esc(source?librarySourceQuery:libraryAssociationQuery)+'"></div>';
}
function bindLibraryPaneSearch(tab){
 $('#passport-pane-search').oninput=()=>{if(tab==='sources')librarySourceQuery=$('#passport-pane-search').value;else libraryAssociationQuery=$('#passport-pane-search').value;clearTimeout(libraryPaneTimer);++libraryFetchSeq;libraryPaneTimer=setTimeout(()=>switchLibraryTab(tab).catch(libraryPaneError),250)};
}
function libraryPanePagination(tab,offset,limit,total){
 const current=Math.floor(offset/limit)+1,pages=Math.max(1,Math.ceil(total/limit));
 return '<div class="passport-pagination"><button id="passport-pane-prev" '+(current===1?'disabled':'')+'>← 上一页</button><span>'+current+' / '+pages+'</span><button id="passport-pane-next" '+(current===pages?'disabled':'')+'>下一页 →</button></div>';
}
function bindLibraryPanePagination(tab,v){$('#passport-pane-prev').onclick=()=>switchLibraryTab(tab,Math.max(0,v.offset-v.limit)).catch(libraryPaneError);$('#passport-pane-next').onclick=()=>switchLibraryTab(tab,v.offset+v.limit).catch(libraryPaneError)}
function renderLibrarySources(v){
 const counts=librarySourceQuery?'匹配 '+v.matched_paper_count+' 篇文献；该组分共 '+v.paper_count+' 篇来源、'+v.occurrence_count+' 条记录。':v.paper_count+' 篇来源 · '+v.occurrence_count+' 条记录。';
 $('#library-passport-content').innerHTML=libraryPaneSearch('sources')+'<p class="passport-pane-caption">'+counts+'每篇保留自己的原文角色与身份说明。</p><div class="passport-source-list">'+v.papers.map(p=>'<article><div class="passport-source-title">'+libraryIcon('paper')+'<h3>'+libraryExternal('/paper/'+encodeURIComponent(p.job_id),esc(p.title))+'</h3><span>'+p.entries.length+' 条记录</span></div>'+p.entries.map(e=>'<div class="passport-source-record"><div><strong>'+esc(e.label)+'</strong><span title="'+esc(e.role||'')+'">'+esc(libraryRole(e.role))+'</span></div><button data-passport-record="'+esc(e.id)+'" data-passport-version="'+esc(p.version)+'">查看此条身份</button>'+libraryExternal(libraryLink(p,e.id),'在文献中定位')+'</div>').join('')+'</article>').join('')+(!v.papers.length?'<div class="catalog-empty">没有匹配的来源文献。</div>':'')+'</div>'+libraryPanePagination('sources',v.offset,v.limit,v.matched_paper_count);
 bindLibraryPaneSearch('sources');bindLibraryPanePagination('sources',v);
 document.querySelectorAll('[data-passport-record]').forEach(b=>b.onclick=()=>selectLibraryRecord(b.dataset.passportVersion,b.dataset.passportRecord).catch(libraryPaneError));
}
async function selectLibraryRecord(version,id){
 const seq=++libraryFetchSeq,dialog=libraryDialogSeq;const r=await fetch('/api/library-entry/'+encodeURIComponent(version)+'/'+encodeURIComponent(id)),v=await r.json();if(seq!==libraryFetchSeq||dialog!==libraryDialogSeq||!$('#component-passport').open)return;if(!r.ok)throw Error(v.error);librarySelectedRecord=v;librarySourceSelected=true;libraryPassportFrame(libraryPassport.entry);await switchLibraryTab('source-identity');
}
function renderLibraryAssociations(v){
 $('#library-passport-content').innerHTML=libraryPaneSearch('associations')+'<p class="passport-pane-caption">按文献中的显式关系列出关联对象。前体、工艺辅助和命名来源各自保留，不作为产物组成计数。</p><div class="passport-association-filters">'+[['all','全部关联',v.association_count],...Object.entries(libraryAssociationLabels).map(([k,label])=>[k,label,v.categories[k]||0])].filter(([k,label,n])=>k==='all'||n>0).map(([k,label,n])=>'<button data-association-category="'+k+'" aria-pressed="'+(k===libraryAssociationCategory)+'">'+label+' <span>'+n+'</span></button>').join('')+'</div><div class="passport-association-list">'+v.entries.map(e=>'<article><div class="passport-association-title"><div><span>'+esc(types[e.kind]||e.kind)+'</span><h3>'+esc(e.label)+'</h3></div>'+libraryExternal(libraryLink(e),'在文献中查看')+'</div><div class="passport-relation-tags">'+[...new Set(e.links.map(x=>x.category))].map(k=>'<span>'+libraryAssociationLabels[k]+'</span>').join('')+'</div><p class="passport-origin-title">'+esc(e.source_title)+'</p><details><summary>查看关联依据（'+e.links.length+' 条）</summary>'+e.links.map(x=>'<div class="passport-relation-evidence"><strong>'+esc(x.source_label)+'</strong> · '+esc(libraryRole(x.role||x.relation))+(x.relation&&x.role&&x.role!==x.relation?'<p>关系：'+esc(libraryRole(x.relation))+'</p>':'')+'<p>'+esc(x.reason||'文献未补充这条关联的说明。')+'</p><small>'+esc(x.source_refs.join(' · ')||'依据随该篇身份证保留')+(x.direction?' · '+esc(x.direction==='incoming'?'原关系指向当前组分':'原关系由当前组分出发'):'')+'</small></div>').join('')+'</details></article>').join('')+(!v.entries.length?'<div class="catalog-empty">此范围未保存明确的对象关联。</div>':'')+'</div>'+libraryPanePagination('associations',v.offset,v.limit,v.total);
 bindLibraryPaneSearch('associations');bindLibraryPanePagination('associations',v);
 document.querySelectorAll('[data-association-category]').forEach(b=>b.onclick=()=>{libraryAssociationCategory=b.dataset.associationCategory;switchLibraryTab('associations').catch(libraryPaneError)});
}
