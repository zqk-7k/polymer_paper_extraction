"use client";

import { Button, Input, Progress, Skeleton, Space, Table, Tabs, Tag, Tooltip, Typography, Empty } from "antd";
import type { ColumnsType } from "antd/es/table";
import type React from "react";
import { Anchor, Beaker, Check, Database, FileSearch, GitBranch, RefreshCw, Search, ShieldCheck, TableProperties, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import type { BatchCollectionSummary, BatchResultSummary, PolyInfoSummary } from "../../types";
import { API_BASE } from "../../types";
import { Metric, ScoreBar, zhPagination } from "../../components/common";
import BatchSwitcher from "../../components/BatchSwitcher";
import { useExtraction } from "../../store/extraction";
import "./style.css";
const { Title, Paragraph } = Typography;

function PolyInfoResultsPage({ loading, rows, batchResults, batchCollections, selectedCollectionId, onCollection, onRefresh, onCompare }: {
  loading: boolean;
  rows: PolyInfoSummary[];
  batchResults: BatchResultSummary[];
  batchCollections: BatchCollectionSummary[];
  selectedCollectionId: string;
  onCollection: (collectionId: string) => void;
  onRefresh: () => void;
  onCompare: (refNo: string, collectionId?: string) => void;
}) {
  const [search, setSearch] = useState("");
  const activeBatch = batchResults[0];
  const activeCollection = batchCollections.find((item) => item.collection_id === selectedCollectionId)
    || batchCollections.find((item) => item.is_active)
    || batchCollections[0];
  const batchCollection = activeCollection?.collection_id || activeBatch?.collection_id || "当前批次";
  const batchResultDate = activeCollection?.result_date || activeBatch?.result_date || "日期未标注";
  const query = search.trim().toLowerCase();
  const filtered = rows.filter((item) => !query || [
    item.ref_no,
    item.reference.doi,
    item.reference.journal,
    ...item.polymer_names,
  ].filter(Boolean).join(" ").toLowerCase().includes(query)).sort((left, right) =>
    Number(right.has_batch_result) - Number(left.has_batch_result) || left.ref_no.localeCompare(right.ref_no),
  );
  const polyInfoTotals = rows.reduce((sum, item) => ({
    polymers: sum.polymers + item.stats.polymer_count,
    samples: sum.samples + item.stats.sample_count,
    properties: sum.properties + item.stats.property_count,
    matched: sum.matched + (item.has_batch_result ? 1 : 0),
  }), { polymers: 0, samples: 0, properties: 0, matched: 0 });

  const chronological = [...batchCollections].sort((left, right) => left.result_date.localeCompare(right.result_date));
  const previousByCollection = new Map<string, BatchCollectionSummary>();
  chronological.forEach((item, index) => {
    if (index > 0) previousByCollection.set(item.collection_id, chronological[index - 1]);
  });

  // 与 batch 页文献记录表一致的行内骨架屏：骨架行直接作为 dataSource 渲染，
  // 而不是在表格上/下叠加一块 Skeleton，避免错位与闪烁。
  const sk = (width: string | number) =>
    typeof width === "number" ? (
      <Skeleton.Input active size="small" style={{ width, maxWidth: "100%", flex: "0 1 auto", minWidth: 0 }} />
    ) : (
      <Skeleton.Input active size="small" block style={{ width, maxWidth: "100%" }} />
    );
  const isSkeleton = (item: unknown) => Boolean((item as { skeleton?: boolean } | null)?.skeleton);
  const cellSkeleton = (item: unknown, node: React.ReactNode) =>
    isSkeleton(item) ? <div className="archive-skeleton-cell">{node}</div> : node;

  const columns: ColumnsType<PolyInfoSummary> = [
    {
      title: "文献与来源",
      key: "paper",
      width: 330,
      render: (_, item) => cellSkeleton(item, isSkeleton(item)
        ? <div className="polyinfo-paper-cell">{sk("70%")}<div style={{ marginTop: 8 }}>{sk("90%")}</div><div style={{ marginTop: 8 }}>{sk("55%")}</div></div>
        : <div className="polyinfo-paper-cell"><strong>{item.ref_no}</strong><span>{item.reference.journal || "期刊未记录"} · {item.reference.year || "年份未记录"}</span><small>{item.reference.doi || "无 DOI"}</small></div>),
    },
    {
      title: "PoLyInfo 聚合物",
      key: "polymers",
      render: (_, item) => cellSkeleton(item, isSkeleton(item)
        ? <div className="polyinfo-polymer-cell">{sk("80%")}<div style={{ marginTop: 8 }}>{sk("60%")}</div></div>
        : <div className="polyinfo-polymer-cell"><strong>{item.polymer_names[0] || "名称未记录"}</strong>{item.polymer_name_count > 1 && <span>另有 {item.polymer_name_count - 1} 个规范名称</span>}<small>{item.stats.polymer_count} PID · {item.stats.structure_count} 个结构图</small></div>),
    },
    { title: "样品", key: "samples", width: 86, align: "right", render: (_, item) => cellSkeleton(item, isSkeleton(item) ? sk(40) : <b className="numeric-cell">{item.stats.sample_count}</b>) },
    { title: "性质值", key: "properties", width: 96, align: "right", render: (_, item) => cellSkeleton(item, isSkeleton(item) ? sk(40) : <b className="numeric-cell">{item.stats.property_count}</b>) },
    { title: "工艺字段", key: "processes", width: 96, align: "right", render: (_, item) => cellSkeleton(item, isSkeleton(item) ? sk(40) : <b className="numeric-cell">{item.stats.process_count}</b>) },
    { title: "来源组", dataIndex: "group", key: "group", width: 88, render: (value, item) => cellSkeleton(item, isSkeleton(item) ? sk(64) : <Tag color={value === "有doi" ? "blue" : "default"}>{value}</Tag>) },
    { title: "批处理", key: "matched", width: 118, render: (_, item) => cellSkeleton(item, isSkeleton(item) ? sk(86) : item.has_batch_result ? <Tag color="success">可直接对照</Tag> : <Tag>无配对结果</Tag>) },
    {
      title: "操作",
      key: "action",
      width: 210,
      render: (_, item) => cellSkeleton(item, isSkeleton(item) ? sk(130) : <Space size={7}><Button type={item.has_batch_result ? "primary" : "default"} icon={<GitBranch size={15} />} onClick={() => onCompare(item.ref_no, activeCollection?.collection_id)}>{item.has_batch_result ? "查看逐项差异" : "查看原始记录"}</Button>{item.has_pdf && <Tooltip title="打开该目录中的论文 PDF"><Button aria-label="打开 PoLyInfo 对应论文" href={`${API_BASE}/api/polyinfo-results/${item.ref_no}/pdf`} target="_blank" icon={<FileSearch size={15} />} /></Tooltip>}</Space>),
    },
  ];

  const evolutionColumns: ColumnsType<BatchCollectionSummary> = [
    {
      title: "批次",
      key: "collection",
      width: 265,
      fixed: "left",
      render: (_, item) => cellSkeleton(item, isSkeleton(item)
        ? <div className="batch-version-cell">{sk("80%")}<div style={{ marginTop: 8 }}>{sk("60%")}</div></div>
        : <div className="batch-version-cell"><strong>{item.collection_id}</strong><span>{item.result_date} · {item.result_mode}</span><small>{item.collection_kind === "review" ? `审阅批次 · ${item.publication_status.partial} 篇 partial` : item.is_active ? "当前生产批次" : item.validation_status}</small></div>),
    },
    { title: "文献", key: "papers", width: 90, align: "right", render: (_, item) => cellSkeleton(item, isSkeleton(item) ? sk(48) : <b>{item.paired_documents}/{item.document_count}</b>) },
    {
      title: "锚点 F1",
      key: "f1",
      width: 145,
      render: (_, item) => cellSkeleton(item, isSkeleton(item) ? sk(72) : (() => {
        const previous = previousByCollection.get(item.collection_id);
        const delta = previous ? item.anchor.f1 - previous.anchor.f1 : null;
        return <div className="batch-score-cell"><strong>{(item.anchor.f1 * 100).toFixed(1)}%</strong>{delta !== null && <Tag color={delta > 0 ? "success" : delta < 0 ? "error" : "default"}>{delta > 0 ? "+" : ""}{(delta * 100).toFixed(1)} pp</Tag>}</div>;
      })()),
    },
    { title: "P / R", key: "pr", width: 140, render: (_, item) => cellSkeleton(item, isSkeleton(item) ? sk(84) : <span className="compact-ratio">{(item.anchor.precision * 100).toFixed(1)} / {(item.anchor.recall * 100).toFixed(1)}%</span>) },
    { title: "样品绑定", key: "sample", width: 120, render: (_, item) => cellSkeleton(item, isSkeleton(item) ? sk("90%") : <Progress percent={Math.round(item.quality.sample_binding_coverage * 100)} size="small" strokeColor="#2f9e8f" trailColor="#e8ebf0" strokeLinecap="round" />) },
    { title: "证据绑定", key: "evidence", width: 120, render: (_, item) => cellSkeleton(item, isSkeleton(item) ? sk("90%") : <Progress percent={Math.round(item.quality.evidence_coverage * 100)} size="small" strokeColor="#3f6fb5" trailColor="#e8ebf0" strokeLinecap="round" />) },
    { title: "单位完整", key: "unit", width: 120, render: (_, item) => cellSkeleton(item, isSkeleton(item) ? sk("90%") : <Progress percent={Math.round(item.quality.unit_completeness * 100)} size="small" strokeColor="#6f6aa8" trailColor="#e8ebf0" strokeLinecap="round" />) },
    { title: "性质候选", key: "properties", width: 105, align: "right", render: (_, item) => cellSkeleton(item, isSkeleton(item) ? sk(48) : <b>{item.totals.property_observations}</b>) },
    { title: "Stage 4R", key: "stage4r", width: 128, render: (_, item) => cellSkeleton(item, isSkeleton(item) ? <div>{sk(56)}<div style={{ marginTop: 8 }}>{sk(84)}</div></div> : <div className="stage-compact"><b>+{item.stage.stage4r_migrated}</b><span>{item.stage.stage4r_recovered} 候选恢复</span></div>) },
    { title: "Stage 6", key: "stage6", width: 150, render: (_, item) => cellSkeleton(item, isSkeleton(item) ? <div>{sk(72)}<div style={{ marginTop: 8 }}>{sk(96)}</div></div> : <div className="stage-compact"><b>{item.stage.final_documents}/{item.document_count} final</b><span>{item.stage.rejected_objects} 拒绝 · {item.stage.stage6_warnings} 警告</span></div>) },
  ];

  const showPaperSkeleton = loading && filtered.length === 0;
  const showEvolutionSkeleton = loading && batchCollections.length === 0;
  const paperSkeletonRows = Array.from({ length: 8 }, (_, i) => ({ ref_no: `skeleton-${i}`, skeleton: true })) as unknown as PolyInfoSummary[];
  const evolutionSkeletonRows = Array.from({ length: 5 }, (_, i) => ({ collection_id: `skeleton-${i}`, skeleton: true })) as unknown as BatchCollectionSummary[];

  const qualityOverview = activeCollection ? <div className="batch-quality-stack">
    {activeCollection.collection_kind === "review" && <div className="source-strip"><span className="source-strip-icon"><ShieldCheck size={16} /></span><div className="source-strip-body"><strong>当前展示 demo30 审阅批次，不是可发布生产数据</strong><span>{`32 篇结果完整可浏览，其中 ${activeCollection.publication_status.partial} 篇为 partial。下列指标用于定位缺口和推动人工审核，不代表已达到入库标准。`}</span></div><span className="source-strip-tag">REVIEW</span></div>}
    <div className="source-strip"><span className="source-strip-icon"><GitBranch size={16} /></span><div className="source-strip-body"><strong>{`当前对照：${activeCollection.collection_id} ↔ PoLyInfo`}</strong><span>锚点 Precision、Recall 和 F1 只衡量与 PoLyInfo 已有记录的一致性，不是全文 gold 准确率。抽取独有记录可能是有效补充，也可能需要回到 PDF 证据裁决。</span></div><span className="source-strip-tag">ANCHOR</span></div>
    {activeCollection.collection_id === "demo30_preview_20260824" && <section className="work-panel audit-report-links">
      <div>
        <strong>demo30 科学审计与目标实验</strong>
        <span>查看 32 篇全量差异，以及九类性质归属 Agent 在独立冻结集上的受控自进化结果。</span>
      </div>
      <Space wrap>
        <Button href={`${API_BASE}/api/reports/demo30-polyinfo`} target="_blank" icon={<TableProperties size={15} />}>打开全量差异报告</Button>
        <Button type="primary" href={`${API_BASE}/api/reports/agent-evolution`} target="_blank" icon={<Workflow size={15} />}>打开 Agent 与自进化报告</Button>
      </Space>
    </section>}
    <section className="metric-strip polyinfo-metrics">
      <Metric icon={<ShieldCheck size={19} />} label="锚点 F1" value={`${(activeCollection.anchor.f1 * 100).toFixed(1)}%`} tone="ink" />
      <Metric icon={<Check size={19} />} label="数值一致" value={activeCollection.anchor.matched} tone="ink" />
      <Metric icon={<Beaker size={19} />} label="样品绑定" value={`${(activeCollection.quality.sample_binding_coverage * 100).toFixed(1)}%`} tone="ink" />
      <Metric icon={<FileSearch size={19} />} label="证据绑定" value={`${(activeCollection.quality.evidence_coverage * 100).toFixed(1)}%`} tone="ink" />
      <Metric icon={<Database size={19} />} label="配对文献" value={`${activeCollection.paired_documents}/${activeCollection.document_count}`} tone="ink" />
    </section>
    <div className="quality-analysis-grid">
      <section className="work-panel quality-analysis-panel">
        <div className="analysis-panel-heading"><div><strong><span className="title-icon"><Anchor size={15} /></span>PoLyInfo 锚点一致性</strong><span>名称规范化、单位换算和 1% 数值容差后的记录级比较</span></div><Tag color="blue">REFERENCE-ALIGNED</Tag></div>
        <ScoreBar label="Precision" value={activeCollection.anchor.precision} color="#3f6fb5" />
        <ScoreBar label="Recall" value={activeCollection.anchor.recall} color="#2f9e8f" />
        <ScoreBar label="F1" value={activeCollection.anchor.f1} color="#6f6aa8" />
        <div className="alignment-summary compact"><span className="matched"><b>{activeCollection.anchor.matched}</b>数值一致</span><span className="different"><b>{activeCollection.anchor.value_diff}</b>同名值不同</span><span className="pi-only"><b>{activeCollection.anchor.polyinfo_only}</b>仅 PoLyInfo</span><span className="web-only"><b>{activeCollection.anchor.extraction_only}</b>仅本批次</span></div>
      </section>
      <section className="work-panel quality-analysis-panel">
        <div className="analysis-panel-heading"><div><strong><span className="title-icon"><Database size={15} /></span>候选记录完整度</strong><span>检查关系和证据是否存在，不等同于人工确认其语义正确</span></div><Tag color="green">PIPELINE QUALITY</Tag></div>
        <ScoreBar label="性质绑定合法样品" value={activeCollection.quality.sample_binding_coverage} color="#2f9e8f" />
        <ScoreBar label="性质绑定原文证据" value={activeCollection.quality.evidence_coverage} color="#3f6fb5" />
        <ScoreBar label="单位字段完整" value={activeCollection.quality.unit_completeness} color="#6f6aa8" />
        <ScoreBar label="测量条件关联" value={activeCollection.quality.condition_coverage} color="#b07f3c" />
      </section>
    </div>
    <section className="work-panel stage-evolution-panel">
      <div className="analysis-panel-heading"><div><strong><span className="title-icon"><GitBranch size={15} /></span>当前批次的阶段变化</strong><span>同一批次从 Stage 4 原始抽取到 Stage 4R 恢复、候选汇总和 Stage 6 发布</span></div><Tag>{activeCollection.strict_compliance_claimed ? "STRICT" : "PREVIEW"}</Tag></div>
      <ol className="stage-flow">
        {[
          { key: "s4", index: "01", name: "Stage 4 · 初始抽取", value: activeCollection.stage.stage4_pre_properties, foot: "LLM / 规则初始结果" },
          { key: "s4r", index: "02", name: "Stage 4R · 恢复", value: activeCollection.stage.stage4_post_properties, foot: `迁移 ${activeCollection.stage.stage4r_migrated} · 跳过 ${activeCollection.stage.stage4r_skipped} · 恢复 ${activeCollection.stage.stage4r_recovered}` },
          { key: "cand", index: "03", name: "候选汇总", value: activeCollection.stage.candidate_properties, foot: "含跨阶段汇总结果" },
          { key: "s6", index: "04", name: "Stage 6 · 发布", value: activeCollection.stage.final_properties, foot: `拒绝 ${activeCollection.stage.rejected_objects} · 警告 ${activeCollection.stage.stage6_warnings}` },
        ].map((step, i, arr) => {
          const prev = i === 0 ? null : arr[i - 1].value;
          const delta = prev === null || prev === 0 ? null : step.value - (prev as number);
          const rate = prev ? Math.min(999, Math.round((step.value / (prev as number)) * 100)) : null;
          const isLast = i === arr.length - 1;
          return (
            <li key={step.key} className={`stage-flow-step${isLast ? " is-final" : ""}`}>
              <div className="stage-flow-node"><span className="stage-flow-index">{step.index}</span></div>
              <div className="stage-flow-card">
                <div className="stage-flow-top"><span className="stage-flow-name">{step.name}</span>{delta !== null && delta !== 0 && <span className={`stage-flow-delta ${delta > 0 ? "up" : "down"}`}>{delta > 0 ? `+${delta}` : delta}</span>}</div>
                <div className="stage-flow-value">{step.value.toLocaleString()}{rate !== null && <em>{rate}% 留存</em>}</div>
                <p className="stage-flow-foot">{step.foot}</p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  </div> : <Empty description="没有可比较的批次质量摘要" />;

  const batchEvolution = <div className="batch-evolution-stack">
    <div className="evolution-notice" role="note">
      <span className="evolution-notice-icon"><GitBranch size={17} /></span>
      <div className="evolution-notice-body">
        <strong>如何读懂批次演进：条数增长 ≠ 质量提升</strong>
        <span>不同批次文献集合不同，记录级指标不可直接当作同一测试集的提升。请联动查看锚点 F1、样品绑定、证据绑定、Stage 6 拒绝对象，再回到逐篇差异用 PDF 证据裁决。</span>
        <div className="evolution-notice-chips">
          <span>锚点 F1</span><span>样品绑定</span><span>证据绑定</span><span>Stage 6 拒绝</span><span>人工 gold 评价</span>
        </div>
      </div>
      <span className="evolution-notice-tag">READING GUIDE</span>
    </div>
    <section className="work-panel batch-evolution-panel">
      <div className="polyinfo-table-toolbar"><div><strong>生产与审阅批次的质量演进</strong><span>不同文献集合的记录级指标不可直接当作同一测试集的提升；审阅批次单独标记，逐篇差异可在下一页核查。</span></div><Tag color="blue">{batchCollections.length} 批次</Tag></div>
      <Table rowKey="collection_id" columns={evolutionColumns} dataSource={showEvolutionSkeleton ? evolutionSkeletonRows : batchCollections} pagination={showEvolutionSkeleton ? false : zhPagination()} scroll={{ x: 1500 }} />
    </section>
  </div>;

  const paperDetails = <section className="work-panel polyinfo-table-panel">
    <div className="polyinfo-table-toolbar"><div><strong>真实 PoLyInfo 文献记录</strong><span>当前显示 {filtered.length} / {rows.length} 篇；逐篇查看聚合物、样品、性质和原始字段差异。</span></div><Input value={search} onChange={(event) => setSearch(event.target.value)} prefix={<Search size={15} />} placeholder="搜索 reference_no、DOI、期刊或聚合物" allowClear /></div>
    <Table rowKey="ref_no" columns={columns} dataSource={showPaperSkeleton ? paperSkeletonRows : filtered} pagination={showPaperSkeleton ? false : zhPagination({ pageSize: 12, showSizeChanger: false })} scroll={{ x: 1280 }} rowClassName={(item) => !isSkeleton(item) && (item as PolyInfoSummary).has_batch_result ? "polyinfo-linked-row" : ""} locale={{ emptyText: <Empty description="没有读取到 PoLyInfo 原始记录" /> }} />
  </section>;

  return <div className="page-stack upload-page polyinfo-results-page">
    <div className="ucard polyinfo-tabs-card">
    <Tabs className="batch-comparison-tabs" defaultActiveKey="overview" tabBarExtraContent={{ right: <BatchSwitcher collections={batchCollections} value={activeCollection?.collection_id} onChange={onCollection} compact /> }} items={[
      { key: "overview", label: "质量总览", children: qualityOverview },
      { key: "evolution", label: `批次演进 (${batchCollections.length})`, children: batchEvolution },
      { key: "papers", label: `文献逐篇 (${polyInfoTotals.matched})`, children: paperDetails },
    ]} />
    </div>
  </div>;
}


export default function PolyInfoRoute() {
  const s = useExtraction();
  useEffect(() => {
    s.ensureBatchPage("polyinfo");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="page-stack polyinfo-results-page">
      <PolyInfoResultsPage
        loading={s.archiveLoading} rows={s.polyInfoResults} batchResults={s.batchResults}
        batchCollections={s.batchCollections} selectedCollectionId={s.selectedBatchCollectionId}
        onCollection={s.selectBatchCollection}
        onRefresh={() => {
          void s.refreshPolyInfoResults(s.selectedBatchCollectionId);
          void s.refreshBatchResults(s.selectedBatchCollectionId);
          void s.refreshBatchCollections();
        }}
        onCompare={s.openPolyInfoComparison}
      />
    </div>
  );
}
