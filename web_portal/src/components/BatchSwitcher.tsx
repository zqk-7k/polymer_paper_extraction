import { Empty, Input, Popover } from "antd";
import { Check, ChevronDown, Layers3, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { BatchCollectionSummary } from "../types";

export default function BatchSwitcher({
  collections,
  value,
  onChange,
  compact = false,
}: {
  collections: BatchCollectionSummary[];
  value?: string;
  onChange?: (collectionId: string) => void;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const active =
    collections.find((item) => item.collection_id === value) ??
    collections.find((item) => item.is_active) ??
    collections[0];
  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return collections;
    return collections.filter((item) =>
      `${item.collection_id} ${item.result_date} ${item.collection_kind}`.toLowerCase().includes(keyword),
    );
  }, [collections, query]);

  const panel = (
    <div className="batch-switcher-panel">
      <div className="batch-switcher-panel-head">
        <div>
          <strong>选择数据批次</strong>
          <span>切换后，页面指标与文献结果将同步更新</span>
        </div>
        <span className="batch-switcher-count">{collections.length}</span>
      </div>
      <Input
        className="batch-switcher-search"
        prefix={<Search size={14} />}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="搜索批次编号或日期"
        allowClear
        autoFocus
      />
      <div className="batch-switcher-list" role="listbox" aria-label="数据批次">
        {filtered.length ? filtered.map((item) => {
          const selected = item.collection_id === active?.collection_id;
          return (
            <button
              type="button"
              role="option"
              aria-selected={selected}
              className={`batch-switcher-option${selected ? " is-selected" : ""}`}
              key={item.collection_id}
              onClick={() => {
                onChange?.(item.collection_id);
                setOpen(false);
                setQuery("");
              }}
            >
              <span className={`batch-switcher-option-mark ${item.collection_kind}`}><Layers3 size={15} /></span>
              <span className="batch-switcher-option-copy">
                <span className="batch-switcher-option-title">
                  <strong>{item.collection_id}</strong>
                  {item.is_active && <em>当前</em>}
                </span>
                <span className="batch-switcher-option-meta">
                  <span>{item.result_date}</span>
                  <span>{item.paired_documents}/{item.document_count} 篇</span>
                  <span>F1 {(item.anchor.f1 * 100).toFixed(1)}%</span>
                </span>
              </span>
              <span className={`batch-switcher-option-type ${item.collection_kind}`}>
                <i />{item.collection_kind === "review" ? "审阅" : "生产"}
              </span>
              <span className="batch-switcher-option-check"><Check size={15} strokeWidth={2.4} /></span>
            </button>
          );
        }) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有匹配的批次" />}
      </div>
    </div>
  );

  return (
    <Popover
      content={panel}
      trigger="click"
      placement="bottomRight"
      arrow={false}
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen) setQuery("");
      }}
      overlayClassName="batch-switcher-popover"
    >
      <button
        type="button"
        className={`batch-switcher2${compact ? " is-compact" : ""}${open ? " is-open" : ""}`}
        aria-label="切换数据批次"
        aria-expanded={open}
      >
        <span className="batch-switcher2-icon" aria-hidden="true"><Layers3 size={16} /></span>
        <span className="batch-switcher2-copy">
          <span className="batch-switcher2-eyebrow">
            <span>当前数据批次</span>
            {active && <i className={active.collection_kind}>{active.collection_kind === "review" ? "审阅" : "生产"}</i>}
          </span>
          <strong>{active?.collection_id || "选择批次"}</strong>
        </span>
        {active && <span className="batch-switcher2-meta"><b>{active.result_date}</b><small>{active.paired_documents}/{active.document_count} 篇</small></span>}
        <span className="batch-switcher2-chevron"><ChevronDown size={15} /></span>
      </button>
    </Popover>
  );
}
