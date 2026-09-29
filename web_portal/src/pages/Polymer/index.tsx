"use client";

import { Button, Space, Table, Typography, Empty } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeft, Atom, Download, FileSearch, TestTubes } from "lucide-react";
import type { CandidateData } from "../../types";
import { polymerTypeLabel, sampleKindLabel, systemPid, repeatUnitFor } from "../../utils/format";
import { PolymerStructure } from "../../components/PolymerStructure";
import { NoResult, zhPagination } from "../../components/common";
import { useExtraction } from "../../store/extraction";
import { useNavigate } from "react-router-dom";
import "./style.css";
const { Title, Text, Paragraph } = Typography;

function PolymerPage({ candidate, entityId, pdfUrl, onExport, onBack, onSample }: { candidate: CandidateData; entityId: string; pdfUrl: string; onExport: () => void; onBack: () => void; onSample: (id: string) => void }) {
  const entity = candidate.polymer_entities.find((item) => item.entity_id === entityId);
  if (!entity) return <div className="page-stack"><Button className="standalone-back" icon={<ArrowLeft size={15} />} onClick={onBack}>返回聚合物目录</Button><Empty description="没有找到该聚合物实体" /></div>;
  const samples = candidate.samples.filter((sample) => sample.refers_to_entity === entity.entity_id);
  const repeatUnit = repeatUnitFor(entity);
  const entityRecord = entity as unknown as Record<string, unknown>;
  const columns: ColumnsType<CandidateData["samples"][number]> = [
    { title: "NO.", key: "no", width: 70, render: (_, __, index) => index + 1 },
    { title: "SAMPLE ID", dataIndex: "sample_id", key: "sample", width: 145, render: (value) => <Button type="link" className="sample-id-link" onClick={() => onSample(value)}>{value}</Button> },
    { title: "MATERIAL TYPE", key: "material", width: 170, render: (_, sample) => sampleKindLabel(sample.sample_kind) },
    { title: "ADDITIVES", key: "additives", width: 150, render: (_, sample) => { const additives = (sample as unknown as Record<string, unknown>).additives; return Array.isArray(additives) && additives.length ? additives.join(", ") : "-"; } },
    { title: "POLYMER TYPE", key: "polymerType", width: 170, render: () => polymerTypeLabel(entity.polymer_type, entity.polymer_name) },
    { title: "PROPERTY", key: "property", render: (_, sample) => { const properties = candidate.property_observations.filter((item) => item.sample_id === sample.sample_id); return properties.length ? <button className="sample-property-preview" onClick={() => onSample(sample.sample_id)}>{properties.slice(0, 5).map((item) => <span key={item.property_id}>{item.property_name_raw} <b>{item.value_raw} {item.unit_normalized || item.unit_raw || ""}</b></span>)}{properties.length > 5 && <small>另有 {properties.length - 5} 条性质</small>}</button> : <Text type="secondary">暂无性质记录</Text>; } },
  ];

  return <div className="page-stack upload-page polymer-page">
    <header className="upload-hero">
      <div className="upload-hero-main">
        <span className="upload-eyebrow">聚合物实体 · 样品列表</span>
        <Title level={2}>Sample List ({entity.polymer_name})</Title>
        <Paragraph>{systemPid(entity)} · {polymerTypeLabel(entity.polymer_type, entity.polymer_name)} — 同一实体的全部样品与性质预览，点击进入样品详情。</Paragraph>
      </div>
      <div className="upload-hero-side">
        <span className="svc-dot on"><i />{samples.length} 个样品</span>
        <Space><Button icon={<ArrowLeft size={15} />} onClick={onBack}>返回聚合物目录</Button><Button href={pdfUrl} target="_blank" icon={<FileSearch size={15} />}>原文</Button><Button className="start-btn" type="primary" onClick={onExport} icon={<Download size={15} />}>导出数据</Button></Space>
      </div>
    </header>
    <section className="ucard polymer-identity-panel">
      <div className="ucard-head">
        <div>
          <span className="identity-kicker">ENTITY PROFILE</span>
          <h3><span className="title-icon"><Atom size={15} /></span>聚合物身份</h3>
          <p>先确认这是哪个聚合物实体，再查看它关联的样品和性质。</p>
        </div>
        <span className="identity-status"><i />已识别实体</span>
      </div>
      <div className="polymer-identity-body">
        <div className="polymer-structure-large">
          <div className="identity-section-title"><div><b>重复单元示意</b><span>Repeat unit</span></div><span className="identity-help">结构仅作识别参考</span></div>
          <PolymerStructure entity={entity} />
          <p className="structure-caption">重复单元用于帮助核对名称与结构，不代表完整分子构型。</p>
        </div>
        <div className="polymer-identity-data">
          <div className="identity-data-heading"><div><b>识别信息</b><span>Identity details</span></div><span>共 {samples.length} 个关联样品</span></div>
          <div className="identity-data-grid">
            <span><b>系统编号 PID</b><strong>{systemPid(entity)}</strong></span>
            <span><b>重复单元分子式 CU formula</b><strong>{repeatUnit.formula || "待补充"}</strong></span>
            <span><b>聚合物类型 Polymer type</b><strong>{polymerTypeLabel(entity.polymer_type, entity.polymer_name)}</strong></span>
            <span><b>样品数量 Samples</b><strong>{samples.length} 个</strong></span>
            <span className="wide"><b>原文名称 Source names</b><strong>{entity.source_names?.join("；") || "未报告"}</strong></span>
            <span className="wide"><b>结构状态 Structure status</b><strong>{repeatUnit.definition ? "名称词典匹配的重复单元示意" : String(entityRecord.representation_status || "待专家补充")}</strong></span>
          </div>
        </div>
      </div>
    </section>
    <section className="ucard polymer-sample-table"><div className="ucard-head"><div><h3><span className="title-icon"><TestTubes size={15} /></span>样品列表</h3><p>Number of data points: {samples.length} · PID = {systemPid(entity)}</p></div></div><div className="polymer-table-wrap"><Table rowKey="sample_id" columns={columns} dataSource={samples} pagination={zhPagination({ pageSize: 10, hideOnSinglePage: true })} scroll={{ x: 1040 }} locale={{ emptyText: <Empty description="该聚合物尚未绑定样品" /> }} /></div></section>
  </div>;
}


export default function PolymerRoute() {
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
  return (
    <div className="page-stack polymer-page">
      <PolymerPage
        candidate={s.candidate} entityId={s.selectedPolymerId}
        pdfUrl={s.pdfUrl} onExport={s.downloadJson}
        onBack={() => navigate("/results")} onSample={s.openSamplePage}
      />
    </div>
  );
}
