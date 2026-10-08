"use client";

import { Button, Empty, Space, Table, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowRight, Beaker, Gauge, Link2, Workflow } from "lucide-react";
import type { CandidateData, Evidence, PropertyObservation } from "../../types";
import { confidenceTag, measurementConditionText, polymerTypeLabel, processParameterText, processTypeLabel, sampleDisplayName, sampleKindLabel, systemPid } from "../../utils/format";
import { NoResult, zhPagination } from "../../components/common";
import { useExtraction } from "../../store/extraction";
import { useNavigate } from "react-router-dom";
import "./style.css";
const { Text } = Typography;

function SamplePage({ candidate, selectedId, pdfUrl, onExport, onEvidence, onSample, onBack }: {
  candidate: CandidateData;
  selectedId?: string;
  pdfUrl: string;
  onExport: () => void;
  onEvidence: (evidence: Evidence) => void;
  onSample: (sampleId: string) => void;
  onBack: () => void;
}) {
  const sample = candidate.samples.find((item) => item.sample_id === selectedId) || candidate.samples[0];
  if (!sample) return <div className="page-stack"><Button className="standalone-back" icon={<ArrowLeft size={15} />} onClick={onBack}>返回样品列表</Button><Empty description="当前结果中没有样品" /></div>;
  const entity = candidate.polymer_entities.find((item) => item.entity_id === sample.refers_to_entity);
  const properties = candidate.property_observations.filter((item) => item.sample_id === sample.sample_id);
  const relatedProcessSteps = candidate.process_steps.filter((step) => step.input_sample_ids.includes(sample.sample_id) || step.output_sample_ids.includes(sample.sample_id));
  const sampleMap = new Map(candidate.samples.map((item) => [item.sample_id, item]));
  const evidenceMap = new Map(candidate.evidence.map((item) => [item.evidence_id, item]));
  const entityPid = entity ? systemPid(entity) : "待归一";

  const renderProcessSamples = (label: string, ids: string[], output = false) => (
    <div className={`flow-col ${output ? "is-out" : "is-in"}`}>
      <div className="flow-col-head"><span className="flow-dot" />{label}<em>× {ids.length}</em></div>
      <div className="flow-chips">{ids.length ? ids.map((id) => {
        const linkedSample = sampleMap.get(id);
        const isCurrent = id === sample.sample_id;
        return <button className={`flow-chip${isCurrent ? " is-current" : ""}`} type="button" key={id} onClick={() => !isCurrent && onSample(id)} disabled={isCurrent} title={isCurrent ? "当前样品" : `查看样品 ${id}`}>
          <span className="flow-chip-text">
            <span className="flow-chip-name">{linkedSample ? sampleDisplayName(linkedSample) : id}</span>
            <span className="flow-chip-id">{id}</span>
          </span>
        </button>;
      }) : <span className="flow-empty">— 未建立 —</span>}</div>
    </div>
  );

  const propertyColumns: ColumnsType<PropertyObservation> = [
    { title: "性质名称", dataIndex: "property_name_raw", key: "name", render: (value, record) => <div className="primary-cell"><strong>{value}</strong><span>{record.property_code || "尚未映射性质编码"}</span></div> },
    { title: "测试方法", key: "method", width: 160, render: (_, record) => { const item = record as unknown as Record<string, unknown>; const method = item.method_normalized || item.method_raw || item.test_method; return method ? String(method) : <Text type="secondary">未建立方法绑定</Text>; } },
    { title: "测试条件", key: "condition", width: 210, render: (_, record) => <span className="condition-copy">{measurementConditionText(candidate, record)}</span> },
    { title: "数值", key: "value", width: 120, render: (_, record) => <strong className="property-value">{record.value_raw}</strong> },
    { title: "单位", key: "unit", width: 90, render: (_, record) => record.unit_normalized || record.unit_raw || "-" },
    { title: "来源", dataIndex: "source_type", key: "source", width: 90, render: (value) => value || "-" },
    { title: "置信度", key: "confidence", width: 95, render: (_, record) => confidenceTag(record.confidence?.score) },
    { title: "原文证据", key: "evidence", width: 95, render: (_, record) => { const item = record.evidence_ids?.map((id) => evidenceMap.get(id)).find(Boolean); return <Tooltip title={item ? "查看该性质的原文证据" : "当前记录未绑定可定位证据"}><Button aria-label="查看性质证据" disabled={!item} icon={<Link2 size={15} />} onClick={() => item && onEvidence(item)} /></Tooltip>; } },
  ];

  return (
    <div className="page-stack upload-page sample-property-page">
      

      <section className="ucard sample-property-identity">
        <div className="sample-avatar"><Beaker size={23} /></div>
        <div className="sample-property-title"><strong>{sampleDisplayName(sample)}</strong><span>{sample.polymer_name}</span></div>
        <div className="sample-identity-fields">
          <span><b>SAMPLE ID</b>{sample.sample_id}</span>
          <span><b>PID</b>{entityPid}</span>
          <span><b>MATERIAL TYPE</b>{sampleKindLabel(sample.sample_kind)}</span>
          <span><b>POLYMER TYPE</b>{polymerTypeLabel(entity?.polymer_type, entity?.polymer_name || sample.polymer_name)}</span>
          <span><b>STATE</b>{sample.state_description || "原文未明确报告"}</span>
          <span><b>PROPERTY COUNT</b>{properties.length}</span>
        </div>
      </section>

      <section className="ucard sample-process-panel">
        <div className="ucard-head"><div><h3><span className="title-icon"><Workflow size={15} /></span>工艺与样品谱系</h3><p>按工艺顺序展示当前样品的上游输入与下游输出 · {relatedProcessSteps.length} steps</p></div><span className="lineage-legend"><i className="lg-in" />输入<i className="lg-cur" />当前<i className="lg-out" />输出</span></div>
        {relatedProcessSteps.length ? <div className="lineage-rail">{relatedProcessSteps.map((step, idx) => {
          const isProduced = step.output_sample_ids.includes(sample.sample_id);
          const isConsumed = step.input_sample_ids.includes(sample.sample_id);
          const relation = isProduced && isConsumed ? "状态更新" : isProduced ? "生成当前样品" : "作为输入参与";
          const parameters = Object.entries((step.parameters || {}) as Record<string, unknown>);
          const stepEvidence = step.evidence_ids?.map((id) => evidenceMap.get(id)).find(Boolean);
          return <article className="lineage-step" key={step.step_id}>
            <div className="lineage-gutter"><span className="lineage-index">{String(idx + 1).padStart(2, "0")}</span><span className="lineage-line" /></div>
            <div className="lineage-body">
              <header className="lineage-head">
                <div className="lineage-title"><strong>{processTypeLabel(step.process_type)}</strong><span className="lineage-sub">{step.step_id} · {step.process_type}</span></div>
                <Space size={6}>{confidenceTag(step.confidence?.score)}<Tag className={`rel-tag ${isProduced ? "is-gen" : "is-use"}`}>{relation}</Tag></Space>
              </header>
              <div className="process-flow">
                {renderProcessSamples("INPUT · 输入", step.input_sample_ids)}
                <div className="flow-op"><span className="flow-op-icon"><ArrowRight size={14} /></span></div>
                <div className="process-node"><span className="node-kicker">工艺步骤</span><strong>{processTypeLabel(step.process_type)}</strong><small>{step.step_id}</small></div>
                <div className="flow-op"><span className="flow-op-icon"><ArrowRight size={14} /></span></div>
                {renderProcessSamples("OUTPUT · 输出", step.output_sample_ids, true)}
              </div>
              <div className="process-parameters"><span className="param-label"><Gauge size={13} />工艺参数<Tag>{parameters.length}</Tag></span>{parameters.length ? <dl>{parameters.map(([key, value]) => <div className="param-item" key={key}><dt>{key}</dt><dd>{processParameterText(value)}</dd></div>)}</dl> : <Text type="secondary">未抽取到结构化工艺参数</Text>}</div>
              <footer className="process-meta"><span className="meta-chain"><span className="meta-label">关系依据</span><span className="meta-links">{step.input_sample_ids.length ? step.input_sample_ids.map((id) => <code key={id} className={id === sample.sample_id ? "is-cur" : ""}>{id}</code>) : <span className="meta-empty">无显式输入</span>}<span className="meta-arrow is-step">→</span><code className="meta-step">{step.step_id}</code><span className="meta-arrow is-step">→</span>{step.output_sample_ids.length ? step.output_sample_ids.map((id) => <code key={id} className={id === sample.sample_id ? "is-cur" : ""}>{id}</code>) : <span className="meta-empty">无显式输出</span>}</span></span><Button size="small" type="primary" className="meta-evidence-btn" disabled={!stepEvidence} icon={<Link2 size={13} />} onClick={() => stepEvidence && onEvidence(stepEvidence)}>原文证据</Button></footer>
            </div>
          </article>;
        })}</div> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前抽取结果未建立该样品与工艺步骤的直接关系" />}
      </section>

      <section className="ucard sample-property-table">
        <div className="ucard-head"><div><h3><span className="title-icon"><Gauge size={15} /></span>性质数据</h3><p>每条性质保留数值、单位、测量语境、置信度与原文证据 · {properties.length} records</p></div></div>
        {properties.length ? <Table rowKey="property_id" columns={propertyColumns} dataSource={properties} pagination={zhPagination({ pageSize: 10, hideOnSinglePage: true })} scroll={{ x: 1080 }} /> : <Empty description="本次性质阶段未生成可用观测" />}
      </section>
    </div>
  );
}

export default function SampleRoute() {
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
  const backTarget = s.selectedPolymerId ? "/polymer" : "/results";
  return (
    <div className="page-stack sample-property-page">
      <SamplePage
        candidate={s.candidate}
        selectedId={s.selectedSampleId || s.candidate.samples[0]?.sample_id}
        pdfUrl={s.pdfUrl} onExport={s.downloadJson}
        onEvidence={s.setSelectedEvidence} onSample={s.openSamplePage}
        onBack={() => navigate(backTarget)}
      />
    </div>
  );
}
