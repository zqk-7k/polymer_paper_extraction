import { Select } from "antd";
import { ChevronDown } from "lucide-react";
import type { BatchCollectionSummary } from "../types";

export default function BatchSwitcher({
  collections,
  value,
  onChange,
}: {
  collections: BatchCollectionSummary[];
  value?: string;
  onChange?: (collectionId: string) => void;
}) {
  const active =
    collections.find((c) => c.collection_id === value) ??
    collections.find((c) => c.is_active) ??
    collections[0];
  return (
    <div className="batch-switcher2">
      <span className="batch-switcher2-label">批次</span>
      <span className="batch-switcher2-sep" />
      <Select
        className="batch-switcher2-select"
        popupClassName="batch-switcher2-popup"
        variant="borderless"
        value={active?.collection_id}
        onChange={onChange}
        placeholder="选择批次"
        showSearch
        suffixIcon={<ChevronDown size={14} />}
        optionFilterProp="searchText"
        labelRender={(props) => {
          const item = collections.find((c) => c.collection_id === props.value);
          if (!item) return <span>选择批次</span>;
          return (
            <span className="batch-switcher2-value">
              <i className={`dot ${item.collection_kind}`} />
              <span className="id">{item.collection_id}</span>
            </span>
          );
        }}
        options={collections.map((item) => ({
          value: item.collection_id,
          searchText: `${item.collection_id} ${item.result_date}`,
          label: (
            <span className="batch-opt2">
              <span className="row1">
                <i className={`dot ${item.collection_kind}`} />
                <span className="id">{item.collection_id}</span>
                {item.is_active && <span className="cur">当前</span>}
              </span>
              <span className="row2">
                {item.collection_kind === "review" ? "审阅" : "生产"} · {item.result_date} ·{" "}
                {item.paired_documents}/{item.document_count} 篇 · F1 {(item.anchor.f1 * 100).toFixed(1)}%
              </span>
            </span>
          ),
        }))}
      />
      {active && (
        <span className={`batch-switcher2-kind ${active.collection_kind}`}>
          {active.collection_kind === "review" ? "审阅" : "生产"}
        </span>
      )}
    </div>
  );
}
