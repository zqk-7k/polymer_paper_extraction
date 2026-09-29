import type React from "react";
import { Button, Select, Skeleton, Space, Table, Tag, Typography, Empty } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Beaker, Boxes, ChevronRight, FileSearch, Gauge, RefreshCw } from "lucide-react";
import type { BatchCollectionSummary, BatchResultSummary, ExtractionJob, ResultStats } from "../types";
import { displayPaperMeta, displayPaperTitle, formatTaskTime } from "../utils/format";
import { Metric, zhPagination } from "./common";
import "./ArchiveView.css";
const { Title, Paragraph } = Typography;

export type ArchiveRow = {
  key: string;
  refNo: string;
  title: string;
  doi?: string | null;
  meta: string;
  time: string;
  source: string;
  status: string;
  validation?: string | null;
  stats: ResultStats;
  task?: ExtractionJob;
  batch?: BatchResultSummary;
  skeleton?: boolean;
};
export function ArchiveResultsPage({ kind, loading, historyTasks, batchResults, batchCollections = [], selectedCollectionId = "", onCollection, onRefresh, onOpenHistory, onOpenBatch }: {
  kind: "history" | "batch";
  loading: boolean;
  historyTasks: ExtractionJob[];
  batchResults: BatchResultSummary[];
  batchCollections?: BatchCollectionSummary[];
  selectedCollectionId?: string;
  onCollection?: (collectionId: string) => void;
  onRefresh: () => void;
  onOpenHistory: (task: ExtractionJob) => void;
  onOpenBatch: (item: BatchResultSummary) => void;
}) {
  const emptyStats: ResultStats = { polymer_count: 0, sample_count: 0, property_count: 0, process_count: 0, characterization_count: 0, evidence_count: 0 };
  const activeBatch = batchResults[0];
  const activeCollection = batchCollections.find((item) => item.collection_id === selectedCollectionId);
  const batchCollection = activeBatch?.collection_id || "未发布批次";
  const batchResultDate = activeBatch?.result_date || "未标注日期";
  const batchMode = activeBatch?.result_mode || "preview";
  const rows: ArchiveRow[] = kind === "history"
    ? historyTasks.map((task) => ({
        key: task.task_id,
        refNo: task.source_reference_no || task.file_name.replace(/\.pdf$/i, "") || task.ref_no,
        title: displayPaperTitle(task.paper, task.file_name),
        doi: task.paper?.doi,
        meta: displayPaperMeta(task.paper),
        time: formatTaskTime(task.created_at),
        source: "网页上传",
        status: task.status,
        validation: task.validation_status,
        stats: task.stats || emptyStats,
        task,
      }))
    : batchResults.map((item) => ({
        key: item.ref_no,
        refNo: item.ref_no,
        title: displayPaperTitle(item.paper, item.ref_no),
        doi: item.paper?.doi,
        meta: displayPaperMeta(item.paper),
        time: item.result_date || "未标注日期",
        source: item.source_batch || item.collection_id,
        status: item.publication_status || "complete",
        validation: item.validation_status,
        stats: item.stats,
        batch: item,
      }));

  const totals = rows.reduce((sum, row) => ({
    polymer_count: sum.polymer_count + row.stats.polymer_count,
    sample_count: sum.sample_count + row.stats.sample_count,
    property_count: sum.property_count + row.stats.property_count,
    process_count: sum.process_count + row.stats.process_count,
    characterization_count: sum.characterization_count + row.stats.characterization_count,
    evidence_count: sum.evidence_count + row.stats.evidence_count,
  }), emptyStats);

  const showSkeleton = loading && rows.length === 0;
  const skeletonRows: ArchiveRow[] = Array.from({ length: 8 }, (_, i) => ({
    key: `skeleton-${i}`,
    refNo: "",
    title: "",
    meta: "",
    time: "",
    source: "",
    status: "",
    stats: emptyStats,
    skeleton: true,
  }));
  const sk = (width: string | number) =>
    typeof width === "number" ? (
      <Skeleton.Input active size="small" style={{ width, maxWidth: "100%", flex: "0 1 auto", minWidth: 0 }} />
    ) : (
      <Skeleton.Input active size="small" block style={{ width, maxWidth: "100%" }} />
    );
  const cellSkeleton = (row: ArchiveRow, node: React.ReactNode) => (row.skeleton ? <div className="archive-skeleton-cell">{node}</div> : node);

  const columns: ColumnsType<ArchiveRow> = [
    {
      title: "文献",
      key: "paper",
      width: 390,
      render: (_, row) => cellSkeleton(row, row.skeleton ? <div className="archive-paper archive-paper-skeleton">{sk("85%")}<div style={{ marginTop: 8 }}>{sk("60%")}</div><div style={{ marginTop: 8 }}>{sk("45%")}</div></div> : <div className="archive-paper"><strong>{row.title}</strong><span>{row.refNo}{row.doi ? ` · DOI ${row.doi}` : " · DOI 未识别"}</span><small>{row.meta}</small></div>),
    },
    {
      title: "关系摘要",
      key: "chain",
      width: 315,
      render: (_, row) => cellSkeleton(row, row.skeleton ? <div className="archive-chain archive-chain-skeleton">{sk(52)}{sk(58)}{sk(52)}</div> : <div className="archive-chain"><span>论文</span><ChevronRight size={13} /><b>{row.stats.polymer_count} 聚合物</b><ChevronRight size={13} /><b>{row.stats.sample_count} 样品</b><ChevronRight size={13} /><b>{row.stats.property_count} 性质</b></div>),
    },
    {
      title: kind === "history" ? "上传时间" : "批次",
      key: "source",
      width: 165,
      render: (_, row) => cellSkeleton(row, row.skeleton ? <div className="archive-source">{sk(96)}<div style={{ marginTop: 8 }}>{sk(64)}</div></div> : <div className="archive-source"><strong>{kind === "history" ? row.time : row.source}</strong><span>{kind === "history" ? row.source : row.time}</span></div>),
    },
    {
      title: "状态",
      key: "status",
      width: 120,
      render: (_, row) => cellSkeleton(row, row.skeleton ? sk(72) : <Space className="archive-status-tags" size={6} direction="vertical"><Tag className={`archive-status-tag status-${row.status}`} color={row.status === "complete" ? "success" : row.status === "failed" ? "error" : row.status === "partial" ? "orange" : "processing"}>{row.status === "complete" ? "完整候选" : row.status === "failed" ? "失败" : row.status === "partial" ? "部分候选" : "运行中"}</Tag>{row.validation === "not_validated" && <Tag className="archive-status-tag status-validation" color="purple">待校验</Tag>}</Space>),
    },
    {
      title: "操作",
      key: "action",
      width: 120,
      fixed: "right",
      render: (_, row) => (row.skeleton ? sk(86) : <Button className="history-open-btn" type="primary" disabled={row.status === "failed" || row.status === "running"} onClick={() => row.task ? onOpenHistory(row.task) : row.batch && onOpenBatch(row.batch)}>打开关系</Button>),
    },
  ];

  return <div className="page-stack archive-page upload-page history-page">
    <header className="upload-hero">
      <div className="upload-hero-main">
        <span className="upload-eyebrow">{kind === "history" ? "网页抽取 · 历史任务" : "离线批处理 · 结果归档"}</span>
        <Title level={2}>{kind === "history" ? "抽取结果" : "离线批处理结果"}</Title>
        <Paragraph>{kind === "history" ? "按上传时间从新到旧展示网页任务。打开任一文献后，可按文献 → 聚合物 → 样品 → 性质逐层查看。" : `独立展示 ${batchResultDate} 发布的 ${rows.length} 篇离线候选结果；这些记录不是在网页端生成，不会混入网页历史。`}</Paragraph>
      </div>
      <div className="upload-hero-side">
        <span className="svc-dot on"><i />{rows.length} 篇文献</span>
        <Space>{kind === "batch" && <Select className="batch-collection-select" value={activeCollection?.collection_id || selectedCollectionId} onChange={onCollection} options={batchCollections.map((item) => ({ value: item.collection_id, label: `${item.collection_kind === "review" ? "审阅" : "生产"} · ${item.result_date} · ${item.collection_id}` }))} placeholder="选择批次" />}<Button icon={<RefreshCw size={15} />} loading={loading} onClick={onRefresh}>刷新列表</Button></Space>
      </div>
    </header>
    <div className="source-strip">
      <span className="source-strip-icon"><FileSearch size={16} /></span>
      <div className="source-strip-body"><strong>{kind === "history" ? "数据源 · web_runtime/tasks" : `数据源 · batch_results/${batchCollection}${activeCollection?.collection_kind === "review" ? "（审阅批次，非生产）" : ""}`}</strong><span>{kind === "history" ? "仅展示网页端任务，不混入离线批处理；运行中与失败任务保留用于追踪。" : `当前模式：${batchMode}。${activeCollection?.collection_kind === "review" ? `完整展示 ${activeCollection.document_count} 篇候选，其中 ${activeCollection.publication_status.partial} 篇仍为 partial；` : ""}批处理结果仅供审核对比，是否可入库以科学校验状态为准。`}</span></div>
      <span className="source-strip-tag">{kind === "history" ? "WEB" : batchMode.toUpperCase()}</span>
    </div>
    <section className="ucard history-metrics-card">
      <div className="ucard-head">
        <div><h3>关系规模总览</h3><p>{kind === "history" ? "WEB EXTRACTION HISTORY" : `OFFLINE BATCH · ${batchCollection.toUpperCase()}`}</p></div>
        <span className="step-chip">01</span>
      </div>
      <div className="history-metrics">
        <Metric icon={<FileSearch size={19} />} label="文献" value={rows.length} tone="blue" />
        <Metric icon={<Boxes size={19} />} label="聚合物实体" value={totals.polymer_count} tone="violet" />
        <Metric icon={<Beaker size={19} />} label="具体样品" value={totals.sample_count} tone="cyan" />
        <Metric icon={<Gauge size={19} />} label="性质观测" value={totals.property_count} tone="orange" />
      </div>
    </section>
    <section className="ucard history-table-card">
      <div className="ucard-head"><div><h3>{kind === "history" ? "网页任务记录" : `${batchCollection} 文献记录`}</h3><p>每行显示文献及其关系链规模，点击后进入完整关系、图谱和样品详情。</p></div><span className="step-chip">02</span></div>
      <div className="history-table-wrap">
        <Table rowKey="key" columns={columns} dataSource={showSkeleton ? skeletonRows : rows} pagination={showSkeleton ? false : zhPagination({ pageSize: 10 })} scroll={{ x: 1110 }} locale={{ emptyText: <Empty description={kind === "history" ? "还没有网页抽取记录" : "未发现可发布的批处理结果"} /> }} />
      </div>
    </section>
  </div>;
}
