import type { ReactNode } from "react";
import { Button, Progress, Skeleton, Space, Tag, Typography } from "antd";
import type { TablePaginationConfig } from "antd";
import type { TableProps } from "antd";
import { Database, UploadCloud } from "lucide-react";
const { Title, Text, Paragraph } = Typography;

export function confidenceTag(score?: number) {
  if (score === undefined) return <Tag>未评分</Tag>;
  const color = score >= 0.9 ? "success" : score >= 0.75 ? "warning" : "error";
  return <Tag color={color}>{Math.round(score * 100)}%</Tag>;
}
export function PageTitle({ title, description, meta, actions }: { title: string; description: string; meta?: string; actions?: ReactNode }) {
  return (
    <div className="page-title-row">
      <div>{meta && <Text className="page-meta">{meta}</Text>}<Title level={2}>{title}</Title><Paragraph>{description}</Paragraph></div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}
export function ScoreBar({ value, label, color = "#3f6fb5" }: { value: number; label: string; color?: string }) {
  const percent = Math.round(value * 1000) / 10;
  return <div className="quality-score"><div><span>{label}</span><strong>{percent.toFixed(1)}%</strong></div><Progress percent={percent} showInfo={false} strokeColor={color} trailColor="#e8ebf0" strokeLinecap="round" size="small" /></div>;
}
export function Metric({ icon, label, value, tone }: { icon: ReactNode; label: string; value: ReactNode; tone: string }) {
  return <div className="metric-item"><div className={`metric-icon ${tone}`}>{icon}</div><div><span>{label}</span><strong>{value}</strong></div></div>;
}
export function TableSkeleton() {
  return <div className="table-skeleton" aria-label="表格加载中"><Skeleton active title={false} paragraph={{ rows: 5, width: "100%" }} /></div>;
}
export function tableLoading(loading: boolean): TableProps["loading"] {
  return loading ? { spinning: true, indicator: <TableSkeleton /> } : false;
}
export const zhPaginationLocale = {
  items_per_page: "条/页",
  jump_to: "跳至",
  jump_to_confirm: "确定",
  page: "页",
  prev_page: "上一页",
  next_page: "下一页",
  prev_5: "向前 5 页",
  next_5: "向后 5 页",
  prev_3: "向前 3 页",
  next_3: "向后 3 页",
};
export function zhPagination(overrides: TablePaginationConfig = {}): TablePaginationConfig {
  return {
    showQuickJumper: true,
    showSizeChanger: true,
    showTotal: (total, range) => `第 ${range[0]}-${range[1]} 条，共 ${total} 条`,
    ...overrides,
    locale: { ...zhPaginationLocale, ...(overrides.locale || {}) },
  };
}
export function NoResult({ onUpload, onSample }: { onUpload: () => void; onSample: () => void }) {
  return <div className="empty-page"><div className="empty-illustration"><Database size={34} /></div><Title level={3}>尚未生成抽取结果</Title><Paragraph>先上传一篇高分子论文并等待流水线完成。也可以加载内置示例查看页面结构。</Paragraph><Space><Button type="primary" icon={<UploadCloud size={16} />} onClick={onUpload}>上传论文</Button><Button onClick={onSample}>加载示例</Button></Space></div>;
}
