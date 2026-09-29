"use client";

import { Alert, Button, Input, Segmented, Select, Space, Table, Tabs, Tag, Tooltip, Typography, Empty } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeft, Beaker, Boxes, ChevronRight, FileSearch, Gauge, GitBranch, Link2, Network, Search, TableProperties, Workflow } from "lucide-react";
import { useMemo, useState } from "react";
import { Background, Controls, MarkerType, MiniMap, ReactFlow, type Edge, type Node, type NodeMouseHandler } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { CandidateData, Evidence, GraphPayload, PolymerEntity } from "../../types";
import { confidenceTag, displayPaperAuthors, displayPaperMeta, displayPaperTitle, polymerTypeLabel, sampleDisplayName, sampleKindLabel, systemPid, repeatUnitFor, warningLabels } from "../../utils/format";
import { Metric, NoResult, zhPagination } from "../../components/common";
import { PolymerStructure } from "../../components/PolymerStructure";
import { useExtraction } from "../../store/extraction";
import { useNavigate } from "react-router-dom";
import "./style.css";
const { Title, Text, Paragraph } = Typography;

function ResultsPage({ candidate, graphPayload, sourceFileName, sourceReferenceNo, sourceLabel, search, filter, pdfUrl, onExport, onSearch, onFilter, onEntity, onEvidence, onSample, onPolymer, onBack }: {
  candidate: CandidateData;
  graphPayload: GraphPayload | null;
  sourceFileName?: string;
  sourceReferenceNo?: string | null;
  sourceLabel: string;
  search: string;
  filter: string;
  pdfUrl: string;
  onExport: () => void;
  onSearch: (value: string) => void;
  onFilter: (value: string) => void;
  onEntity: (entity: PolymerEntity) => void;
  onEvidence: (evidence: Evidence) => void;
  onSample: (id: string) => void;
  onPolymer: (id: string) => void;
  onBack: () => void;
}) {
  const evidenceMap = useMemo(() => new Map(candidate.evidence.map((item) => [item.evidence_id, item])), [candidate]);
  const entities = candidate.polymer_entities.filter((entity) => {
    const query = search.trim().toLowerCase();
    const matches = !query || [entity.polymer_name, ...(entity.source_names || [])].join(" ").toLowerCase().includes(query);
    const sampleCount = candidate.samples.filter((sample) => sample.refers_to_entity === entity.entity_id).length;
    return matches && (filter === "all" || (filter === "sample" && sampleCount > 0) || (filter === "low" && (entity.confidence?.score || 0) < 0.8));
  });

  const columns: ColumnsType<PolymerEntity> = [
    { title: "聚合物名称", dataIndex: "polymer_name", key: "name", width: 300, render: (value, record) => <button className="name-link" onClick={() => onEntity(record)}><strong>{value}</strong><span>{record.entity_id}</span></button> },
    { title: "简称与原文名称", dataIndex: "source_names", key: "aliases", render: (names?: string[]) => <div className="tag-list">{(names || []).slice(0, 3).map((name) => <Tag key={name}>{name}</Tag>)}{(names || []).length > 3 && <Tag>+{(names || []).length - 3}</Tag>}</div> },
    { title: "样品数量", key: "samples", width: 105, render: (_, record) => { const samples = candidate.samples.filter((sample) => sample.refers_to_entity === record.entity_id); return samples.length ? <Button type="link" onClick={() => onSample(samples[0].sample_id)}>{samples.length}</Button> : <Text type="secondary">0</Text>; } },
    { title: "类型", key: "type", width: 120, render: (_, record) => candidate.samples.some((sample) => sample.refers_to_entity === record.entity_id && sample.sample_kind === "processed_material") ? <Tag color="blue">复合/加工材料</Tag> : <Tag>聚合物实体</Tag> },
    { title: "置信度", key: "confidence", width: 95, render: (_, record) => confidenceTag(record.confidence?.score) },
    { title: "操作", key: "action", width: 90, render: (_, record) => <Tooltip title="查看原文证据"><Button aria-label="查看实体证据" icon={<Link2 size={15} />} onClick={() => { const item = record.evidence_ids?.map((id) => evidenceMap.get(id)).find(Boolean); if (item) onEvidence(item); }} /></Tooltip> },
  ];

  return (
    <div className="page-stack upload-page results-page">
      <header className="upload-hero">
        <div className="upload-hero-main">
          <span className="upload-eyebrow">关系抽取 · 结果浏览</span>
          <Title level={2}>论文关系化抽取结果</Title>
          <Paragraph>沿论文 → 聚合物 → 样品 → 性质逐层浏览；所有关系均来自候选 JSON 中的对象 ID。</Paragraph>
        </div>
        <div className="upload-hero-side">
          <span className="svc-dot on"><i />{sourceLabel}</span>
          <Space><Button icon={<ArrowLeft size={15} />} onClick={onBack}>返回结果列表</Button><Button href={pdfUrl} target="_blank" icon={<FileSearch size={15} />}>原文</Button><Button className="start-btn" type="primary" onClick={onExport}>导出数据</Button></Space>
        </div>
      </header>

      <section className="ucard paper-summary">
        <div className="paper-main"><Text>文献 · {sourceLabel}</Text><Title level={4}>{displayPaperTitle(candidate.paper, sourceReferenceNo || "未识别题名")}</Title><div className="paper-fields"><span><b>作者</b>{displayPaperAuthors(candidate.paper.authors)}</span><span><b>DOI</b>{candidate.paper.doi || "未识别"}</span><span><b>来源编号</b>{sourceReferenceNo || candidate.paper.ref_no}</span>{sourceFileName && <span><b>上传文件</b>{sourceFileName}</span>}</div></div>
        <div className="paper-badge"><FileSearch size={28} /><span>{sourceLabel}</span><strong>{candidate.paper.year || "--"}</strong></div>
      </section>

      <section className="ucard results-metrics-card">
        <div className="ucard-head"><div><h3><span className="title-icon"><Boxes size={15} /></span>抽取规模总览</h3><p>{displayPaperMeta(candidate.paper)}</p></div></div>
      <div className="metric-strip results-metrics">
        <Metric icon={<Boxes size={19} />} label="聚合物实体" value={candidate.polymer_entities.length} tone="blue" />
        <Metric icon={<Beaker size={19} />} label="具体样品" value={candidate.samples.length} tone="violet" />
        <Metric icon={<Gauge size={19} />} label="性质观测" value={candidate.property_observations.length} tone="cyan" />
        <Metric icon={<GitBranch size={19} />} label="加工步骤" value={candidate.process_steps.length} tone="orange" />
        <Metric icon={<FileSearch size={19} />} label="原文证据" value={candidate.evidence.length} tone="green" />
      </div>
      </section>

      <section className="ucard result-browser-card">
        <div className="ucard-head"><div><h3><span className="title-icon"><Network size={15} /></span>关系浏览</h3><p>聚合物目录 · 知识图谱 · 数据表</p></div></div>
      <div className="result-browser">
        <Tabs
          defaultActiveKey="hierarchy"
          items={[
            {
              key: "hierarchy",
              label: <span className="mode-tab"><Workflow size={15} />聚合物目录</span>,
              children: <PolymerDirectory candidate={candidate} entities={entities} search={search} filter={filter} onSearch={onSearch} onFilter={onFilter} onEntity={onEntity} onPolymer={onPolymer} />,
            },
            {
              key: "graph",
              label: <span className="mode-tab"><Network size={15} />知识图谱</span>,
              children: <KnowledgeGraph candidate={candidate} payload={graphPayload} onEntity={onEntity} onEvidence={onEvidence} onSample={onSample} />,
            },
            {
              key: "tables",
              label: <span className="mode-tab"><TableProperties size={15} />数据表</span>,
              children: <div className="flat-data-view">
                <div className="panel-heading responsive"><div><Title level={4}>识别到的聚合物</Title><Text>保留传统表格视图，便于检索、排序和批量审核</Text></div><Space wrap><Input value={search} onChange={(event) => onSearch(event.target.value)} prefix={<Search size={15} />} placeholder="搜索名称或缩写" allowClear /><Select value={filter} onChange={onFilter} options={[{ value: "all", label: "全部实体" }, { value: "sample", label: "仅有关联样品" }, { value: "low", label: "低置信度" }]} /></Space></div>
                <Table rowKey="entity_id" columns={columns} dataSource={entities} pagination={zhPagination({ pageSize: 7 })} scroll={{ x: 920 }} />
                <div className="table-section-heading"><div><Title level={4}>样品清单</Title><Text>点击样品进入完整详情</Text></div><Tag color="blue">{candidate.samples.length} 个样品</Tag></div>
                <Table rowKey="sample_id" pagination={zhPagination()} scroll={{ x: 820 }} dataSource={candidate.samples} columns={[
                  { title: "样品", key: "sample", render: (_, item) => <div className="primary-cell"><strong>{sampleDisplayName(item)}</strong><span>{item.sample_id}</span></div> },
                  { title: "聚合物/材料", dataIndex: "polymer_name", key: "polymer" },
                  { title: "样品类型", dataIndex: "sample_kind", key: "kind", render: sampleKindLabel },
                  { title: "状态", dataIndex: "state_description", key: "state", render: (value) => value || <Text type="secondary">原文未明确</Text> },
                  { title: "性质数", key: "properties", width: 85, render: (_, item) => candidate.property_observations.filter((property) => property.sample_id === item.sample_id).length },
                  { title: "操作", key: "action", width: 90, render: (_, item) => <Button type="link" onClick={() => onSample(item.sample_id)}>查看详情</Button> },
                ]} />
              </div>,
            },
          ]}
        />
      </div>
      </section>

      {candidate.warnings.length > 0 && (
        <section className="ucard warning-panel">
          <div className="ucard-head"><div><h3><span className="title-icon"><FileSearch size={15} /></span>待人工复核</h3><p>以下为流水线自动标记的可疑项，共 {candidate.warnings.length} 项 · 结论不可直接入库</p></div></div>
          <div className="warning-grid">{candidate.warnings.slice(0, 6).map((warning, index) => (
            <div className="warning-card" key={`${warning.code}-${index}`}>
              <span className="warning-index">{String(index + 1).padStart(2, "0")}</span>
              <span className="warning-body"><strong>{warningLabels[warning.code] || warning.code}</strong><small>阶段 · {warning.stage}</small></span>
              <Tag color="warning">待复核</Tag>
            </div>
          ))}</div>
        </section>
      )}
    </div>
  );
}
function PolymerDirectory({ candidate, entities, search, filter, onSearch, onFilter, onEntity, onPolymer }: {
  candidate: CandidateData;
  entities: PolymerEntity[];
  search: string;
  filter: string;
  onSearch: (value: string) => void;
  onFilter: (value: string) => void;
  onEntity: (entity: PolymerEntity) => void;
  onPolymer: (id: string) => void;
}) {
  return <div className="polymer-directory-view">
    <div className="polymer-directory-toolbar"><div><strong>识别到 {entities.length} 个聚合物</strong><span>PID 由规范名称稳定生成；结构和 CU formula 只在有可靠依据时展示。</span></div><Space wrap><Input value={search} onChange={(event) => onSearch(event.target.value)} prefix={<Search size={15} />} placeholder="搜索聚合物" allowClear /><Select value={filter} onChange={onFilter} options={[{ value: "all", label: "全部实体" }, { value: "sample", label: "仅有关联样品" }, { value: "low", label: "低置信度" }]} /></Space></div>
    {entities.length ? <div className="polymer-result-list">{entities.map((entity, index) => {
      const samples = candidate.samples.filter((sample) => sample.refers_to_entity === entity.entity_id);
      const repeatUnit = repeatUnitFor(entity);
      return <article className="polymer-result-card" key={entity.entity_id}>
        <div className="polymer-result-heading"><button onClick={() => onPolymer(entity.entity_id)}><b>{index + 1}.</b> {entity.polymer_name}</button><Space size={5}>{confidenceTag(entity.confidence?.score)}<Tooltip title="查看实体归一与原文证据"><Button aria-label="查看聚合物证据" icon={<Link2 size={14} />} onClick={() => onEntity(entity)} /></Tooltip></Space></div>
        <div className="polymer-result-meta"><span><b>PID</b>{systemPid(entity)}</span><span><b>CU formula</b>{repeatUnit.formula || "待补充"}</span><button onClick={() => onPolymer(entity.entity_id)}>{samples.length} samples <ChevronRight size={14} /></button><Tag>{polymerTypeLabel(entity.polymer_type, entity.polymer_name)}</Tag></div>
        <button className="polymer-structure-button" onClick={() => onPolymer(entity.entity_id)} aria-label={`查看 ${entity.polymer_name} 的样品`}><PolymerStructure entity={entity} compact /></button>
      </article>;
    })}</div> : <Empty description="没有符合筛选条件的聚合物" />}
  </div>;
}
function buildGraphPayload(candidate: CandidateData): GraphPayload {
  const paperId = `paper:${candidate.paper.ref_no}`;
  const nodes: GraphNodePayload[] = [{ id: paperId, type: "paper", label: candidate.paper.title, data: candidate.paper as unknown as Record<string, unknown> }];
  const edges: GraphPayload["edges"] = [];
  candidate.polymer_entities.forEach((entity) => {
    nodes.push({ id: entity.entity_id, type: "polymer", label: entity.polymer_name, data: entity as unknown as Record<string, unknown> });
    edges.push({ id: `${paperId}:contains:${entity.entity_id}`, source: paperId, target: entity.entity_id, type: "contains_polymer", label: "识别" });
  });
  candidate.samples.forEach((sample) => {
    nodes.push({ id: sample.sample_id, type: "sample", label: sampleDisplayName(sample), data: sample as unknown as Record<string, unknown> });
    edges.push({ id: `${sample.refers_to_entity}:sample:${sample.sample_id}`, source: sample.refers_to_entity, target: sample.sample_id, type: "has_sample", label: "对应样品" });
  });
  candidate.process_steps.forEach((step) => {
    nodes.push({ id: step.step_id, type: "process", label: step.process_type, data: step as unknown as Record<string, unknown> });
    step.input_sample_ids.forEach((id) => edges.push({ id: `${id}:input:${step.step_id}`, source: id, target: step.step_id, type: "process_input", label: "输入" }));
    step.output_sample_ids.forEach((id) => edges.push({ id: `${step.step_id}:output:${id}`, source: step.step_id, target: id, type: "process_output", label: "生成" }));
  });
  candidate.property_observations.forEach((property) => {
    const unit = property.unit_normalized || property.unit_raw || "";
    nodes.push({ id: property.property_id, type: "property", label: `${property.property_name_raw}: ${property.value_raw} ${unit}`.trim(), data: property as unknown as Record<string, unknown> });
    edges.push({ id: `${property.sample_id}:property:${property.property_id}`, source: property.sample_id, target: property.property_id, type: "has_property", label: "测得" });
  });
  candidate.characterizations.forEach((item) => {
    nodes.push({ id: item.characterization_id, type: "characterization", label: item.method_normalized || item.method_raw, data: item as unknown as Record<string, unknown> });
    item.sample_ids?.forEach((id) => edges.push({ id: `${id}:characterization:${item.characterization_id}`, source: id, target: item.characterization_id, type: "characterized_by", label: "表征" }));
  });
  const nodeCounts = nodes.reduce<Record<string, number>>((counts, node) => ({ ...counts, [node.type]: (counts[node.type] || 0) + 1 }), {});
  return { nodes, edges, stats: { node_counts: nodeCounts, edge_count: edges.length } };
}
type FlowNodeData = { kind: GraphNodePayload["type"]; source: GraphNodePayload; title: string; subtitle: string; label: React.ReactNode };
type FlowNode = Node<FlowNodeData>;
function KnowledgeGraph({ candidate, payload, onEntity, onEvidence, onSample }: { candidate: CandidateData; payload: GraphPayload | null; onEntity: (entity: PolymerEntity) => void; onEvidence: (evidence: Evidence) => void; onSample: (id: string) => void }) {
  const [scope, setScope] = useState<"core" | "all">("core");
  const graph = payload || buildGraphPayload(candidate);
  const evidenceMap = useMemo(() => new Map(candidate.evidence.map((item) => [item.evidence_id, item])), [candidate]);
  const linkedPolymerIds = new Set(graph.edges.filter((edge) => edge.type === "has_sample").map((edge) => edge.source));
  const visibleSourceNodes = scope === "all" ? graph.nodes : graph.nodes.filter((node) => node.type !== "polymer" || linkedPolymerIds.has(node.id));
  const visibleIds = new Set(visibleSourceNodes.map((node) => node.id));
  const activeEdges = graph.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target));
  const typeLabels: Record<GraphNodePayload["type"], string> = { paper: "SOURCE PAPER", polymer: "POLYMER ENTITY", sample: "SAMPLE STATE", process: "PROCESS EVENT", property: "PROPERTY", characterization: "CHARACTERIZATION" };
  const palette = {
    paper: { x: 20, color: "#0066CC", bg: "#FFFFFF" },
    polymer: { x: 285, color: "#7B5AA6", bg: "#FFFFFF" },
    sample: { x: 550, color: "#008C95", bg: "#FFFFFF" },
    process: { x: 815, color: "#D27A16", bg: "#FFFFFF" },
    property: { x: 1080, color: "#178A63", bg: "#FFFFFF" },
    characterization: { x: 1345, color: "#66788A", bg: "#FFFFFF" },
  } as const;

  const gap = 112;
  const positionY = new Map<string, number>();
  const nodesOf = (type: GraphNodePayload["type"]) => visibleSourceNodes.filter((node) => node.type === type);
  const placeColumn = (items: GraphNodePayload[], desired: (item: GraphNodePayload, index: number) => number) => {
    const ranked = items.map((item, index) => ({ item, desired: desired(item, index) })).sort((a, b) => a.desired - b.desired || a.item.label.localeCompare(b.item.label));
    let previous = -gap;
    ranked.forEach(({ item, desired: target }) => {
      const y = Math.max(24, target, previous + gap);
      positionY.set(item.id, y);
      previous = y;
    });
  };
  const average = (values: number[], fallback: number) => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : fallback;

  const polymerNodes = nodesOf("polymer");
  const polymerRank = new Map(polymerNodes.sort((a, b) => a.label.localeCompare(b.label)).map((node, index) => [node.id, index]));
  const sampleNodes = nodesOf("sample").sort((a, b) => {
    const parentA = activeEdges.find((edge) => edge.type === "has_sample" && edge.target === a.id)?.source || "";
    const parentB = activeEdges.find((edge) => edge.type === "has_sample" && edge.target === b.id)?.source || "";
    return (polymerRank.get(parentA) ?? 999) - (polymerRank.get(parentB) ?? 999) || a.label.localeCompare(b.label);
  });
  placeColumn(sampleNodes, (_, index) => 24 + index * gap);
  placeColumn(polymerNodes, (node, index) => {
    const childY = activeEdges.filter((edge) => edge.type === "has_sample" && edge.source === node.id).map((edge) => positionY.get(edge.target)).filter((value): value is number => value !== undefined);
    return average(childY, 24 + index * gap);
  });
  const paperNodes = nodesOf("paper");
  placeColumn(paperNodes, () => average(polymerNodes.map((node) => positionY.get(node.id)).filter((value): value is number => value !== undefined), 140));
  const processNodes = nodesOf("process");
  placeColumn(processNodes, (node, index) => {
    const linkedY = activeEdges.filter((edge) => (edge.source === node.id || edge.target === node.id) && ["process_input", "process_output"].includes(edge.type)).map((edge) => positionY.get(edge.source === node.id ? edge.target : edge.source)).filter((value): value is number => value !== undefined);
    return average(linkedY, 24 + index * gap);
  });
  const propertyNodes = nodesOf("property");
  placeColumn(propertyNodes, (node, index) => {
    const linkedY = activeEdges.filter((edge) => edge.target === node.id).map((edge) => positionY.get(edge.source)).filter((value): value is number => value !== undefined);
    return average(linkedY, 24 + index * gap);
  });
  const characterizationNodes = nodesOf("characterization");
  placeColumn(characterizationNodes, (node, index) => {
    const linkedY = activeEdges.filter((edge) => edge.target === node.id).map((edge) => positionY.get(edge.source)).filter((value): value is number => value !== undefined);
    return average(linkedY, 24 + index * gap);
  });

  const nodes: FlowNode[] = visibleSourceNodes.map((source) => {
    const style = palette[source.type];
    return {
      id: source.id,
      position: { x: style.x, y: positionY.get(source.id) || 24 },
      data: { kind: source.type, source, title: source.label, subtitle: source.id, label: <div className="graph-node-copy"><span className="graph-node-type"><i style={{ background: style.color }} />{typeLabels[source.type]}</span><strong>{source.label}</strong><small>{source.id}</small></div> },
      style: { width: source.type === "paper" ? 240 : 208, minHeight: 84, border: "1px solid #D5DDE6", borderLeft: `4px solid ${style.color}`, borderRadius: 8, background: style.bg, color: "#172033", padding: "12px 13px 12px 14px", fontSize: 13, boxShadow: "0 8px 22px rgba(16,24,40,.08)" },
      ariaLabel: `${source.type}: ${source.label}`,
    };
  });
  const edgeColors: Record<string, string> = { contains_polymer: "#4F85BB", has_sample: "#8874A8", process_input: "#C18443", process_output: "#C18443", has_property: "#4E8F74", characterized_by: "#7A8998" };
  const edges: Edge[] = activeEdges.map((edge) => {
    const color = edgeColors[edge.type] || "#8794a6";
    return { id: edge.id, source: edge.source, target: edge.target, label: activeEdges.length <= 42 ? edge.label : undefined, type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color }, style: { stroke: color, strokeWidth: 1.7, opacity: .82 }, labelStyle: { fill: "#526071", fontSize: 10, fontWeight: 650 }, labelBgStyle: { fill: "#ffffff", fillOpacity: .96 }, labelBgPadding: [5, 4], labelBgBorderRadius: 4, interactionWidth: 18 };
  });
  const handleNodeClick: NodeMouseHandler<FlowNode> = (_, node) => {
    const source = node.data.source;
    if (source.type === "sample") return onSample(source.id);
    if (source.type === "polymer") {
      const entity = candidate.polymer_entities.find((item) => item.entity_id === source.id);
      if (entity) onEntity(entity);
      return;
    }
    const evidenceIds = source.data.evidence_ids;
    if (Array.isArray(evidenceIds)) {
      const item = evidenceIds.map((id) => evidenceMap.get(String(id))).find(Boolean);
      if (item) onEvidence(item);
    }
  };

  return <div className="graph-view">
    <div className="graph-toolbar"><div><strong>样品中心实验知识图谱</strong><span>从文献来源到聚合物、样品状态、工艺事件和观测结果；节点位置按真实关系自动对齐</span></div><Segmented value={scope} onChange={(value) => setScope(value as "core" | "all")} options={[{ label: "关系主干", value: "core" }, { label: "全部实体", value: "all" }]} /></div>
    <div className="graph-legend">{Object.entries(palette).map(([key, value]) => <span key={key}><i style={{ background: value.color }} />{{ paper: "论文", polymer: "聚合物", sample: "样品状态", process: "工艺事件", property: "性质观测", characterization: "表征" }[key as keyof typeof palette]}</span>)}<b>{nodes.length} 节点 · {edges.length} 关系</b></div>
    {!candidate.property_observations.length && <Alert className="graph-alert" type="warning" showIcon message="本次抽取没有生成性质节点" description="图谱仍完整展示聚合物、样品、工艺和表征关系；性质阶段已标记为待重跑或人工复核。" />}
    <div className="graph-stage-headings"><span>文献来源</span><span>聚合物实体</span><span>样品状态</span><span>工艺事件</span><span>性质观测</span><span>表征方法</span></div>
    <div className="graph-canvas"><ReactFlow nodes={nodes} edges={edges} onNodeClick={handleNodeClick} fitView fitViewOptions={{ padding: 0.06, maxZoom: 1.08 }} minZoom={0.24} maxZoom={1.7} nodesDraggable nodesConnectable={false} elementsSelectable onlyRenderVisibleElements proOptions={{ hideAttribution: true }}><MiniMap pannable zoomable maskColor="rgba(247,249,251,.78)" nodeStrokeWidth={2} nodeColor={(node) => palette[(node.data as FlowNodeData).kind].color} /><Controls showInteractive={false} /><Background color="#DDE3EA" gap={30} size={1} /></ReactFlow></div>
  </div>;
}


export default function ResultsRoute() {
  const s = useExtraction();
  const navigate = useNavigate();
  if (!s.mounted) return null;
  if (!s.candidate) {
    return (
      <div className="page-stack">
        <NoResult onUpload={() => navigate("/upload")} onSample={s.loadSample} />
      </div>
    );
  }
  const sourceReferenceNo =
    s.dataSource === "batch" ? s.selectedBatch?.ref_no
    : s.job?.source_reference_no || s.job?.file_name?.replace(/\.pdf$/i, "");
  return (
    <div className="page-stack">
      <ResultsPage
        candidate={s.candidate} search={s.entitySearch} filter={s.entityFilter}
        sourceFileName={s.dataSource === "task" ? s.job?.file_name : undefined}
        sourceReferenceNo={sourceReferenceNo}
        sourceLabel={s.dataSource === "batch" ? "离线批处理归档" : s.dataSource === "sample" ? "内置示例" : "网页上传任务"}
        onSearch={s.setEntitySearch} onFilter={s.setEntityFilter}
        onEntity={s.setSelectedEntity} onEvidence={s.setSelectedEvidence}
        graphPayload={s.graphPayload} onBack={s.returnToResultList}
        pdfUrl={s.pdfUrl} onExport={s.downloadJson}
        onPolymer={s.openPolymerPage} onSample={s.openSamplePage}
      />
    </div>
  );
}
