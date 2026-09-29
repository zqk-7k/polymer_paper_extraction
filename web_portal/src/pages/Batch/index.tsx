
import { useEffect } from "react";
import { ArchiveResultsPage } from "../../components/ArchiveView";
import { useExtraction } from "../../store/extraction";

export default function BatchRoute() {
  const s = useExtraction();
  useEffect(() => {
    s.ensureBatchPage("batch");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <ArchiveResultsPage
      kind="batch"
      loading={s.archiveLoading}
      historyTasks={[]}
      batchResults={s.batchResults}
      batchCollections={s.batchCollections}
      selectedCollectionId={s.selectedBatchCollectionId}
      onCollection={s.selectBatchCollection}
      onRefresh={() => void s.refreshBatchResults(s.selectedBatchCollectionId)}
      onOpenHistory={(t) => void s.openHistoryTask(t)}
      onOpenBatch={(b) => void s.openBatchResult(b)}
    />
  );
}
