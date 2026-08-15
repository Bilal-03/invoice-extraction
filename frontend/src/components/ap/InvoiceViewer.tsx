import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, ReceiptIndianRupee } from "lucide-react";
import type { Invoice } from "../../lib/api-client";
import { fetchFileBlob, resolveFileUrl } from "../../lib/api-client";

export function InvoiceViewer({ invoice }: { invoice: Invoice }) {
  const [src, setSrc] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => { setPage(1); }, [invoice.document_id]);
  useEffect(() => {
    let active = true;
    let objectUrl = "";
    if (!invoice.preview_url) { setSrc(""); return; }
    const separator = invoice.preview_url.includes("?") ? "&" : "?";
    void fetchFileBlob(resolveFileUrl(`${invoice.preview_url}${separator}page=${page}`))
      .then((url) => { objectUrl = url; if (active) setSrc(url); })
      .catch(() => undefined);
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [invoice.preview_url, page]);
  const locations = Object.entries(invoice.extraction?.field_locations || {}).filter(([, box]) => box.page === page - 1);
  return (
    <aside className="source-card panel">
      <div className="panel-heading"><div><span className="eyebrow">Source document</span><h2>Evidence view</h2></div><span className="muted-text">{invoice.filename || "Preview unavailable"}</span></div>
      <div className="source-page-controls"><button className="icon-button tiny-icon" disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))} aria-label="Previous page"><ArrowLeft size={14} /></button><span>Page {page} of {Math.max(1, invoice.page_count)}</span><button className="icon-button tiny-icon" disabled={page >= invoice.page_count} onClick={() => setPage((current) => Math.min(invoice.page_count, current + 1))} aria-label="Next page"><ArrowRight size={14} /></button></div>
      <div className={`document-canvas ${src ? "has-image" : ""}`} style={src ? { backgroundImage: `url(${src})` } : undefined}>{!src && <div className="document-placeholder"><ReceiptIndianRupee size={29} /><strong>Invoice source</strong><span>Upload preview will appear after the document is stored.</span><i /><i /><i /></div>}{locations.slice(0, 10).map(([key, box]) => <span className="evidence-box" key={key} style={{ left: `${box.x0 * 100}%`, top: `${box.y0 * 100}%`, width: `${(box.x1 - box.x0) * 100}%`, height: `${(box.y1 - box.y0) * 100}%` }} title={key} />)}</div>
      <div className="source-legend"><span><i className="green-dot" /> OCR / rules</span><span><i className="violet-dot" /> Local AI</span><span><i className="amber-dot" /> Review signal</span></div>
    </aside>
  );
}
