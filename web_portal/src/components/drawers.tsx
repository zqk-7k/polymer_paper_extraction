import { Alert, Button, Descriptions, Drawer, Empty, Space, Table, Tabs, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Boxes, FileSearch, FlaskConical, Link2, LoaderCircle, TableProperties, Workflow } from "lucide-react";
import { useState } from "react";
import { evidencePageUrl } from "../evidence-urls.mjs";
import type { CandidateData, Evidence, PolyInfoComparison, PolyInfoProperty, PolymerEntity, PropertyObservation } from "../types";
import { confidenceTag, zhPagination } from "./common";
import { sampleDisplayName, sampleKindLabel } from "../utils/format";
const { Title, Text, Paragraph } = Typography;

export function EvidenceVisual({ evidence, pdfUrl }: { evidence: Evidence; pdfUrl: string }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const page = evidence.page ?? 0;
  const pageImageUrl = evidencePageUrl(pdfUrl, page);
  const sourceWidth = 1000;
  const sourceHeight = 1000;
  const values = Array.isArray(evidence.bbox) ? evidence.bbox.map(Number) : [];
  const hasBox = values.length === 4 && values.every(Number.isFinite) && values[2] > values[0] && values[3] > values[1];
  const x0 = hasBox ? Math.max(0, Math.min(sourceWidth, values[0])) : 0;
  const y0 = hasBox ? Math.max(0, Math.min(sourceHeight, values[1])) : 0;
  const x1 = hasBox ? Math.max(x0 + 1, Math.min(sourceWidth, values[2])) : sourceWidth;
  const y1 = hasBox ? Math.max(y0 + 1, Math.min(sourceHeight, values[3])) : sourceHeight;
  const boxWidth = x1 - x0;
  const boxHeight = y1 - y0;
  const boxStyle: React.CSSProperties = {
    left: `${(x0 / sourceWidth) * 100}%`,
    top: `${(y0 / sourceHeight) * 100}%`,
    width: `${(boxWidth / sourceWidth) * 100}%`,
    height: `${(boxHeight / sourceHeight) * 100}%`,
  };
  const cropImageStyle: React.CSSProperties = {
    width: `${(sourceWidth / boxWidth) * 100}%`,
    left: `${(-x0 / boxWidth) * 100}%`,
    top: `${(-y0 / boxHeight) * 100}%`,
  };

  if (failedUrl === pageImageUrl) return <div className="notice-card warn"><span className="notice-icon"><FileSearch size={16} /></span><div className="notice-body"><strong>证据页图像暂不可用</strong><span>后端页图渲染失败（503），仍可直接打开 PDF 对应页核对证据。</span></div><Button size="small" onClick={() => setFailedUrl(null)}>重试</Button></div>;

  return <section className="evidence-visual-panel">
    <div className="evidence-visual-heading"><div><strong>原文定位</strong><span>红框为抽取记录保存的 bbox 坐标</span></div></div>
    <div className="evidence-page-preview">
      <img src={pageImageUrl} alt={`原文第 ${page + 1} 页证据定位`} onError={() => setFailedUrl(pageImageUrl)} />
      {hasBox && <i className="evidence-bbox" style={boxStyle}><span>bbox</span></i>}
    </div>
    {hasBox && <div className="evidence-crop-section"><div><strong>证据区域放大</strong><span>{values.join(", ")}</span></div><div className="evidence-crop-frame" style={{ aspectRatio: `${boxWidth} / ${boxHeight}` }}><img src={pageImageUrl} alt="根据 bbox 裁剪的原文证据区域" style={cropImageStyle} /><i /></div></div>}
  </section>;
}
export function extractionPropertyValue(item?: PropertyObservation | null) {
  if (!item) return "-";
  return `${item.value_raw ?? "-"} ${item.unit_normalized || item.unit_raw || ""}`.trim();
}
export function displayApiText(value: unknown, fallback = "-"): string {
  if (value === null || value === undefined || value === "") return fallback;
  if (Array.isArray(value)) {
    const parts = value.map((item) => displayApiText(item, "")).filter(Boolean);
    return parts.join("；") || fallback;
  }
  if (typeof value === "object") {
    const parts = Object.entries(value as Record<string, unknown>)
      .map(([key, child]) => {
        const text = displayApiText(child, "");
        return text ? `${key.replaceAll("_", " ")}: ${text}` : "";
      })
      .filter(Boolean);
    return parts.join("；") || fallback;
  }
  return String(value);
}
export function alignmentStatusTag(status: PolyInfoComparison["property_alignment"][number]["status"]) {
  const config = {
    matched: { color: "success", label: "数值一致" },
    value_diff: { color: "error", label: "同名但值不同" },
    polyinfo_only: { color: "warning", label: "仅 PoLyInfo" },
    extraction_only: { color: "blue", label: "仅最新批处理" },
  }[status];
  return <Tag color={config.color}>{config.label}</Tag>;
}
export function PolyInfoComparisonDrawer({ comparison, loading, onClose }: { comparison: PolyInfoComparison | null; loading: boolean; onClose: () => void }) {
  const metricColumns: ColumnsType<PolyInfoComparison["metrics"][number]> = [
    { title: "比较维度", dataIndex: "label", key: "label", width: 160, render: (value) => <strong>{value}</strong> },
    { title: "PoLyInfo", dataIndex: "polyinfo", key: "polyinfo", width: 100, align: "right", render: (value) => <b className="numeric-cell polyinfo-number">{value}</b> },
    { title: "所选批处理", dataIndex: "extraction", key: "extraction", width: 118, align: "right", render: (value) => <b className="numeric-cell extraction-number">{value}</b> },
    { title: "差值", key: "delta", width: 90, align: "right", render: (_, item) => { const delta = item.extraction - item.polyinfo; return <Tag color={delta === 0 ? "success" : delta > 0 ? "blue" : "warning"}>{delta > 0 ? `+${delta}` : delta}</Tag>; } },
    { title: "解释", dataIndex: "interpretation", key: "interpretation" },
  ];
  const alignmentColumns: ColumnsType<PolyInfoComparison["property_alignment"][number]> = [
    { title: "判定", dataIndex: "status", key: "status", width: 126, render: alignmentStatusTag },
    { title: "统一性质名", dataIndex: "canonical_name", key: "name", width: 210, render: (value) => <strong>{value}</strong> },
    { title: "PoLyInfo 样品", key: "piSample", width: 150, render: (_, item) => item.polyinfo?.sample_id || "-" },
    { title: "PoLyInfo 值", key: "piValue", width: 150, render: (_, item) => item.polyinfo ? <span className="comparison-value polyinfo-number">{displayApiText(item.polyinfo.value)} {displayApiText(item.polyinfo.unit, "")}</span> : "-" },
    { title: "批处理样品", key: "webSample", width: 110, render: (_, item) => item.extraction?.sample_id || "-" },
    { title: "批处理值", key: "webValue", width: 150, render: (_, item) => item.extraction ? <span className="comparison-value extraction-number">{extractionPropertyValue(item.extraction)}</span> : "-" },
    { title: "方法与条件", key: "context", render: (_, item) => <div className="comparison-context"><span>{displayApiText(item.polyinfo?.method || (item.extraction as unknown as Record<string, unknown> | null)?.determination_method_raw, "方法未记录")}</span><small>{displayApiText(item.polyinfo?.condition, "条件见批处理证据记录或未报告")}</small></div> },
  ];
  const polyInfoSampleColumns: ColumnsType<PolyInfoComparison["polyinfo"]["samples"][number]> = [
    { title: "SAMPLE ID", dataIndex: "sample_id", key: "sample", width: 190 },
    { title: "PID", dataIndex: "polymer_id", key: "pid", width: 120 },
    { title: "材料类型", dataIndex: "material_type", key: "material", render: (value: string[]) => value?.join("；") || "-" },
    { title: "聚合物类型", dataIndex: "polymer_type", key: "type", width: 130 },
    { title: "性质", dataIndex: "property_count", key: "properties", width: 80, align: "right" },
    { title: "工艺字段", dataIndex: "process_count", key: "process", width: 90, align: "right" },
  ];
  const extractionSampleColumns: ColumnsType<CandidateData["samples"][number]> = [
    { title: "SAMPLE ID", dataIndex: "sample_id", key: "sample", width: 120 },
    { title: "绑定实体", dataIndex: "refers_to_entity", key: "entity", width: 120 },
    { title: "样品名称", key: "name", render: (_, item) => sampleDisplayName(item) },
    { title: "样品类型", dataIndex: "sample_kind", key: "kind", width: 140, render: sampleKindLabel },
    { title: "状态", dataIndex: "state_description", key: "state", render: (value) => value || "原文未明确报告" },
  ];
  const processColumns: ColumnsType<PolyInfoComparison["polyinfo"]["processes"][number]> = [
    { title: "SAMPLE ID", dataIndex: "sample_id", key: "sample", width: 190 },
    { title: "字段", dataIndex: "kind", key: "kind", width: 170 },
    { title: "PoLyInfo 内容", dataIndex: "value", key: "value", render: displayApiText },
  ];

  const overview = comparison && <div className="comparison-tab">
    <div className="comparison-heading"><div><Text className="page-meta">{comparison.ref_no}</Text><Title level={4}>{comparison.polyinfo.reference.journal || "PoLyInfo 文献记录"}</Title><Paragraph>{comparison.polyinfo.reference.doi || "无 DOI"} · {comparison.polyinfo.reference.year || "年份未记录"}</Paragraph></div><Space wrap><Tag color="blue">PoLyInfo: {comparison.polyinfo.group}</Tag>{comparison.extraction ? <Tag color="success">匹配批次 {comparison.extraction.collection_id}</Tag> : <Tag color="warning">本批次无结果</Tag>}</Space></div>
    {!comparison.extraction && <Alert type="warning" showIcon message="所选批处理没有可比较结果" description="该 reference_no 不在当前网页所选批次中；这里只展示 PoLyInfo 原始记录。" />}
    {comparison.extraction && <Alert type="info" showIcon message={comparison.message} description="样品数量和实体数量受建模层级影响，不能直接当作准确率；逐性质表才用于判断具体缺失、额外抽取或数值冲突。" />}
    {comparison.extraction && comparison.alignment_stats && <section className="single-paper-quality">
      <div className="single-paper-quality-heading"><div><strong>单篇论文评价指标</strong><span>锚点一致性衡量与 PoLyInfo 的逐值吻合；结构完整性只检查字段和关系是否存在。</span></div><Tag color="blue">PAPER LEVEL</Tag></div>
      <div className="single-paper-score-grid">
        <article className="anchor-score primary"><span>锚点 F1</span><b>{(comparison.alignment_stats.f1 * 100).toFixed(1)}%</b><small>Precision 与 Recall 的调和平均</small></article>
        <article className="anchor-score"><span>Precision</span><b>{(comparison.alignment_stats.precision * 100).toFixed(1)}%</b><small>抽取记录中精确匹配的比例</small></article>
        <article className="anchor-score"><span>Recall</span><b>{(comparison.alignment_stats.recall * 100).toFixed(1)}%</b><small>PoLyInfo 锚点中被恢复的比例</small></article>
        <article><span>样品绑定</span><b>{(comparison.extraction.quality.sample_binding_coverage * 100).toFixed(1)}%</b><small>{comparison.extraction.quality.sample_bound}/{comparison.extraction.quality.properties} 条性质</small></article>
        <article><span>证据绑定</span><b>{(comparison.extraction.quality.evidence_coverage * 100).toFixed(1)}%</b><small>{comparison.extraction.quality.evidence_bound}/{comparison.extraction.quality.properties} 条性质</small></article>
        <article><span>单位完整</span><b>{(comparison.extraction.quality.unit_completeness * 100).toFixed(1)}%</b><small>{comparison.extraction.quality.unit_complete}/{comparison.extraction.quality.properties} 条性质</small></article>
        <article><span>条件覆盖</span><b>{(comparison.extraction.quality.condition_coverage * 100).toFixed(1)}%</b><small>{comparison.extraction.quality.condition_bound}/{comparison.extraction.quality.properties} 条性质</small></article>
      </div>
    </section>}
    {comparison.alignment_stats && <div className="alignment-summary"><span className="matched"><b>{comparison.alignment_stats.matched || 0}</b>数值一致</span><span className="different"><b>{comparison.alignment_stats.value_diff || 0}</b>同名值不同</span><span className="pi-only"><b>{comparison.alignment_stats.polyinfo_only || 0}</b>仅 PoLyInfo</span><span className="web-only"><b>{comparison.alignment_stats.extraction_only || 0}</b>仅所选批处理</span></div>}
    <Table rowKey="key" className="comparison-metric-table" columns={metricColumns} dataSource={comparison.metrics} pagination={zhPagination()} size="middle" />
    <div className="comparison-notes"><strong>本页应怎样解读</strong><p>PoLyInfo 是样品记录参考，不自动等于全文 gold truth。批处理多出的内容可能是有效补充，也可能是错绑；PoLyInfo 缺少证据链，因此所有争议项最终仍需回到 PDF 和 bbox 证据裁决。</p></div>
  </div>;

  const identity = comparison && <div className="comparison-tab">
    <div className="source-identity-grid">
      <section><div className="comparison-section-title"><strong>PoLyInfo 聚合物</strong><span>{comparison.polyinfo.polymers.length} PID</span></div>{comparison.polyinfo.polymers.map((polymer) => <article className="polyinfo-identity-card" key={polymer.polymer_id}>{polymer.structure_image ? <img src={polymer.structure_image} alt={`${polymer.polymer_id} 重复单元结构`} /> : <div className="polyinfo-structure-empty"><FlaskConical size={22} />无结构图</div>}<div><b>{polymer.polymer_id}</b><strong>{polymer.polymer_names.join("；") || "名称未记录"}</strong><span>{polymer.cu_formula || "CU formula 未记录"} · {polymer.polymer_type || "类型未记录"}</span><small>{polymer.sample_ids.length} samples</small></div></article>)}</section>
      <section><div className="comparison-section-title"><strong>所选批处理聚合物实体</strong><span>{comparison.extraction?.polymer_entities.length || 0} entities</span></div>{comparison.extraction?.polymer_entities.map((entity) => <article className="extraction-identity-card" key={entity.entity_id}><div className="entity-mark"><Boxes size={20} /></div><div><b>{entity.entity_id}</b><strong>{entity.polymer_name}</strong><span>{entity.source_names?.slice(0, 3).join("；") || "无原文别名"}</span><small>{Math.round((entity.confidence?.score || 0) * 100)}% confidence</small></div></article>) || <Empty description="本批次无抽取实体" />}</section>
    </div>
    <div className="comparison-section-title table-title"><strong>PoLyInfo 样品记录</strong><span>每个 JSON 对应一个样品记录</span></div><Table rowKey="sample_id" columns={polyInfoSampleColumns} dataSource={comparison.polyinfo.samples} pagination={zhPagination({ pageSize: 8, hideOnSinglePage: true })} scroll={{ x: 900 }} />
    <div className="comparison-section-title table-title"><strong>所选批处理样品状态</strong><span>样品可表示合成批次、加工态和状态变化</span></div><Table rowKey="sample_id" columns={extractionSampleColumns} dataSource={comparison.extraction?.samples || []} pagination={zhPagination({ pageSize: 8, hideOnSinglePage: true })} scroll={{ x: 880 }} />
  </div>;

  const properties = comparison && <div className="comparison-tab"><Alert type="warning" showIcon message="一致表示名称、单位换算和数值相符，不代表样品绑定已自动验证" description="同一篇论文可能同时包含多个聚合物和状态；样品归属仍需结合原文证据检查。" /><Table rowKey={(item) => `${item.status}:${item.polyinfo?.id || item.extraction?.property_id}`} className="property-alignment-table" columns={alignmentColumns} dataSource={comparison.property_alignment} pagination={zhPagination({ pageSize: 12, showSizeChanger: false })} scroll={{ x: 1260 }} /></div>;

  const rawRecords = comparison && <div className="comparison-tab"><div className="comparison-section-title"><strong>PoLyInfo 工艺与制样字段</strong><span>这些是原始字段值，不代表已恢复为有顺序的过程事件图</span></div><Table rowKey={(item, index) => `${item.sample_id}:${item.kind}:${index}`} columns={processColumns} dataSource={comparison.polyinfo.processes} pagination={zhPagination({ pageSize: 10, hideOnSinglePage: true })} /><div className="comparison-section-title table-title"><strong>PoLyInfo 全部性质记录</strong><span>{comparison.polyinfo.properties.length} 条数值观测</span></div><Table rowKey="id" columns={[{ title: "SAMPLE ID", dataIndex: "sample_id", key: "sample", width: 190 }, { title: "性质", dataIndex: "name", key: "name", width: 240, render: displayApiText }, { title: "值", key: "value", width: 140, render: (_, item: PolyInfoProperty) => `${displayApiText(item.value)} ${displayApiText(item.unit, "")}`.trim() }, { title: "方法", dataIndex: "method", key: "method", width: 160, render: displayApiText }, { title: "条件", dataIndex: "condition", key: "condition", render: displayApiText }]} dataSource={comparison.polyinfo.properties} pagination={zhPagination({ pageSize: 12, showSizeChanger: false })} scroll={{ x: 1050 }} /></div>;

  return <Drawer className="polyinfo-comparison-drawer" title="批处理与 PoLyInfo 对照" width={1180} open={loading || Boolean(comparison)} onClose={onClose}>{loading && !comparison ? <div className="comparison-loading"><LoaderCircle size={30} className="spin" /><strong>正在解析真实 PoLyInfo 样品记录并计算差异</strong></div> : comparison && <Tabs defaultActiveKey="overview" items={[{ key: "overview", label: "对照总览", children: overview }, { key: "identity", label: "聚合物与样品", children: identity }, { key: "properties", label: `性质逐项 (${comparison.property_alignment.length})`, children: properties }, { key: "raw", label: "PoLyInfo 原始记录", children: rawRecords }]} />}</Drawer>;
}
export function EvidenceDrawer({ evidence, pdfUrl, onClose }: { evidence: Evidence | null; pdfUrl: string; onClose: () => void }) {
  return (
    <Drawer title="原文证据" width={820} open={Boolean(evidence)} onClose={onClose}>
      {evidence && <div className="evidence-drawer"><EvidenceVisual key={evidence.evidence_id} evidence={evidence} pdfUrl={pdfUrl} /><div className="evidence-location evidence-location-below"><span className="evidence-location-label">原文位置</span><Tag color="blue">第 {(evidence.page ?? 0) + 1} 页</Tag><Tag>{evidence.source_type || "text"}</Tag><Text code>{evidence.block_id || "未记录块编号"}</Text></div><blockquote>{evidence.source_sentence || "未保存可展示的原文片段。"}</blockquote><Descriptions column={1} bordered size="small"><Descriptions.Item label="证据 ID">{evidence.evidence_id}</Descriptions.Item><Descriptions.Item label="来源阶段">{evidence.source_stage}</Descriptions.Item><Descriptions.Item label="对象 ID">{evidence.object_id}</Descriptions.Item><Descriptions.Item label="版面坐标">{evidence.bbox?.join(", ") || "未记录"}</Descriptions.Item></Descriptions><Button block type="primary" className="drawer-action-btn" href={`${pdfUrl}#page=${(evidence.page ?? 0) + 1}`} target="_blank" icon={<FileSearch size={16} />}>在原文中打开本页</Button></div>}
    </Drawer>
  );
}
export function EntityDrawer({ entity, evidence, onEvidence, onClose }: { entity: PolymerEntity | null; evidence: Evidence[]; onEvidence: (item: Evidence) => void; onClose: () => void }) {
  return (
    <Drawer title="聚合物实体详情" width={520} open={Boolean(entity)} onClose={onClose}>
      {entity && <div className="entity-drawer"><Title level={4}>{entity.polymer_name}</Title><Space wrap><Tag color="warning">需专家复核</Tag>{confidenceTag(entity.confidence?.score)}</Space><Descriptions column={1} bordered size="small"><Descriptions.Item label="实体 ID">{entity.entity_id}</Descriptions.Item><Descriptions.Item label="关联指称">{entity.resolved_from_mentions?.length || 0} 条</Descriptions.Item><Descriptions.Item label="结构特征">{entity.structural_features?.length ? entity.structural_features.join("；") : "尚未抽取"}</Descriptions.Item></Descriptions><div><Text strong>原文名称与别名</Text><div className="tag-list drawer-tags">{entity.source_names?.map((name) => <Tag key={name}>{name}</Tag>)}</div></div><div className="notice-card warn"><span className="notice-icon"><FlaskConical size={16} /></span><div className="notice-body"><strong>统一实体仍需人工确认</strong><span>名称相近不等于结构、组成或样品状态完全相同，请结合原文证据裁决。</span></div></div><Button block type="primary" className="drawer-action-btn" icon={<Link2 size={15} />} onClick={() => { const item = entity.evidence_ids?.map((id) => evidence.find((entry) => entry.evidence_id === id)).find(Boolean); if (item) onEvidence(item); }}>查看实体证据</Button></div>}
    </Drawer>
  );
}
