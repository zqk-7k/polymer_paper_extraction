'use strict';
const $=s=>document.querySelector(s), esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let selected=null,bundle=null,member=null,evaluation=null,generation=0;
let selectedSeries=null;
const rememberedSamples=new Map(),readerFilters={query:'',kind:'major',role:'all'};
const directoryVersions=new Map();
let refreshPending=null,directorySignature='';
const libraryState={q:'',kind:'all',role:'all',group:'all',owner:'',offset:0,limit:24,paperQuery:'',sort:'recent',view:'components',shared:'0'};
let libraryData=null,libraryMounted=false,libraryTimer=null,libraryDetailGeneration=0,libraryPaperLimit=12;
const taskLabels={QUEUED:'排队等待',CHECKING_RUNTIME:'检查生成服务',PREPARING_SOURCE:'准备来源',UNDERSTANDING_AND_BUILDING:'解析描述、建图与命名',DELIVERED:'已完成',INCOMPLETE:'未完成',ENGINEERING_FAILED:'生成服务异常',STOPPED:'已停止'};
const activeStatuses=['QUEUED','CHECKING_RUNTIME','PREPARING_SOURCE','UNDERSTANDING_AND_BUILDING'];
const isLibrary=()=>['/knowledge','/library'].includes(location.pathname);
const isWorkbench=()=>location.pathname==='/';
let rawValues=[];
// Prepared outside the frozen app; insert only after all fifteen attempts seal.
let postsealNotes=null;
function modelReviewSummary(c,b=bundle){
 const major=Object.values(c.materials||{}).filter(m=>m.major),recorded=major.filter(m=>m.review?.reason&&/^[a-f0-9]{64}$/.test(m.review.state_sha256||''));
 const draft=b?.display_state==='SAVED_DRAFT';
 return {total:major.length,recorded:recorded.length,
  text:draft?'候选尚未完成当前状态复核':!major.length?'暂无主要对象复核记录':recorded.length===major.length?'已完成（同会话模型及工具，'+major.length+' 个主要对象）':recorded.length?'已保存 '+recorded.length+'/'+major.length+' 个主要对象的复核记录':'未保存模型复核记录',
  complete:!draft&&major.length>0&&recorded.length===major.length};
}
function reviewStatusMarkup(c,b=bundle){
 const status=modelReviewSummary(c,b);
 return '<div class="model-review-status"><p><strong>模型化学复核：'+esc(status.text)+'</strong></p></div>';
}
function numericDisplay(v){
 if(!Number.isFinite(v))return v;
 const nearest=Math.round(v),tail=Math.abs(v-nearest);
 return nearest!==0&&Number.isSafeInteger(nearest)&&tail>0&&tail<=1e-9&&tail<=2*Number.EPSILON*Math.max(1,Math.abs(v))?nearest:v;
}
function postsealNoteMarkup(){
 if(!postsealNotes||postsealNotes.version!==bundle?.version)return '';
 const notes=postsealNotes.notes||[],issues=postsealNotes.binding_issues||[];
 if(!notes.length&&!issues.length)return '';
 return '<aside class="postseal-source-notes"><p><strong>封存后原文有限核对</strong> · 同一模型系统的有限阅读，核对结论与保留问题见下方说明</p>'+notes.map(n=>'<p>'+esc(n.notice)+'</p><details><summary>阅读与本版本绑定的原文核对说明</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+esc(n.text)+'</pre></details>'+(n.manual_text?'<details><summary>封存后人工JSON有限回读说明</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+esc(n.manual_text)+'</pre></details>':'')).join('')+(issues.length?'<p>核对说明未通过版本绑定检查，暂无法读取。</p><details><summary>绑定检查信息</summary><pre>'+esc(JSON.stringify(issues,null,2))+'</pre></details>':'')+'</aside>';
}
async function loadPostsealNotes(version,token,id){
 if(!/^[a-f0-9]{64}$/.test(version))return;
 const current=()=>token===generation&&id===selected&&version===bundle?.version;
 try{
  const response=await fetch('/api/source-review-notes/'+encodeURIComponent(version));
  const result=await response.json();if(!current())return;
  if(!response.ok)throw Error(result.error||'核对说明读取失败');
  if(result.contract!=='identity-postseal-reader-notes/1.0'||result.version!==version||result.job_id!==id||!Array.isArray(result.notes)||!Array.isArray(result.binding_issues)||result.notes.some(n=>typeof n.notice!=='string'||typeof n.text!=='string'||n.manual_text!=null&&typeof n.manual_text!=='string'))throw Error('核对说明版本绑定不一致');
  postsealNotes=result;
 }catch(e){if(!current())return;postsealNotes={version,notes:[],binding_issues:[{error:e.message}]}}
 const container=$('#postseal-note-container');if(container&&current())container.innerHTML=postsealNoteMarkup();
}

function completedResult(b){return Boolean(Object.keys(b?.candidate?.materials||{}).length&&b.version&&b.display_state!=='SAVED_DRAFT'&&!b.validation_errors?.length&&!b.errors?.length)}
const types={polymer:'聚合物',prepolymer:'预聚物',oligomer:'低聚物',monomer:'单体',component:'组分',blend:'共混材料',network:'网络材料',series:'材料系列'};
const scopes={repeat_unit:'重复单元候选',constitutional_unit:'构成单元候选',local_network:'局部网络候选',end_group:'端段候选',finite_molecule:'有限分子候选',component:'组分候选',oligomer:'低聚片段候选',residue:'反应残基候选'};
const labels={role:'使用角色',name:'名称',description:'说明',fact:'来源事实',basis:'依据／基准',scope:'适用范围',reason:'选择理由',synthesis:'合成依据',procedure:'制备说明',process:'过程',label:'原文代称',specimen_states:'样品状态',source_refs:'原文依据',components:'组分',material_id:'关联材料',material_ids:'关联材料',from_material_id:'起始材料',to_material_id:'产物材料',graph_id:'对应结构',graph_relation:'结构关系',relation:'关系',type:'关系类别',ratio:'组成比',values:'数值',as_reported:'原文值',reported_part:'原文份数',reported_value:'原文值',unit:'单位',value:'数值',amount:'用量',formula_scope:'公式范围',phase_relation:'相关系',temperature_C:'温度 / °C',time_min:'时间 / min',time_h:'时间 / h',rotor_speed_rpm:'转速 / rpm',apparatus:'设备',compression_molding:'压片条件',plaque_thickness_mm:'片厚 / mm',mass_fraction:'质量分数',mole_fraction:'摩尔分数',graft_content:'接枝含量',grafting_degree:'接枝程度',silicon_substituents:'硅取代基',p_tolyl_groups_per_Si:'每个硅的对甲苯基数',aryl_group_count_ratio_Ph_to_pTol:'苯基与对甲苯基数比',chemical_unit_formula_computed:'计算构成单元式',occurrence:'出现范围',is_separate_blend_component:'是否为独立共混组分',sequence:'序列',connection:'连接',topology:'拓扑',supplier:'供应方',trade_name:'商品名',molar_mass:'身份相关分子量',average_type:'平均方式',graph_scope_note:'结构图范围',notes:'说明',note:'说明',statement:'陈述',conflict:'来源冲突',uncertainty:'不确定性',status:'来源状态'};
const words={source_confirmed:'主模型声明原文确认',main_material:'研究主体',main_product:'研究主体',synthesized_feedstock:'合成原料',isolated_cyclic_byproduct:'环状副产物',starting_polymer_and_control:'起始聚合物与对照',blend_component:'共混组分',source_based:'来源型命名',structure_based:'结构型命名',material_expression:'材料组分命名表达',physical_blend_component:'物理共混组分',noncovalent_material_blend:'非共价材料共混',not_explicitly_specified:'原文未明确',series_members:'同一研究系列的成员',depicted_monomer_to_polymer:'原图中的单体与聚合物关系',covalent_constitutional_unit:'共价构成单元',viscosity_average:'黏均',PP_phase:'聚丙烯相',elastomer_phase:'弹性体相'};
Object.assign(labels,{Mn_g_per_mol:'数均分子量 Mn / g·mol⁻¹',Mw_over_Mn:'分散系数 Đ',method:'方法',calibration:'校准',solvent:'溶剂',value_g_per_mol:'数值 / g·mol⁻¹',source_facts:'来源事实',crystalline_identity:'晶体构成依据',sensitizer_conditions:'身份相关敏化条件',tool_calculations:'局部图计算',constitutional_residue:'构成残基',backbone_bridge:'骨架桥',temperature:'温度',duration:'持续时间',identity:'组分身份',molecular_weight_distribution:'分子量分布',formula:'分子式',formal_charge:'总形式电荷',component_key:'组分引用',identity_properties:'身份相关性质'});
Object.assign(words,{solvent:'溶剂',initiator:'引发剂',base:'碱',reactant:'反应投料',bridge_feed:'桥接投料',inhibitor:'阻聚剂',recrystallization_solvent:'重结晶溶剂',polymerized_monomer_source:'聚合单体来源',single_monomer_homopolymer:'单一单体的均聚物'});
Object.assign(labels,{source_molecule_material_id:'有限前体',conditional_graph_id:'有条件局部图',candidate_graphs:'候选图集合',occurrence_basis:'出现次数基准',graft_role:'接枝身份角色',covalent_incorporation:'共价并入范围',graph_applicability:'局部图适用条件',regioisomer:'区域异构身份',from:'起始材料',to:'关联材料',end_groups:'端基',dispersity:'分散系数 Đ',degree_of_polymerization:'聚合度',comonomer_ratio:'共聚单体比',repeat_formula_excluding_ports:'不计端口的单元式',repeat_formula_status:'单元式范围',repeat_graph_id:'重复构成图',source_value:'来源数值',monomer:'来源单体',initiator:'引发剂',duration_h:'时间 / h'});
Object.assign(words,{precursor:'前体',base_polymer_identity:'基础聚合物身份',sample_state_of:'样品身份限定',PP_backbone_precursor:'PP 骨架前体',covalently_incorporated_functionality:'共价并入的功能组分',source_assigned_graft_functionality:'来源指认的接枝功能组分',nomenclature_source:'命名来源组分'});
Object.assign(words,{reported_source_and_identity_qualifiers:'来源及已报告的身份限定'});
Object.assign(labels,{text:'限定说明',raw_name:'原文名称',full_name:'工具全名／系统重述',aliases:'来源别名',origin:'展开依据',prepared_query:'实际查询名称',identity_preparations:'组分名称准备',registry_candidates:'已有库候选',hypotheses:'命名假设',statement:'假设／陈述'});
Object.assign(words,{material_description_with_explicit_component_scope:'材料描述与明确的组分范围',not_certified:'候选名称'});
Object.assign(labels,{pp_rule_candidate:'PP 骨架规则名候选',source_monomer_name:'来源单体名称',dmi_local_deterministic_name:'DMI 局部规则命名'});
const checks={GRAPH_MATCH:'编码结构一致',SOURCE_DESCRIPTOR_MATCH:'来源描述一致',MISMATCH:'名称与图不一致',UNSUPPORTED:'当前校验不支持',NOT_APPLICABLE:'不适用完整化学名校验',NOT_RUN:'未执行',PARSED:'已解析',CANDIDATE:'候选',DEFERRED:'暂未执行',UNAVAILABLE:'工具不可用',TOOL_FAILED:'调用失败',NO_NAME:'尚无规则名称',GRAPH_READABLE:'图可读'};
Object.assign(checks,{NEEDS_DETAILS:'待补充信息',AMBIGUOUS:'候选存在歧义',INVALID:'输入无效',IUPAC_AT_DECLARED_SCOPE:'规则支持当前声明范围'});
Object.assign(checks,{SOURCE_SCOPE_MATCH:'来源命名范围一致'});

Object.assign(words,{monomer:'单体',intermediate:'中间体',main_material_variant:'主要材料变体',reagent:'试剂',acylating_reagent:'酰化试剂',polymerization_inhibitor:'阻聚剂',neutralization_reagent:'中和试剂',drying_agent:'干燥剂',nmr_solvent:'NMR 溶剂',gpc_eluent:'GPC 流动相',solubility_test_solvent:'溶解性测试溶剂',nmr_reference:'NMR 标准',photosensitizer:'光敏化剂',inert_gas:'惰性气体',extraction_solvent:'萃取溶剂',filtered_byproduct:'过滤副产物',systematic_reexpression:'依据原文作系统名称重述',source_definition:'原文明确定义',source_context:'原文上下文展开',declared_synonym:'明确的同义名称',source_printed_conflict:'原文印刷数值存在冲突，尚未确认修正'});
Object.assign(labels,{raw_value:'原始报告值',conditions:'测量或使用条件',elements:'元素',found:'实测',calculated_source:'作者计算',assumptions:'假设',unknowns:'保留未知',melting_point:'熔点',elemental_analysis:'元素分析',weight_average_molar_mass:'重均分子量 Mw',number_average_molar_mass:'数均分子量 Mn',glass_transition_temperature:'玻璃化转变温度',polymer_type:'聚合物类型',feed_concentration:'投料浓度',initiator_loading:'引发剂用量',product_composition:'产物组成',isolated_yield_reports:'分离产率报告',purpose:'来源用途',polymerization:'聚合方法',atmosphere:'气氛',isolation:'分离与纯化',evidence_basis:'证据基准',selection_reason:'选择依据'});
Object.assign(words,{melting_point:'熔点',elemental_analysis:'元素分析',weight_average_molar_mass:'重均分子量 Mw',number_average_molar_mass:'数均分子量 Mn',dispersity:'分散系数 Đ',glass_transition_temperature:'玻璃化转变温度',source_supported:'原文支持',broader_scope:'采用较宽命名范围',most_likely_hypothesis:'最可能假设'});
Object.assign(labels,{grafting_content:'实际接枝含量',initial_feed:'初始投料',unit_distribution:'接枝单元与支链分布',monoester_anhydride_ratio:'单酯与酸酐比例',viscosity_average_molar_mass:'黏均分子量 Mv'});
Object.assign(words,{viscosity_average_molar_mass:'黏均分子量 Mv'});
Object.assign(words,{condensation_monomer:'缩聚单体',difunctional_bridge_feed:'双官能桥接原料',deprotonating_base:'脱质子碱',polycondensation_solvent:'缩聚溶剂',recrystallization_and_polycondensation_solvent:'重结晶与缩聚溶剂',purification_and_GPC_solvent:'纯化与 GPC 溶剂',monomer_synthesis_and_precipitation_solvent:'单体合成与沉淀溶剂',guanamine_precursor:'胍胺前体',monomer_synthesis_reagent:'单体合成试剂',monomer_synthesis_solvent:'单体合成溶剂',monomer_synthesis_and_assay_base:'单体合成与测定用碱',aqueous_solvent:'水相溶剂',recrystallization_solvent:'重结晶溶剂',model_NMR_solvent:'模型化合物 NMR 溶剂',polymer_NMR_solvent:'聚合物 NMR 溶剂',impurity_NMR_solvent:'副产物 NMR 溶剂'});
function scopeLabel(m){
 const a=m.iupac_assessment||{},s=m.most_likely_name?.scope||'';
 if(s==='polymer_matrix')return '主名对应聚合物基体；物理配方及各组分名称另列';
 if(['component','monomer'].includes(m.kind))return '当前有限组分身份范围；歧义与实物证据另列';
 if(isWorkbench()&&bundle?.source_index?.page_count===0&&s==='structure_polymer')return a.hypotheses?.length?'明确假设下的理想重复构成；输入未确定的信息另列':'输入描述支持的理想重复构成；端基与实物状态另列';
 if(a.status==='STRUCTURE_NAME_SUPPORTED')return a.hypotheses?.length?'明确假设下的理想重复构成；样品状态另列':'理想重复构成；实物微结构与样品状态另列';
 if(a.status==='MODIFIED_NAME_SUPPORTED')return '点改性家族；位点与分布按来源限定';
 if(a.status==='GRAFT_NAME_SUPPORTED')return '来源型骨架和聚合侧链；位点与链长未确定';
 if(a.status==='HYPOTHESIS_NAME_SUPPORTED')return '明确假设选定的有限身份；其他候选保留';
 if(m.kind==='blend'&&a.formal_name)return '组分身份与共混关系；比例基准另列';
 if(a.evidence_basis==='broader_scope')return '较宽的来源组成范围；完整连接拓扑未确定';
 if(a.hypotheses?.length)return '明确假设下的来源及连接范围';
 if(a.formal_name)return '来源及已报告的身份限定';
 return words[s]||(/[a-z]_[a-z]/i.test(s)?'声明的候选范围；详见命名依据':s);
}
function materialOverview(c,major,buttons,chapters){
 const perMember=key=>major.map(x=>'<details><summary>'+esc(x.label)+'</summary>'+(key==='components'?componentSummaries(x)+display(x.composition||{})+records(x.components||[]):display(x[key]||'此项按该成员的来源证据保留'))+'</details>').join('');
 const rows=major.map(x=>'<tr><td>'+related(x.id)+'</td><td>'+esc(x.most_likely_name?.text||'名称尚未确定')+(x.iupac_assessment?.hypotheses?.length?'<p class="scope-note">基于明确假设</p>':'')+'</td><td>'+esc((x.graph_ids||[]).map(id=>scopes[c.graphs?.[id]?.scope]||'已保存结构').join('、'))+'</td><td>'+esc(checks[x.naming_verification?.status]||x.naming_verification?.status||'未执行')+'</td></tr>').join('');
 return '<div class="reader-actions"><a href="#review-record">在工作台核对</a></div><nav class="chapter-anchors" aria-label="身份证章节定位">'+chapters.map(([id,label],i)=>'<a class="'+(!i?'active':'')+'" href="#'+id+'">'+label+'</a>').join('')+'</nav><section id="identity"><p class="eyebrow">聚合物来源定义</p><h2 class="identity-title">本文概览</h2><p>'+esc(c.overview||'')+'</p><p class="scope-note">各成员的图、用量和名称证据分别保存。选择成员可阅读完整身份证。</p><div class="overview-table"><table><thead><tr><th>原文材料</th><th>当前化学名称</th><th>结构范围</th><th>名称校验</th></tr></thead><tbody>'+rows+'</tbody></table></div></section>'+section('组成与组分',perMember('components'),'components')+section('材料与样品',records(c.relations||[]),'materials')+section('制备与变化',perMember('preparation'),'preparation')+section('身份与组分性质',major.map(x=>'<details><summary>'+esc(x.label)+'</summary>'+identityProperties(x)+'</details>').join(''),'properties')+section('关联与证据',records(c.source_facts||[]),'evidence')+'<details id="review-record"><summary>当前成员核对记录</summary>'+major.map(x=>'<details><summary>'+esc(x.label)+'</summary>'+raw(x.review)+'</details>').join('')+'</details>'+versionHistory();
}

const technical=new Set(['id','independent_review','preferred_iupac_name','preferred_iupac_status','naming_state','certified_preferred_iupac','state_sha256','reviewer','time','recorded_at','kernel_passport','kernel_naming']);
const uiHiddenNameFields=new Set(['preferred_iupac_name','preferred_iupac_status','certified_preferred_iupac','naming_state']);
function redactUi(v){
 if(Array.isArray(v))return v.map(redactUi);
 if(v&&typeof v==='object')return Object.fromEntries(Object.entries(v).filter(([k])=>!uiHiddenNameFields.has(k)).map(([k,x])=>[k,redactUi(x)]));
 return v;
}
const raw=v=>'<pre data-raw-index="'+(rawValues.push(redactUi(v))-1)+'"></pre>';
function bindRawDetails(){
 document.querySelectorAll('#reader details').forEach(detail=>detail.addEventListener('toggle',()=>{
  if(!detail.open)return;
  detail.querySelectorAll('pre[data-raw-index]').forEach(pre=>{
   if(pre.closest('details')!==detail)return;
   pre.textContent=JSON.stringify(rawValues[Number(pre.dataset.rawIndex)],null,2)||'';
   pre.removeAttribute('data-raw-index');
  });
 }));
}
function sources(refs=[]){const seen=new Set();return refs.map(r=>{const page=r.startsWith('page:')?r.slice(5):bundle?.sourceIndex?.[r];const href=r==='text:input'?'/source-input/'+encodeURIComponent(selected):'/source-view/'+encodeURIComponent(selected)+(page?'?page='+page+'#p'+page:'');if(seen.has(href))return '';seen.add(href);return '<a class="source-link" target="_blank" href="'+href+'">'+esc(page?'原文第 '+page+' 页':r==='text:input'?'输入来源':r)+'</a>'}).join('')}
function related(id){const m=bundle?.candidate?.materials?.[id];return m?'<button class="inline-member" data-member="'+esc(id)+'">'+esc(m.label)+'</button>':esc(id)}
function relationFieldLabel(key,record){
 const pair={precursor_to_product:['前体材料','产物材料'],sample_state_of:['样品','基础材料'],physical_blend_component:['共混组分','共混材料'],formulation_component:['配方组分','物理复合材料'],graft_backbone_of:['接枝骨架','接枝材料'],graft_sidechain_of:['聚合侧链','接枝材料'],source_of:['来源组分','关联材料'],derived_from:['派生材料','来源材料'],processed_from:['加工样品','基础材料']}[record.type||record.relation];
 if(['from_material_id','from'].includes(key))return pair?.[0]||'关联材料 A';
 if(['to_material_id','to'].includes(key))return pair?.[1]||'关联材料 B';
 return labels[key]||key.replace(/_/g,' ');
}
Object.assign(labels,{stage:'产物阶段',connectivity_change:'连接变化',stereochemistry:'立构范围',composition_basis:'组成与用量基准',precursor_distinction:'与前体的区别'});
Object.assign(words,{formulation_component:'物理配方组分',polymer_matrix:'聚合物基体名称范围',feasible_hypothesis:'可行假设（未证明最可能）',MODEL_CLASS_NAME_REVIEWED_WITH_TOOL_GAPS:'主模型核对类别名称；具体构成未确定',precursor_to_product:'前体到化学产物',physical_blend_component:'物理共混组分',graft_backbone_of:'接枝骨架关联',graft_sidechain_of:'聚合侧链关联',source_of:'来源组分关联',derived_from:'派生材料关联',processed_from:'加工样品关联',comparison:'对比材料',MODEL_RULE_REVIEWED:'主模型按规则核对（工具覆盖单列）',MODEL_STRUCTURE_GRAPH_CHECKED:'主模型按规则命名，子单元及整图核对一致',MODEL_RULE_REVIEWED_WITH_TOOL_GAPS:'主模型按规则命名，部分子单元工具尚不支持',MODEL_EVIDENCE_NAME_REVIEWED:'来源等命名规则与最终产物范围已由主模型核对'});
function display(v,key=''){
 if(v==null)return '原文未明确';
 if(key==='source_refs'&&Array.isArray(v))return sources(v);
 if(['material_id','source_molecule_material_id','from_material_id','to_material_id','from','to','guanamine_material_id'].includes(key)&&bundle?.candidate?.materials?.[v])return related(v);
 if(key==='material_ids'||key==='components'&&Array.isArray(v)&&v.every(x=>typeof x==='string'))return v.map(related).join('、');
 if(key==='graph_id')return esc(scopes[bundle?.candidate?.graphs?.[v]?.scope]||'已保存结构');
 if(Array.isArray(v))return v.length?'<ul class="facts">'+v.map(x=>'<li>'+display(x)+'</li>').join('')+'</ul>':'';
 if(typeof v==='object')return '<dl class="facts">'+Object.entries(v).filter(([k,x])=>!technical.has(k)&&x!==undefined).map(([k,x])=>'<div><dt>'+esc(relationFieldLabel(k,v))+'</dt><dd>'+display(x,k)+'</dd></div>').join('')+'</dl>';
 return esc(typeof v==='boolean'?(v?'是':'否'):typeof v==='number'?numericDisplay(v):words[v]||v);
}
const records=(arr=[])=>arr.map(x=>'<div class="record">'+display(x)+'</div>').join('');
function section(label,body,id=''){return body?'<section class="section"'+(id?' id="'+id+'"':'')+'><h3>'+label+'</h3>'+body+'</section>':''}
function relevant(r,id){const targets=[...(r.material_ids||[]),r.material_id,r.from_material_id,r.to_material_id,r.from,r.to].filter(Boolean);return !targets.length||targets.includes(id)}
function navigationSeries(c){
 // Reading groups only: never merge identities, infer missing samples or mutate c.
 const major=Object.values(c.materials||{}).filter(m=>m.major),byId=new Map(major.map(m=>[m.id,m])),assigned=new Set(),groups=[];
 const add=(key,title,items,note='')=>{items=items.filter(m=>m&&!assigned.has(m.id));if(!items.length)return;items.forEach(m=>assigned.add(m.id));groups.push({key,title,items,note})};
 const sourceSeriesTitle=items=>{let prefix=items[0]?.label||'';for(const m of items)while(prefix&&!String(m.label||'').startsWith(prefix))prefix=prefix.slice(0,-1);prefix=prefix.replace(/[-\s]+$/,'');return /^[A-Z][A-Z0-9]{1,11}$/.test(prefix)?prefix+' 系列':'高分子对比系列'};
 for(const r of c.relations||[]){
  if(!/series/.test(r.type||r.relation||''))continue;
  const items=(r.material_ids||[]).map(id=>byId.get(id)).filter(Boolean);
  if(items.length>1)add('relation:'+items.map(m=>m.id).join(':'),r.label||r.name||sourceSeriesTitle(items),items,'原文系列');
 }
 const rootOf=m=>{let root=m;const seen=new Set([m.id]);while(byId.has(root.parent_id)&&!seen.has(root.parent_id)){root=byId.get(root.parent_id);seen.add(root.id)}return root};
 for(const root of major){const items=major.filter(m=>!assigned.has(m.id)&&rootOf(m).id===root.id);if(items.length>1)add('parent:'+root.id,root.label+' 系列',items,'基体与相关样品')}
 const numbered=new Map();
 for(const m of major.filter(m=>!assigned.has(m.id))){const match=/^(\d+)[a-z]$/i.exec(m.label||'');if(match){const key=m.kind+':'+match[1];if(!numbered.has(key))numbered.set(key,[]);numbered.get(key).push(m)}}
 for(const [key,items] of numbered){if(items.length<2)continue;const ordered=[...items].sort((a,b)=>a.label.localeCompare(b.label,undefined,{numeric:true}));add('numbered:'+key,ordered[0].label+'–'+ordered.at(-1).label+' 系列',items,'按原文编号阅读')}
 // Explicit pairs can share reading tabs; keep already grouped bases and states together.
 for(const r of c.relations||[]){
  if(r.type!=='comparison'||r.material_ids?.length!==2)continue;
  const items=r.material_ids.map(id=>byId.get(id));
  if(items.every(m=>m&&!assigned.has(m.id)))add('comparison:'+items.map(m=>m.id).join(':'),r.label||r.name||items.map(m=>m.label).join(' / '),items,'原文比较对');
 }
 const blends=major.filter(m=>!assigned.has(m.id)&&m.kind==='blend');if(blends.length>1)add('kind:blend','共混材料系列',blends,'各样品组成分别保存');
 for(const m of major)if(!assigned.has(m.id))add('material:'+m.id,m.label,[m]);
 return groups.sort((a,b)=>major.indexOf(a.items[0])-major.indexOf(b.items[0]));
}
function seriesSamples(group,m,overview){
 if(overview||!group)return '';
 const back=!group.items.some(x=>x.id===m.id)?'<button data-member="'+esc(rememberedSamples.get(group.key)||group.items[0].id)+'" class="return-sample">返回系列样品</button>':'';
 return (group.items.length>1?'<nav class="members sample-tabs" aria-label="选中系列的样品"><span class="sample-tabs-label">样品</span>'+group.items.map(x=>'<button data-member="'+esc(x.id)+'" class="'+(x.id===member?'selected':'')+'" '+(x.id===member?'aria-current="true"':'')+'>'+esc(x.label)+'</button>').join('')+back+'</nav>':back?'<div class="members">'+back+'</div>':'');
}
function nameHeading(m){
 const a=m.iupac_assessment||{};
 if(a.primary_matches_display&&(a.formal_name||['identity-model-nomenclature/1.0','identity-model-nomenclature/1.1'].includes(a.contract))){
  if(a.hypotheses?.length)return a.proposal?.hypothesis_ranking?'IUPAC 名称候选（有依据的优先假设）':'IUPAC 名称候选（可行假设，未确定唯一身份）';
  if(a.proposal?.name_scope==='class_based')return 'IUPAC 类别名称（较宽身份范围）';
  if(['identity-model-nomenclature/1.0','identity-model-nomenclature/1.1'].includes(a.contract))return m.most_likely_name?.basis==='structure_based'?'IUPAC 结构名称候选（主模型规则核对）':'IUPAC 名称候选（来源等适用范围）';
  if(a.status==='STRUCTURE_NAME_SUPPORTED')return 'IUPAC 结构名称候选（图名一致）';
  return 'IUPAC 来源型名称（声明范围）';
 }
 const basis=m.most_likely_name?.basis;
 if(basis==='material_expression')return '材料身份描述';
 if(['component','monomer','oligomer'].includes(m.kind))return basis==='source_based'?'有限分子来源名称候选':'有限分子系统名称候选';
 return basis==='source_based'?'来源型聚合物名称候选':basis==='structure_based'?'结构型聚合物名称候选':'化学名称候选';
}
 function nameEvidence(m){
  const v=m.naming_verification||{status:'NOT_RUN'},rules=m.kernel_rule_naming||{};
 const gaps=v.reason_code||(['identity-model-nomenclature/1.0','identity-model-nomenclature/1.1'].includes(m.iupac_assessment?.contract)?null:rules.reason_code);
 const assessment=m.iupac_assessment,a=assessment?.formal_name&&!assessment.primary_matches_display?{...assessment,status:'DISPLAY_NAME_UNVERIFIED'}:assessment,states={STRUCTURE_NAME_SUPPORTED:'结构型命名规则与完整周期图匹配',DISPLAY_NAME_UNVERIFIED:'当前名称与规则建议不同，尚未通过此范围校验',SOURCE_NAME_SUPPORTED:'来源型命名规则支持',BASE_NAME_WITH_QUALIFIERS:'基础名称支持，样品限定另列',SOURCE_NETWORK_SUPPORTED:'网络来源型命名规则支持',SOURCE_ASSEMBLY_SUPPORTED:'共混来源型命名规则支持',QUALIFIED_DESCRIPTION:'基础名称已验证；功能化身份仍不完整',QUALIFIED_ASSEMBLY:'共混关系支持；接枝组分名称仍需补证',CANDIDATE_SET_VERIFIED:'两个异构体名称分别与图一致；尚未选定身份',MODIFIED_NAME_SUPPORTED:'IUPAC 改性聚合物规则支持',GRAFT_NAME_SUPPORTED:'IUPAC 来源型接枝规则支持',HYPOTHESIS_NAME_SUPPORTED:'候选图名称一致；已明确选择假设',NEEDS_EVIDENCE:'命名仍需补充证据'};
 return (a?.source_conflicts?.length?'<div class="hypothesis-note"><strong>原文／解析证据冲突（原值与推断分别保留）</strong>'+records(a.source_conflicts)+'</div>':'')+(a?.hypotheses?.length?'<div class="hypothesis-note"><strong>'+esc(a?.proposal?.hypothesis_ranking?'本名称采用有依据的优先假设':'本名称基于可行假设，尚未证明最可能')+'</strong>'+records(a.hypotheses)+'</div>':'')+'<div class="check-summary"><strong>'+esc(a?states[a.status]||words[a.status]||a.status:checks[v.status]||v.status)+'</strong><p>'+esc(v.validation_scope==='reported_source_nomenclature_not_product_constitution'?'来源名称与已保存组分证据一致；不推断完整聚合产物结构。':v.validation_scope==='source_descriptor_not_product_graph'?'校验范围：来源与材料描述；尚未证明聚合后的构成。':v.status==='MODEL_RULE_REVIEWED'?(a?.tool_graph_match?'子单元名称与整图核对一致；命名方向等规则由主模型核对，候选名称。':'已保存主模型规则依据；工具未覆盖的部分保留，不能当作完整名称—图验证。'):v.status==='GRAPH_MATCH'?'校验范围：当前编码图；实物身份和链级细节仍需进一步证据。':v.status==='NOT_APPLICABLE'?'按材料描述或局部构成范围阅读。':'候选保留；校验缺口可展开查看。')+'</p>'+(a?.source_alternative?'<p class="source-name-alternative">保留来源型名称：'+esc(a.source_alternative.text)+'</p>'+(a.source_alternative.assessment?.hypotheses?.length?'<details><summary>来源型名称的范围与假设</summary>'+records(a.source_alternative.assessment.hypotheses)+'</details>':''):'')+(a?.base_name?'<p>已验证基础名称：'+esc(a.base_name)+'</p>':'')+(a?.identity_qualifiers?.length?'<div class="identity-qualifiers"><strong>身份限定</strong>'+records(a.identity_qualifiers)+'</div>':'')+(a?.alternatives?'<ul>'+a.alternatives.map(x=>'<li>'+esc(x.name)+'</li>').join('')+'</ul>':'')+(a?.next_steps?.length?'<details class="naming-next"><summary>如何继续提升此对象的命名</summary>'+records(a.next_steps)+'</details>':'')+(rules.structure_naming&&a?.status!=='STRUCTURE_NAME_SUPPORTED'&&!['identity-model-nomenclature/1.0','identity-model-nomenclature/1.1'].includes(a?.contract)?'<p>由重复图生成名称：'+esc(checks[rules.structure_naming.status]||rules.structure_naming.status)+'</p>':'')+(a?.proposal?'<details><summary>最终产物与命名规则核对</summary>'+display(a.proposal.product_identity_check)+records(a.proposal.rule_review)+(a.checks?.subunit_checks?records(a.checks.subunit_checks.map(x=>({name:x.name,status:x.status,provider:x.provider}))):'')+'</details>':'')+'<details><summary>规则依据与未完成项</summary>'+display({范围:v.scope||m.most_likely_name?.scope,校验缺口:a?.reason_code||gaps||'未完成全部命名规则',命名规则合同:a?.contract||rules.contract||'未执行',重复单元选择:v.preferred_cru_selection||'NOT_COMPLETED',独立复核:'未另安排（NOT_REVIEWED）'})+(a?'<a target="_blank" rel="noopener" href="'+esc(a.source_url)+'">IUPAC 命名规则依据</a>'+raw(a):'')+raw(v)+raw(rules)+'</details></div>';
}
function graphSummary(g){
 const profile=g.chemical_profile,props=profile?.properties||[];
 const main=props.filter(p=>['formula','molar_mass','formal_charge','port_count','exact_mass'].includes(p.key));
 return '<div class="graph-summary"><p><strong>RDKit</strong> · '+esc(profile?.method||'已保存图计算')+' · '+esc(scopes[g.scope]||g.scope)+'</p>'+main.map(p=>'<span class="property"><strong>'+esc(p.label)+'</strong> '+esc(p.value)+' '+esc(p.unit)+'</span>').join('')+'<details><summary>结构编码与组分化学性质</summary><p class="smiles">'+esc(g.canonical_smiles)+'</p>'+display(props.filter(p=>!main.includes(p)))+display(profile?.functional_groups||[])+'<p>'+esc((profile?.limitations||[]).join(' '))+'</p></details><details><summary>结构规则命名及范围（独立于 OPSIN 解析）</summary>'+esc(checks[g.rule_profile_result?.status||g.deterministic_name?.status]||g.rule_profile_result?.status||g.deterministic_name?.status||'未执行')+'</details>'+(g.rule_profile_result?.primary?.text?'<p>由编码图生成的结构名称候选（）：'+esc(g.rule_profile_result.primary.text)+'</p>':'')+'</div>';
}
function toolEvidence(m){
 const links=m.tool_evidence||[],all=bundle.tool_evidence||{};
 if(!links.length&&!(m.graph_ids||[]).some(g=>bundle.candidate?.graphs?.[g]?.scope==='finite_molecule'))return '';
 const providers=['OPSIN','PubChem',...['CIR','CAS'].filter(p=>links.some(x=>all[x.receipt_id]?.input?.provider===p))];
 return '<div class="tool-evidence"><h4>本地与在线工具结果</h4>'+providers.map(provider=>{
  const entries=links.map(x=>({link:x,r:all[x.receipt_id]})).filter(x=>x.r&&(provider==='OPSIN'?x.r.operation==='resolve':x.r.operation==='public_lookup'&&x.r.input?.provider===provider));
  if(!entries.length)return '<p><strong>'+provider+'</strong> · '+(bundle.history_view&&!bundle.foundation_contract?'此版本未绑定工具回执':provider==='CAS'?'未配置':'未执行')+'</p>';
  return entries.map(({r,link},entryIndex)=>{const out=r.result||{},result=out.result||out,p=result.candidates?.length===1?result.candidates[0]:{};
   const query=r.operation==='public_lookup'&&r.input?.graph_id?'有限结构图查询':link.query||out.query||out.name||'';
   const verified=Boolean(r.id)&&((m.naming_verification?.reused_receipt===r.id&&m.naming_verification?.status==='GRAPH_MATCH')||m.iupac_assessment?.checks?.some(c=>c.receipt_id===r.id&&c.relation==='EQUAL'));
   const match=out.graph_check?.status||link.binding_check||(verified?'GRAPH_MATCH':null);
   return '<div class="tool-item"><p class="tool-status"><strong>'+provider+'</strong> · '+esc(checks[out.status||result.status]||out.status||result.status||'未知')+' · '+esc(query)+'</p>'+display({...(result.formula||p.MolecularFormula?{分子式:result.formula||p.MolecularFormula}:{}),...(p.IUPACName?{外部数据库名称:p.IUPACName}:{}),图一致性:checks[match]||match||'未单独核对',调用时间:r.finished_at,...(out.reused_parser_receipt_id?{解析执行:'复用已保存的成功回执；本次未重新运行 OPSIN'}:{})})+(Number.isSafeInteger(p.CID)&&p.CID>0?'<p><a target="_blank" rel="noopener" href="https://pubchem.ncbi.nlm.nih.gov/compound/'+p.CID+'">PubChem CID '+p.CID+'</a></p>':'')+'<details><summary>查询名称、失败原因与原始回执</summary>'+raw(r)+'</details></div>'}).join('');
 }).join('')+'</div>';
}
function componentReferenceIssues(candidate,onlyOwner){
 const materials=candidate?.materials||{},issues=[];
 for(const [owner,m] of Object.entries(materials)){
  if(onlyOwner!=null&&owner!==onlyOwner)continue;
  for(const [position,use] of (Array.isArray(m.components)?m.components:[]).entries()){
   if(!use||typeof use!=='object')continue;
   for(const field of ['material_id','source_molecule_material_id']){
    if(!Object.prototype.hasOwnProperty.call(use,field))continue;
    const target=use[field];
    if(typeof target!=='string'||!target.trim()||!Object.prototype.hasOwnProperty.call(materials,target))
     issues.push({owner,label:m.label||owner,position,field,target});
   }
  }
 }
 return issues;
}
function componentReferenceWarning(candidate){
 const issues=componentReferenceIssues(candidate);
 if(!issues.length)return '';
 const rows=issues.map(x=>'<li>'+esc(x.label)+'：保存的组分引用 '+esc(x.target==null?'（空值）':String(x.target))+' 无法解析</li>').join('');
 return '<div class="draft-note" data-reference-issues="'+issues.length+'" role="status"><strong>此保存版本有 '+issues.length+' 个组分引用无法解析。</strong><p>这些来源关系尚未完整核对；原始记录保留。</p><details><summary>涉及的对象和保存引用</summary><ul>'+rows+'</ul></details></div>';
}
function evaluationRow(m){
 const row=evaluation?.by_material_id?.[m.id];
 if(row)return row;
 return (evaluation?.rows||[]).find(x=>x.extraction_object===m.id||x.extraction_object===m.label);
}
function evaluationMarkup(m){
 const row=evaluationRow(m);if(!row)return '';
 const score=Number.isInteger(row.score)?row.score:null,flags=(row.flags||[]).join('、');
 const p=row.extraction_identity_package||{}, names=(p.source_names||[]).join('；'), graph=(p.graphs||[]).map(g=>[g.id,g.scope,g.formula].filter(Boolean).join(' · ')).join('；');
 const listText=v=>(v||[]).map(x=>typeof x==='string'?x:(x?.text||x?.name||JSON.stringify(x))).join('；');
 const packageBlock=Object.keys(p).length?'<div class="evaluation-package"><div><span>抽取原文代称/名称</span><strong>'+esc(names||'未保存')+'</strong></div><div><span>候选结构范围</span><strong>'+esc(p.scope_note||p.structure_kind||'未说明')+'</strong></div>'+(graph?'<div><span>结构摘要</span><strong>'+esc(graph)+'</strong></div>':'')+((p.identity_qualifiers||[]).length?'<div><span>身份限定</span><strong>'+esc(listText(p.identity_qualifiers))+'</strong></div>':'')+((p.unknowns||[]).length?'<details><summary>保留未知（'+p.unknowns.length+'）</summary><p>'+esc(listText(p.unknowns))+'</p></details>':'')+'</div>':'';
 const detail=row.comparison_detail?'<details class="evaluation-detail"><summary>为什么判定抽取更好</summary><p>'+esc(row.comparison_detail)+'</p></details>':'';
 return '<section class="evaluation-card" aria-label="人工结果对照"><div class="evaluation-card-heading"><h3>人工结果对照</h3>'+(score!=null?'<strong class="evaluation-score score-'+score+'">'+score+'/2</strong>':'')+'</div><div class="evaluation-grid"><div><span>人工名称</span><strong>'+esc(row.manual_name||row.source_alias_or_name||'未提供')+'</strong></div><div><span>抽取候选 IUPAC</span><strong>'+esc(row.extraction_iupac_candidate||'未提供')+'</strong></div></div>'+packageBlock+'<p class="evaluation-result">'+esc(row.result||'未记录对照结论')+(flags?'<span> · '+esc(flags)+'</span>':'')+'</p>'+detail+(row.note?'<details><summary>对照备注</summary><p>'+esc(row.note)+'</p></details>':'')+'</section>';
}

function componentSummaries(m){
 const groups=new Map(),unlinked=[];
 for(const use of (Array.isArray(m.components)?m.components:[])){if(!use||typeof use!=='object')continue;const id=use.material_id||use.source_molecule_material_id;
  if(id&&Object.prototype.hasOwnProperty.call(bundle.candidate.materials,id)){if(!groups.has(id))groups.set(id,[]);groups.get(id).push(use)}else unlinked.push(use);
 }
 const figure=(g,label)=>{const role=graphRole(g,{});return '<figure class="component-structure" data-graph="'+esc(g.id)+'">'+(g.depiction?.image?'<img src="'+esc(g.depiction.image)+'" alt="'+esc(label)+' · '+esc(role.title)+'" data-zoom>':'<p>此版本没有已保存的结构图像。</p>')+'<figcaption><strong>'+esc(role.title)+'</strong> · '+esc(graphFormula(g))+' · '+esc(scopes[g.scope]||g.scope)+'<p>'+esc(role.detail)+'</p></figcaption>'+graphSummary(g)+sources(g.source_refs)+'</figure>';};
 const cards=[...groups].map(([id,uses])=>{const c=bundle.candidate.materials[id],gs=(c.graph_ids||[]).map(g=>bundle.candidate.graphs[g]).filter(Boolean);
  const local=[...new Set(uses.flatMap(u=>[u.conditional_graph_id,...(u.candidate_graphs||[])]).filter(Boolean))].filter(g=>!c.graph_ids?.includes(g)).map(g=>bundle.candidate.graphs[g]).filter(Boolean);
  return '<div class="component-card" data-component="'+esc(id)+'"><div class="component-heading">'+related(id)+'<span>'+esc(types[c.kind]||c.kind)+'</span></div><p class="component-name">'+esc(c.most_likely_name?.text||'名称未确定')+'</p><p class="component-aliases">来源名称：'+esc(componentAliases(c).join('；')||c.label)+'</p><details class="component-uses"><summary>使用角色、用量与原文依据</summary>'+records(uses)+'</details><div class="component-graphs">'+(gs.length?gs.map(g=>figure(g,c.label)).join(''):'<p class="scope-note">来源名称已保存；有限结构解析尚未完成。</p>')+'</div>'+(c.iupac_assessment?.identity_qualifiers?.length?records(c.iupac_assessment.identity_qualifiers):'')+local.map(g=>'<p class="scope-note">关联的局部或有条件构成图；不代表此有限前体已经聚合。</p>'+figure(g,'局部构成')).join('')+toolEvidence(c)+(identityProperties(c)?'<details class="component-identity-properties"><summary>组分身份性质</summary>'+identityProperties(c)+'</details>':'')+(c.identity_preparations?.length?'<details><summary>缩写、同义词与工具名称准备</summary>'+records(c.identity_preparations)+'</details>':'')+'<p>'+related(id)+' <span class="name-note">查看组分详情</span></p></div>';
 });
 for(const use of unlinked){const ids=[use.graph_id,use.conditional_graph_id,...(use.candidate_graphs||[])].filter(Boolean),gs=[...new Set(ids)].map(g=>bundle.candidate.graphs[g]).filter(Boolean);cards.push('<div class="component-card component-fragment">'+records([use])+gs.map(g=>figure(g,use.label||use.identity||use.name||'局部组分')).join('')+'</div>')}
 const missing=componentReferenceIssues(bundle.candidate,m.id);
 const warning=missing.length?'<p class="draft-note">此版本未定义该组分引用：'+missing.map(x=>esc(x.target==null?'（空值）':String(x.target))).join('；')+'。来源关系尚未完整核对。</p>':'';
 return warning+(cards.length?'<div class="component-grid">'+cards.join('')+'</div>':'');
}
function identityProperties(m){
 return ['molar_mass','identity_properties','crystalline_identity','sensitizer_conditions','tool_calculations','computational_evidence','supplier'].filter(k=>m[k]!=null).map(k=>'<div class="record"><strong>'+esc(labels[k]||k.replace(/_/g,' '))+'</strong>'+display(m[k])+'</div>').join('');
}
function sourceFacts(c,m){
 const facts=c.source_facts||[],owned=facts.filter(x=>Object.keys(x||{}).some(k=>['material_id','material_ids','from','to'].includes(k))&&relevant(x,m.id));
 const common=facts.filter(x=>!Object.keys(x||{}).some(k=>['material_id','material_ids','from','to'].includes(k)));
 return records(owned)+(common.length?'<details><summary>本文共同来源事实（未归属当前成员）</summary>'+records(common)+'</details>':'');
}
function revisionForm(m){
 if(bundle.history_view||bundle.display_state==='SAVED_DRAFT')return '';
 return '<details class="revision-form"><summary>修订当前身份证</summary><label>候选名称或材料描述<input id="revision-name" value="'+esc(m.most_likely_name?.text||'')+'"></label><label>修订理由<textarea id="revision-reason" placeholder="说明修订依据和需要保留的未知"></textarea></label><button id="preview-revision">校验并预览新版本</button><span id="revision-status" role="status"></span><div id="revision-preview"></div></details>';
}
function versionHistory(){
 return '<details class="version-history"><summary>版本与回放</summary><p>'+esc(bundle.revision?.reason||'首次封存结果')+'</p><p>'+esc(bundle.version)+'</p>'+(bundle.revision?.parent_version?'<button id="previous-version">读取上一版本</button>':'')+(bundle.history_view?'<button id="current-version">返回当前采用版本</button>':'')+'</details>';
}
async function readHistorical(version){
 const token=++generation,id=selected,mid=member;const response=await fetch('/api/version/'+encodeURIComponent(version));const b=await response.json();
 if(token!==generation||id!==selected)return;if(!response.ok)throw Error(b.error||'历史版本读取失败');if(!completedResult(b))throw Error('此历史版本未完成，不能作为身份证阅读');
 bundle={...b,history_view:true,sourceIndex:Object.fromEntries((b.source_index?.blocks||[]).map(x=>[x.id,x.page]))};member=mid;postsealNotes=null;render();void loadPostsealNotes(bundle.version,token,id);
}
function componentAliases(m){
 const raw=[m.label,...(m.aliases||m.source_names||[]),...(m.identity_preparations||[]).flatMap(p=>[p.raw_name,...(p.aliases||[])])];
 return [...new Set(raw.filter(x=>typeof x==='string'&&x.trim()))];
}
function graphFormula(g){return g.chemical_profile?.properties?.find(p=>p.key==='formula')?.value||g.formula}
function graphRole(g,m){
 const id=String(g.id||'').toLowerCase(),scope=g.scope;
 if(scope==='finite_molecule')return {title:'原料／组分结构图',detail:'这是有限分子图，用来说明投料或组分身份；对于高分子对象，它不是聚合物产物结构。'};
 if(id.includes('junction'))return {title:'聚合物局部连接图（最接近当前产物）',detail:'把主链局部与连接节点放在一起；它是当前对象网络的局部代表，不是完整网络拓扑。'};
 if(id.includes('btc'))return {title:'交联节点图（BTC）',detail:'只表示三官能交联组分与胺端的局部交联节点，用于解释网络连接角色。'};
 if(scope==='constitutional_unit')return {title:'聚合物主链局部构成图',detail:'表示当前对象的聚合物主链局部，是高分子骨架的核心局部图。'};
 if(scope==='local_network')return {title:'聚合物网络局部图',detail:'表示网络中的局部连接关系，不能外推为完整链级结构。'};
 return {title:'当前范围结构图',detail:'图像只代表保存的编码范围。'};
}
function mainFigure(g,m){
 const repeat=g.scope==='repeat_unit',image=g.depiction?.image,d=m.structure_expression,declared=d?.graph_ids?.includes(g.id),role=graphRole(g,m),caption=role.title+(declared&&d.kind==='ideal_repeat'?' · '+(d.evidence_basis==='most_likely_hypothesis'?'最可能假设下的理想重复单元':'理想重复单元'):'');
 return '<figure class="structure" data-graph="'+esc(g.id)+'"><div class="structure-role"><strong>'+esc(role.title)+'</strong><span>'+esc(role.detail)+'</span></div>'+(image?'<div class="natural-structure"><div class="'+(repeat?'repeat-frame':'graph-frame')+'"><img src="'+esc(image)+'" alt="'+esc(m.label)+' '+esc(caption)+'" data-zoom>'+(repeat?'<span class="repeat-index">n</span>':'')+'</div></div>':'<p>结构图尚未保存。</p>')+'<figcaption><span class="formula">'+esc(graphFormula(g))+'</span>'+esc(caption)+'<p>'+(repeat?'n 表示未定聚合度；星号是连接端口，单元式不含端口且不补氢。':'图与式仅代表当前编码范围；局部图不代表实物全链或整个网络。')+'</p>'+sources(g.source_refs)+'</figcaption>'+graphSummary(g)+'</figure>';
}
function structureDecision(m){
 const d=m.structure_expression;if(!d)return '';
 return '<div class="scope-note product-structure-decision"><p>'+esc(d.reason)+'</p>'+(d.assumptions?.length?'<details><summary>构成图的假设与保留未知</summary>'+records(d.assumptions)+records(d.unknowns||[])+'</details>':'')+'</div>';
}
function filterObjects(){
 const q=($('#object-search')?.value||'').trim().toLowerCase(),kind=$('#object-kind')?.value||'major',role=$('#object-role')?.value||'all';
 Object.assign(readerFilters,{query:$('#object-search')?.value||'',kind,role});
 const activeKind=kind==='major'&&q?'all':kind;
 const matches=m=>{const poly=['polymer','prepolymer','network','blend','series'].includes(m.kind);return componentAliases(m).concat(m.most_likely_name?.text||'').join(' ').toLowerCase().includes(q)&&(activeKind==='all'||activeKind==='major'&&m.major||activeKind==='polymer'&&poly||activeKind==='component'&&!poly)&&(role==='all'||m.role===role)};
 const groups=navigationSeries(bundle.candidate);
 document.querySelectorAll('[data-series-key]').forEach(el=>{const g=groups.find(g=>g.key===el.dataset.seriesKey);el.hidden=!(g?.items.some(matches)||g?.key===selectedSeries)});
 let visibleExtras=0;
 document.querySelectorAll('[data-picker-object]').forEach(el=>{const m=bundle.candidate.materials[el.dataset.pickerObject];el.hidden=!(matches(m)||m.id===member);if(!el.hidden)visibleExtras++});
 if($('#support-picker')&&visibleExtras&&(q||kind==='component'||!bundle.candidate.materials[member]?.major&&member!=='__overview__'))$('#support-picker').open=true;
}

function render(){
 if(!bundle?.candidate)return;
 rawValues=[];
 const c=bundle.candidate,all=Object.values(c.materials||{}),major=all.filter(m=>m.major),m=c.materials[member]||major[0]||all[0];if(!m)return;const requestedOverview=member==='__overview__';member=requestedOverview?'__overview__':m.id;
 const overview=member==='__overview__',series=navigationSeries(c),ownSeries=series.find(g=>g.items.some(x=>x.id===m.id));
 if(overview)selectedSeries=null;
 else if(ownSeries){selectedSeries=ownSeries.key;rememberedSamples.set(ownSeries.key,m.id)}
 else if(!series.some(g=>g.key===selectedSeries))selectedSeries=null;
 const activeSeries=series.find(g=>g.key===selectedSeries);
 const polymerCount=major.filter(x=>['polymer','prepolymer','oligomer','blend','network'].includes(x.kind)).length,mixedMajor=polymerCount!==major.length,majorSummary=mixedMajor?major.length+' 个研究对象（'+polymerCount+' 个高分子）':major.length+' 个高分子样品';
 const name=m.most_likely_name||{},allGraphs=(m.graph_ids||[]).map(id=>c.graphs?.[id]).filter(Boolean),polymerKinds=new Set(['polymer','prepolymer','oligomer','blend','network','assembly']),componentGraphIds=new Set((m.components||[]).flatMap(use=>{const id=use?.material_id||use?.source_molecule_material_id,target=id?c.materials?.[id]:null;return target?.graph_ids||[]})),finiteMoved=m.major&&polymerKinds.has(m.kind)?allGraphs.filter(g=>g.scope==='finite_molecule'&&componentGraphIds.has(g.id)):[],graphs=allGraphs.filter(g=>!finiteMoved.includes(g)),extras=all.filter(x=>!x.major);
 const draft=bundle.display_state==='SAVED_DRAFT';
 const aliases=componentAliases(m),chapters=[['identity','身份与结构'],['components','组成与组分'],['materials','材料与样品'],['preparation','制备与变化'],['properties','性质与结果'],['evidence','关联与证据']];
 const picker=extras.map(x=>'<button data-picker-object="'+esc(x.id)+'" data-member="'+esc(x.id)+'" class="object-picker '+(x.id===m.id?'selected':'')+'"><strong>'+esc(x.label)+'</strong><small>'+esc(types[x.kind]||x.kind)+' · '+esc(words[x.role]||x.role||'来源对象')+'</small><small>'+esc(componentAliases(x).join('；'))+'</small></button>').join('');
 $('#reader').innerHTML='<div class="paper-breadcrumb"><a href="/paper">← 全部文献</a><span>'+(draft?'已保存候选':bundle.history_view?'历史只读版本':'当前采用版本')+' · '+esc(bundle.version.slice(0,12))+'</span></div><div class="paper-document-heading"><small>来源文献</small><h1>'+esc(c.title||'已保存的部分结果')+'</h1><p>'+esc(bundle.source_index?.page_count||'')+' 页 · 内核 '+esc(bundle.kernel_version)+'</p>'+reviewStatusMarkup(c,bundle)+'<nav><a class="primary-action" target="_blank" href="/source-view/'+encodeURIComponent(selected)+'">阅读原文</a><a href="#review-record">核对与审核</a></nav></div><div id="postseal-note-container">'+postsealNoteMarkup()+'</div>'+componentReferenceWarning(c)+'<div class="object-toolbar"><input id="object-search" type="search" placeholder="搜索原文名称或别名" aria-label="搜索原文名称或别名"><select id="object-kind" aria-label="对象类型"><option value="major">本文研究对象</option><option value="polymer">所有高分子</option><option value="component">单体与组分</option><option value="all">全部对象</option></select><select id="object-role" aria-label="本文角色"><option value="all">所有角色</option>'+[...new Set(all.map(x=>x.role).filter(Boolean))].map(r=>'<option value="'+esc(r)+'">'+esc(words[r]||r)+'</option>').join('')+'</select></div><div class="paper-layout"><details class="object-sidebar" open><summary>'+(mixedMajor?'高分子系列与研究对象':'高分子系列与组分')+'</summary><nav class="series-list" aria-label="本文概览与研究系列"><button data-overview class="object-picker overview-picker '+(overview?'selected':'')+'" '+(overview?'aria-current="page"':'')+'><strong>本文概览</strong><small>'+esc(majorSummary)+'</small></button>'+series.map(g=>'<button data-series-key="'+esc(g.key)+'" class="object-picker series-picker '+(g.key===selectedSeries?'selected':'')+'" '+(g.key===selectedSeries?'aria-current="true"':'')+'><strong>'+esc(g.title)+'</strong><small>'+g.items.length+' 个样品'+(g.note?' · '+esc(g.note):'')+'</small></button>').join('')+'</nav>'+(extras.length?'<details id="support-picker" class="sidebar-components" '+(!m.major&&!overview?'open':'')+'><summary>单体与组分 ('+extras.length+')</summary><div class="object-list">'+picker+'</div></details>':'')+'</details><div class="card" data-version="'+esc(bundle.version)+'" data-material="'+esc(m.id)+'">'+(draft?'<p class="draft-note">这是已保存的部分候选，尚未通过交付检查。</p>'+records(bundle.errors||[]):'')+'<div class="reader-actions"><a href="#review-record">在工作台核对</a></div>'+seriesSamples(activeSeries,m,overview)+'<nav class="chapter-anchors" aria-label="身份证章节定位">'+chapters.map(([id,label],i)=>'<a class="'+(!i?'active':'')+'" href="#'+id+'">'+label+'</a>').join('')+'</nav><section id="identity"><p class="eyebrow">'+esc(types[m.kind]||m.kind)+'身份</p><h2 class="identity-title">'+esc(m.label)+'</h2><p class="source-aliases">原文代称：'+esc(aliases.join('；'))+'</p><p>'+esc(m.description||'')+'</p>'+(m.graph_scope_note&&m.graph_scope_note!==m.structure_expression?.reason?'<p class="scope-note">'+esc(m.graph_scope_note)+'</p>':'')+(m.naming_limits?'<details><summary>结构说明与边界</summary>'+display(m.naming_limits)+'</details>':'')+structureDecision(m)+(graphs.length?graphs.map(g=>mainFigure(g,m)).join(''):finiteMoved.length?'<p class="scope-note">原料／组分结构图已集中显示在后面的“组成与组分”。</p>':'<p class="draft-note">当前对象尚无已接收的结构图。</p>')+'<div class="chemical-names"><h2>化学名称与命名依据</h2><span class="name-kind">'+nameHeading(m)+'</span><button id="copy-name">复制候选名称</button><span id="copy-status" role="status"></span><div class="name">'+esc(name.text||'候选尚未完成')+'</div><div class="name-note">适用范围：'+esc(scopeLabel(m))+' · '+esc(words[name.basis]||name.basis)+'</div><details class="name-reason"><summary>命名范围与依据</summary><p>'+esc(name.reason)+'</p></details>'+nameEvidence(m)+sourceScopeReview(m,c)+'</div></section>'+section('组成与组分',componentSummaries(m)+(m.composition?display(m.composition):'')+toolEvidence(m)+(m.identity_preparations?.length?'<details class="identity-preparations"><summary>缩写、同义词与工具名称准备</summary>'+records(m.identity_preparations)+'</details>':''),'components')+section('材料与样品',records(m.relationships||[])+records((c.relations||[]).filter(r=>relevant(r,m.id)))+(m.variants?display(m.variants):'<p>当前对象：'+esc(m.label)+'</p>'),'materials')+section('制备与变化',m.preparation?display(m.preparation):'<p>制备依据随来源保留。</p>','preparation')+section('身份与组分性质',identityProperties(m)||'<p>身份相关性质按来源报告保留。</p>','properties')+section('关联与证据',records(m.evidence_facts||[])+sourceFacts(c,m)+sources(m.source_refs),'evidence')+'<details><summary>假设与保留未知</summary>'+records(m.assumptions||[])+records(name.assumptions||[])+'<div class="unknown">'+records(m.unknowns||[])+records(name.unknowns||[])+records(c.unknowns||[])+'</div></details><details id="review-record"><summary>当前图名式复核与工具记录</summary>'+raw(m.review)+graphs.map(g=>'<p>'+esc(g.id)+' · '+esc(g.canonical_smiles)+'</p>'+raw(g.deterministic_name)).join('')+raw(m)+'</details><details><summary>修订与撤回</summary>'+raw(c.withdrawals||[])+'</details>'+revisionForm(m)+versionHistory()+'</div></div>';
 const comparison=evaluationMarkup(m);if(comparison&&!overview)$('#identity')?.insertAdjacentHTML('beforeend',comparison);
 if(overview)$('#reader .card').innerHTML=materialOverview(c,major,'',chapters);
 bindRawDetails();
 $('#object-search').value=readerFilters.query;$('#object-kind').value=readerFilters.kind;$('#object-role').value=readerFilters.role;
 if(!m.major&&!overview){$('#object-kind').value='all';readerFilters.kind='all'}
 document.querySelectorAll('[data-series-key]').forEach(b=>b.onclick=()=>{const group=series.find(g=>g.key===b.dataset.seriesKey);member=rememberedSamples.get(group.key)||group.items[0].id;render()});
 if($('#support-picker'))$('#support-picker').ontoggle=()=>{if($('#support-picker').open&&$('#object-kind').value==='major'){$('#object-kind').value='all';filterObjects()}};
 document.querySelectorAll('[data-overview]').forEach(b=>b.onclick=()=>{member='__overview__';render()});
 document.querySelectorAll('.chapter-anchors a').forEach(a=>a.onclick=()=>{document.querySelectorAll('.chapter-anchors a').forEach(x=>x.classList.toggle('active',x===a))});
 $('#object-search').oninput=filterObjects;$('#object-kind').onchange=filterObjects;$('#object-role').onchange=filterObjects;filterObjects();
 document.querySelectorAll('[data-member]').forEach(b=>b.onclick=()=>{member=b.dataset.member;render()});
 document.querySelectorAll('[data-zoom]').forEach(i=>i.onclick=()=>{$('#zoom-img').src=i.src;$('#zoom').showModal()});
 if($('#previous-version'))$('#previous-version').onclick=()=>readHistorical(bundle.revision.parent_version).catch(e=>$('#status').textContent=e.message);
 if($('#current-version'))$('#current-version').onclick=()=>loadJob(selected,m.id);
 if($('#preview-revision'))$('#preview-revision').onclick=async()=>{const status=$('#revision-status'),id=selected,version=bundle.version,token=generation;try{status.textContent=' 校验中…';const result=await post('/api/revisions/'+encodeURIComponent(id),{expected_version:version,material_id:m.id,name:$('#revision-name').value,reason:$('#revision-reason').value});if(token!==generation||id!==selected||member!==m.id)return;$('#revision-preview').innerHTML=display(result.diff)+records(result.errors||[])+'<p>新候选版本 '+esc(result.version?.slice(0,12))+'</p>'+(!result.errors?.length?'<button id="adopt-revision">采用此版本</button>':'');status.textContent=' 已保存预览；尚未采用';if($('#adopt-revision'))$('#adopt-revision').onclick=async()=>{try{await post('/api/adopt-revision/'+encodeURIComponent(id),{expected_version:version,version:result.version});if(token===generation&&id===selected)await loadJob(id,m.id)}catch(e){status.textContent=' '+e.message}}}catch(e){status.textContent=' '+e.message}};
 if($('#copy-name'))$('#copy-name').onclick=async()=>{try{await navigator.clipboard.writeText(name.text||'');$('#copy-status').textContent=' 已复制'}catch{$('#copy-status').textContent=' 请选中上方完整名称复制'}};
 if(isWorkbench())decorateTextResult({input_kind:bundle.source_index?.page_count===0?'text':'pdf'});
 if(isLibrary()){
  libraryMounted=false;$('#reader').insertAdjacentHTML('afterbegin','<div class="library-return"><button id="back-library">← 返回组分库</button><a href="/paper/'+encodeURIComponent(selected)+'?material='+encodeURIComponent(m.id)+'">打开来源文献与关联材料</a></div>');
  $('#back-library').onclick=()=>loadLibrary().catch(showError);
 }
}
async function loadJob(id,initialMember,expectedVersion){
 $('.workspace').classList.toggle('paper-directory',false);
 const token=++generation;if(selected!==id){selectedSeries=null;rememberedSamples.clear();readerFilters.query='';readerFilters.kind='major';readerFilters.role='all'}selected=id;member=initialMember||null;bundle=null;evaluation=null;postsealNotes=null;$('#status').textContent='正在读取保存版本…';$('#reader').innerHTML='<div class="notice">正在读取所选任务的保存结果…</div>';
 const response=await fetch('/api/job/'+encodeURIComponent(id));const result=await response.json();if(token!==generation)return;if(!response.ok)throw Error(result.error||'读取失败');
 $('#paper-nav').href='/paper';
 const run=result.run,b=result.bundle,active=activeStatuses.includes(run?.status),complete=run?.status==='DELIVERED'&&completedResult(b);$('#status').textContent=(complete?'已完成':active?'正在建立身份证':'暂无已完成结果')+(run?.elapsed_seconds?' · '+(run.elapsed_seconds/60).toFixed(1)+' 分钟':'');
 if(expectedVersion&&b?.version!==expectedVersion){await loadLibrary();$('#status').textContent='文献采用版本已更新，请从当前列表重新选择组分。';return}
 if(complete){bundle=b;bundle.sourceIndex=Object.fromEntries((b.source_index?.blocks||[]).map(x=>[x.id,x.page]));try{const er=await fetch('/api/evaluation/'+encodeURIComponent(id));const ed=await er.json();if(token===generation&&selected===id&&er.ok&&ed.available)evaluation=ed}catch{}render();void loadPostsealNotes(bundle.version,token,id)}else{$('#reader').innerHTML='<div class="notice"><h2>'+(!run?'未找到此文献结果':active?'身份证正在建立':'暂无已完成的身份证')+'</h2><p>完成并采用的结果会出现在文献首页。</p><a href="/paper">返回全部文献</a></div>'}
 if(isWorkbench()&&!complete)renderTask(run);
 else if(active){$('#reader').insertAdjacentHTML('beforeend','<div class="toolbar"><button id="stop-job">停止本任务</button></div>');$('#stop-job').onclick=()=>post('/api/stop/'+id,{})}
 if(complete&&isWorkbench())decorateTextResult(run);
 document.querySelectorAll('.job').forEach(j=>j.classList.toggle('active',(j.dataset.job||j.dataset.task)===id));
}
async function refresh(){
 if(refreshPending)return refreshPending;
 refreshPending=refreshDirectory();try{return await refreshPending}finally{refreshPending=null}
}
function sourceScopeReview(m,c){
 const review=c.source_review;
 if(review?.contract!=='identity-source-review/1.1')return '';
 const checks=(review.checks||[]).filter(x=>x.material_ids?.includes(m.id));
 const textSource=bundle?.source_index?.page_count===0&&Boolean(bundle?.sourceIndex?.['text:input']!==undefined);
 const labels={salt_charge:'盐态与电荷',stereo_isotope:'立构与同位素',end_groups:'端基与单元范围',assembly_topology:'组装与网络范围'};
 return '<details class="source-scope-review"><summary>来源核对与身份边界（同一模型）</summary><p>'+esc(textSource?'以下为本次模型对输入文本保存的观察和范围说明；确认状态也是主模型声明，程序校验来源及状态绑定，具体结论和保留问题如下。':'以下为本次模型保存的原页观察和范围说明；确认状态也是主模型声明，程序校验来源及状态绑定；原图解释由主模型作出，具体结论和保留问题如下。')+'</p>'+checks.map(x=>'<p>'+esc(x.topic==='identity'?'身份与命名范围':'数值与材料状态')+'：'+esc(x.reason)+'</p>'+sources(x.source_refs)+(x.identity_limits?records(Object.entries(x.identity_limits).map(([k,v])=>({项目:labels[k]||k,范围:v}))):'')+raw(x)).join('')+'</details>';
}
async function refreshDirectory(){
 if(isLibrary())return;
 if(isWorkbench())return refreshWorkbench();
 const rows=await completedDirectory(await fetch('/api/jobs').then(r=>r.json()));const signature=JSON.stringify(rows);
 if(signature!==directorySignature){directorySignature=signature;$('#jobs').innerHTML=rows.map(r=>'<button class="job '+(selected===r.job_id?'active':'')+'" data-job="'+esc(r.job_id)+'"><span class="job-label">'+esc(r.title)+'</span><small>已完成</small></button>').join('');document.querySelectorAll('[data-job]').forEach(b=>b.onclick=()=>loadJob(b.dataset.job).catch(e=>$('#status').textContent=e.message));
 if(location.pathname==='/paper'&&!selected)renderPaperDirectory(rows)}
 if(selected&&(!bundle||bundle.display_state==='SAVED_DRAFT'))await loadJob(selected,member);
}
function showError(e){$('#status').textContent=friendlyError(e.message||String(e))}
function friendlyError(message){
 const labels={TEXT_OR_PDF_REQUIRED:'请输入高分子描述，再开始生成。',TEXT_INPUT_INVALID:'文本输入格式无效。',TEXT_SIZE_LIMIT:'描述超过 60,000 字，请缩短后提交。',CHOOSE_TEXT_OR_PDF:'每次请选择文本或 PDF 一种来源。',CLI_PREFLIGHT_FAILED:'生成服务检查未通过。请查看任务错误记录，修复服务后重新提交。',ORIGINAL_JOB_DEADLINE_EXPIRED:'此任务原截止时间已过，请使用原描述创建新任务。',SEALED_JOB_IMMUTABLE_NEW_JOB_REQUIRED:'此任务已封存，请重新提交描述创建新任务。'};
 return labels[message]||message;
}
function renderTask(run){
 const state=run?.status,active=activeStatuses.includes(state),waiting=['QUEUED','CHECKING_RUNTIME'].includes(state);
 const title=taskLabels[state]||'暂无已完成结果';
 $('#status').textContent=title;
 $('#reader').innerHTML='<div class="card task-progress" aria-live="polite"><p class="eyebrow">身份证生成任务</p><h2>'+esc(title)+'</h2><ol class="progress-steps"><li class="'+(waiting?'current':'done')+'">排队与服务检查</li><li class="'+(active&&!waiting?'current':'')+'">解析、建图与 IUPAC 命名</li><li>保存并打开身份证</li></ol><p>'+esc(waiting?'队列和服务检查完成后开始本任务的 60 分钟预算。':active?'正在处理所提交的来源，页面会自动显示完成的身份证。':'本任务未交付完整身份证。原描述与任务记录保留。')+'</p>'+(run?.elapsed_seconds?'<p>已运行 '+(run.elapsed_seconds/60).toFixed(1)+' 分钟</p>':'')+(run?.error?'<p class="error">'+esc(friendlyError(run.error))+'</p>':'')+(run?.delivery?.errors?.length||run?.errors?.length?'<details><summary>未完成原因</summary>'+records(run.errors||run.delivery.errors)+'</details>':'')+'<p class="name-note">任务编号 '+esc(selected||run?.job_id||'')+'</p><div class="toolbar">'+(active?'<button id="stop-job">停止本任务</button>':'<button id="retry-text">使用原描述重新生成</button>')+'</div></div>';
 if(active)$('#stop-job').onclick=async()=>{try{await post('/api/stop/'+encodeURIComponent(selected),{});$('#stop-job').disabled=true;$('#status').textContent='已请求停止，正在等待当前步骤结束。'}catch(e){showError(e)}};
 else $('#retry-text').onclick=async()=>{const id=selected;try{const r=await fetch('/api/input/'+encodeURIComponent(id));if(!r.ok)throw Error('原描述暂不可读，请在输入框填写后重新提交。');const v=await r.json();if(id!==selected)return;$('#text').value=v.text;$('#text').oninput?.();$('#text').focus();$('#input-area').scrollIntoView({behavior:'smooth'})}catch(e){showError(e)}};
 if(run?.can_resume){$('#reader .toolbar').insertAdjacentHTML('afterbegin','<button id="resume-task">继续本任务</button>');$('#resume-task').onclick=async()=>{try{await post('/api/resume/'+encodeURIComponent(selected),{});await refresh()}catch(e){showError(e)}}}
}
function decorateTextResult(run){
 if(run?.input_kind!=='text'&&bundle?.source_index?.page_count!==0)return;
 const heading=$('.paper-document-heading');if(!heading)return;
 heading.innerHTML='<small>文本生成的化学身份证</small><h1>'+esc(bundle.candidate.title)+'</h1><p>用户描述来源 · 内核 '+esc(bundle.kernel_version)+'</p>'+reviewStatusMarkup(bundle.candidate,bundle)+'<nav><a class="primary-action" href="/source-input/'+encodeURIComponent(selected)+'" target="_blank">查看输入原文</a><a href="#identity">查看 IUPAC 名称与结构</a></nav>';
 const crumb=$('.paper-breadcrumb');if(crumb)crumb.innerHTML='<a href="/">← 身份证工作台</a><span>当前保存版本 · '+esc(bundle.version.slice(0,12))+'</span>';
 const alias=$('.source-aliases');if(alias)alias.textContent=alias.textContent.replace(/^原文代称：/,'输入名称：');
 const overview=$('[data-overview] strong');if(overview)overview.textContent='身份证概览';
 const name=$('.chemical-names');if(name){heading.insertAdjacentHTML('beforeend','<div class="text-result-name"><small>最可能 IUPAC 名称 · '+esc(scopeLabel(bundle.candidate.materials[member]||Object.values(bundle.candidate.materials).find(m=>m.major)||{}))+'</small><div>'+esc((bundle.candidate.materials[member]||Object.values(bundle.candidate.materials).find(m=>m.major))?.most_likely_name?.text||'查看身份证中的名称')+'</div></div>')}
}
async function refreshWorkbench(){
 const response=await fetch('/api/workbench');if(!response.ok&&response.ok!==undefined)throw Error('近期任务读取失败');
 const rows=await response.json();if(!Array.isArray(rows))return;
 const signature=JSON.stringify([selected,rows.map(r=>[r.job_id,r.title,r.status])]);
 if(signature!==directorySignature){directorySignature=signature;$('#jobs').innerHTML=rows.map(r=>'<button class="job '+(selected===r.job_id?'active':'')+'" data-task="'+esc(r.job_id)+'"><span class="job-label">'+esc(r.title)+'</span><small>'+esc(taskLabels[r.status]||r.status)+'</small></button>').join('')||'<p class="name-note">提交的文本任务将保存在这里。</p>';document.querySelectorAll('[data-task]').forEach(b=>b.onclick=()=>{rememberTask(b.dataset.task);loadJob(b.dataset.task).catch(showError)})}
 if(selected&&!bundle){const id=selected,token=generation,r=await fetch('/api/task/'+encodeURIComponent(id));const run=await r.json();if(token!==generation||selected!==id)return;if(!r.ok)throw Error(run.error||'任务状态读取失败');if(run.status==='DELIVERED')await loadJob(id,member);else renderTask(run)}
}
function rememberTask(id){if(typeof history!=='undefined')history.replaceState(null,'','/?job='+encodeURIComponent(id))}
async function completedDirectory(rows){
 const completed=await Promise.all(rows.filter(r=>r.status==='DELIVERED'&&r.version).map(async r=>{
  if(r.overview!==undefined)return r;
  // Older running servers supply compact rows; enrich once from immutable sealed versions.
  try{
   if(!directoryVersions.has(r.version)){const response=await fetch('/api/version/'+encodeURIComponent(r.version)),b=await response.json();if(!response.ok||!completedResult(b))return null;directoryVersions.set(r.version,b)}
   const b=directoryVersions.get(r.version),c=b.candidate,all=Object.values(c.materials),major=all.filter(m=>m.major),used=new Set(all.flatMap(m=>(m.components||[]).map(x=>x.material_id)));
   return {...r,title:c.title||r.title,overview:c.overview||'',source_sha256:b.source_sha256,page_count:b.source_index?.page_count||0,major_count:major.length,polymer_count:major.filter(m=>['polymer','prepolymer','oligomer','blend','network'].includes(m.kind)).length,material_labels:major.map(m=>m.label),component_count:all.filter(m=>['component','monomer'].includes(m.kind)||used.has(m.id)||['blend_component','starting_polymer_and_control'].includes(m.role)).length};
  }catch{return null}
 }));
 const titles=new Set(),sources=new Set();return completed.filter(Boolean).sort((a,b)=>b.started_at.localeCompare(a.started_at)||b.job_id.localeCompare(a.job_id)).filter(r=>{
  const title=r.title.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]/gu,''),duplicate=titles.has(title)||r.source_sha256&&sources.has(r.source_sha256);titles.add(title);if(r.source_sha256)sources.add(r.source_sha256);return !duplicate;
 });
}
function renderPaperDirectory(rows){
 $('.workspace').classList.toggle('paper-directory',true);$('#status').textContent='';
 $('#reader').innerHTML='<div class="paper-directory-heading"><p class="eyebrow">文献与材料</p><h1>文献身份证</h1><p>'+rows.length+' 篇文献 · 同一文献显示最新完成结果</p></div><div class="paper-cards">'+rows.map(r=>{
  const names=r.material_labels||[],summary=String(r.overview||'');
  return '<a class="paper-card" href="/paper/'+encodeURIComponent(r.job_id)+'"><div class="paper-card-meta"><span>'+esc(r.page_count?r.page_count+' 页':'材料来源')+'</span><time>'+esc((r.started_at||'').slice(0,10))+'</time></div><h2>'+esc(r.title)+'</h2><p class="paper-card-overview">'+esc(summary.length>230?summary.slice(0,230)+'…':summary)+'</p><div class="paper-card-materials">'+names.slice(0,4).map(x=>'<span>'+esc(x)+'</span>').join('')+(names.length>4?'<span>另 '+(names.length-4)+' 个</span>':'')+'</div><div class="paper-card-footer"><span>'+esc(r.major_count||0)+' 个研究对象 · '+esc(r.polymer_count||0)+' 个高分子 · '+esc(r.component_count||0)+' 个组分</span><strong>查看身份证 →</strong></div></a>';
 }).join('')+'</div>'+(!rows.length?'<div class="notice">完成的文献身份证会显示在这里。</div>':'');
}
async function post(url,v){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(v)});const value=await r.json();if(!r.ok)throw Error(value.error);return value}
$('#pdf').onchange=()=>$('#file-name').textContent=$('#pdf').files[0]?.name||'';
$('#generate').onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button[type="submit"]');button.disabled=true;$('#status').textContent='正在提交描述…';try{const v={text:$('#text').value.trim()},file=$('#pdf').files[0];if(!v.text&&!file)throw Error('TEXT_OR_PDF_REQUIRED');if(v.text&&file)throw Error('CHOOSE_TEXT_OR_PDF');if(file){v.pdf_base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file)})}const result=await post('/api/start',v);rememberTask(result.job_id);await loadJob(result.job_id);await refresh();$('#reader').scrollIntoView?.({behavior:'smooth',block:'start'})}catch(error){showError(error)}finally{button.disabled=false}};
$('#close-zoom').onclick=()=>$('#zoom').close();
async function init(){
 const path=location.pathname;document.querySelectorAll('header [data-area]').forEach(a=>{const area=path.startsWith('/paper')?'papers':path==='/knowledge'||path==='/library'?'knowledge':'workbench';if(a.dataset.area===area)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')});
 if(isLibrary()){$('#input-area').hidden=true;const params=new URLSearchParams(location.search||'');for(const k of ['q','kind','group','owner','sort','view','shared'])if(params.has(k))libraryState[k]=params.get(k);libraryState.offset=Math.max(0,Number(params.get('offset'))||0);await loadLibrary();setInterval(()=>refreshLibrary().catch(showError),10000);return}
 if(path==='/paper'){$('#input-area').hidden=true;$('.workspace').classList.toggle('paper-directory',true);$('#reader').innerHTML='<div class="notice">正在读取文献…</div>'}
 const query=location.search||'',value=key=>{const match=query.match(new RegExp('[?&]'+key+'=([^&]*)'));return match?decodeURIComponent(match[1]):null};
 if(path.startsWith('/paper/')){$('#input-area').hidden=true;await loadJob(decodeURIComponent(path.split('/')[2]),value('material'))}
 if(isWorkbench()){
  $('.workspace').classList.toggle('workbench-view',true);
  try{if(typeof localStorage!=='undefined')$('#text').value=localStorage.getItem('polymer-text-draft')||''}catch{}
  $('#text').oninput=()=>{try{if(typeof localStorage!=='undefined')localStorage.setItem('polymer-text-draft',$('#text').value)}catch{}};
  document.querySelectorAll('[data-example]').forEach(b=>b.onclick=()=>{$('#text').value=b.dataset.example;$('#text').oninput();$('#text').focus()});
  if(value('job'))await loadJob(value('job'));
 }
 await refresh();setInterval(()=>{if(!document.hidden)refresh().catch(showError)},5000);
}
init().catch(e=>$('#status').textContent=e.message);
