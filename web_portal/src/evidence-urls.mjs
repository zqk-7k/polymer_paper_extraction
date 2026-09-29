/** Preserve the collection query when addressing a zero-based PDF page. */
export function evidencePageUrl(pdfUrl, page) {
  if (!Number.isInteger(page) || page < 0) throw new RangeError("Invalid PDF page");
  const url = new URL(pdfUrl, "http://evidence.local");
  url.pathname = `${url.pathname.replace(/\/$/, "")}/pages/${page}`;
  url.hash = "";
  return /^https?:\/\//i.test(pdfUrl) ? url.href : `${url.pathname}${url.search}`;
}

/** A missing batch PDF must never fall back to an unrelated example paper. */
export function batchPdfUrl(apiBase, batch) {
  if (batch.pdf_url) return `${apiBase}${batch.pdf_url}`;
  const query = batch.collection_id ? `?collection=${encodeURIComponent(batch.collection_id)}` : "";
  return `${apiBase}/api/batch-results/${encodeURIComponent(batch.ref_no)}/pdf${query}`;
}
