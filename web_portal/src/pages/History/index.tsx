
import { useEffect } from "react";
import { ArchiveResultsPage } from "../../components/ArchiveView";
import { useExtraction } from "../../store/extraction";

export default function HistoryRoute() {
  const s = useExtraction();
  useEffect(() => {
    void s.refreshHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <ArchiveResultsPage
      kind="history"
      loading={s.archiveLoading}
      historyTasks={s.historyTasks}
      batchResults={[]}
      onRefresh={() => void s.refreshHistory()}
      onOpenHistory={(t) => void s.openHistoryTask(t)}
      onOpenBatch={(b) => void s.openBatchResult(b)}
    />
  );
}
