import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useDropzone } from "react-dropzone";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  CalendarClock,
  Check,
  ChevronRight,
  CircleDollarSign,
  ClipboardCheck,
  FileDown,
  FileUp,
  Files,
  Loader2,
  PackageCheck,
  Plus,
  ReceiptIndianRupee,
  RefreshCw,
  Search,
  ShieldAlert,
  Store,
  WalletCards,
  X,
} from "lucide-react";
import {
  Link,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  apiClient,
  type APAnalytics,
  type DashboardSummary,
  type DocumentResponse,
  type GSTSummary,
  type Invoice,
  type InvoiceList,
  type InvoiceQuestionResponse,
  type PaymentDue,
  type PurchaseOrder,
  type Vendor,
  type DocumentUploadResponse,
  downloadFile,
  formatDate,
  formatINR,
  uploadDocument,
} from "../lib/api-client";
import { Input } from "../components/ui/input";
import {
  AgingBars,
  EmptyState,
  ExtractionEditor,
  InvoiceTable,
  InvoiceUploader,
  InvoiceViewer,
  LoadingRow,
  MetricCard,
  PageHeader,
  RiskBadge,
  StatusPill,
  ValidationPanel,
  VendorCard,
} from "../components/ap";
export function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [analytics, setAnalytics] = useState<APAnalytics | null>(null);
  const [gst, setGst] = useState<GSTSummary | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [analyticsResponse, invoiceResponse, gstResponse] = await Promise.all([
        apiClient.get<APAnalytics>("/analytics/ap"),
        apiClient.get<InvoiceList>("/invoices?page_size=8"),
        apiClient.get<GSTSummary>("/analytics/ap/gst"),
      ]);
      setAnalytics(analyticsResponse.data);
      setSummary(analyticsResponse.data.summary);
      setGst(gstResponse.data);
      setInvoices(invoiceResponse.data.invoices);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const emptySummary: DashboardSummary = { total_invoices: 0, processing_invoices: 0, review_invoices: 0, approved_invoices: 0, awaiting_payment_invoices: 0, paid_invoices: 0, rejected_invoices: 0, duplicate_invoices: 0, on_hold_invoices: 0, outstanding_total: 0, due_this_week: 0, overdue_total: 0, high_risk_count: 0, average_confidence: 0, total_tax: 0, aging: [] };
  const data = summary || emptySummary;
  return <>
    <PageHeader eyebrow="Accounts payable" title="A clearer ledger for every invoice" description="Extraction, verification, approvals, and payment visibility in one workspace." action={<><button className="secondary-button" onClick={() => void load()}><RefreshCw size={15} /> Refresh</button><Link className="primary-button" to="/upload"><FileUp size={15} /> Upload invoices</Link></>} />
    <div className="metric-grid">
      <MetricCard label="Invoices" value={String(data.total_invoices)} detail="Uploaded to the ledger" icon={Files} tone="blue" />
      <MetricCard label="Outstanding" value={formatINR(data.outstanding_total)} detail={`${data.awaiting_payment_invoices} invoices awaiting payment`} icon={CircleDollarSign} tone="green" />
      <MetricCard label="Due this week" value={formatINR(data.due_this_week)} detail="Scheduled payable exposure" icon={CalendarClock} tone="amber" />
      <MetricCard label="Overdue" value={formatINR(data.overdue_total)} detail={`${data.high_risk_count} high-risk records`} icon={AlertTriangle} tone="red" />
    </div>
    <div className="dashboard-grid">
      <section className="panel span-two"><div className="panel-heading"><div><span className="eyebrow">Action queue</span><h2>Recent invoices</h2></div><Link to="/invoices" className="text-link">View all <ArrowRight size={14} /></Link></div>{loading ? <LoadingRow /> : invoices.length === 0 ? <EmptyState icon={Files} title="Your ledger is empty" body="Upload an invoice or load the seeded workspace to see AP activity." action={<Link className="secondary-button" to="/upload">Start with an upload</Link>} /> : <InvoiceTable invoices={invoices} compact />}</section>
      <section className="panel"><div className="panel-heading"><div><span className="eyebrow">AP aging</span><h2>Outstanding by age</h2></div></div><AgingBars buckets={data.aging} /></section>
      <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Control center</span><h2>Workflow status</h2></div></div><div className="status-summary"><StatusCount label="Processing" value={data.processing_invoices} tone="processing" /><StatusCount label="Review required" value={data.review_invoices} tone="review_required" /><StatusCount label="Approved" value={data.approved_invoices} tone="approved" /><StatusCount label="Paid" value={data.paid_invoices} tone="paid" /></div><div className="control-footnote">{data.on_hold_invoices} on hold · {data.duplicate_invoices} duplicate · {data.rejected_invoices} rejected</div><Link className="full-width-button" to="/review">Open review queue <ChevronRight size={15} /></Link></section>
    </div>
    <DashboardCharts analytics={analytics} gst={gst} summary={data} />
  </>;
}

function StatusCount({ label, value, tone }: { label: string; value: number; tone: string }) { return <div className="status-count"><span className={`status-icon ${tone}`}><i /></span><div><strong>{value}</strong><small>{label}</small></div></div>; }

function DashboardCharts({ analytics, gst, summary }: { analytics: APAnalytics | null; gst: GSTSummary | null; summary: DashboardSummary }) {
  const monthly = monthlyTrend(analytics?.trends || []);
  const volume = monthly.length ? monthly : [{ label: "Now", count: summary.total_invoices, confidence: summary.average_confidence }];
  const volumeMax = Math.max(...volume.map((point) => point.count), 1);
  const accuracyMax = 1;
  const vendors = analytics?.vendors.slice(0, 6) || [];
  const vendorMax = Math.max(...vendors.map((vendor) => vendor.total_spend), 1);
  const taxes = Object.entries(gst?.by_type || {}).filter(([, amount]) => Number(amount) > 0).sort(([, a], [, b]) => Number(b) - Number(a));
  const taxMax = Math.max(...taxes.map(([, amount]) => Number(amount)), 1);
  const statuses = [
    { label: "Paid", value: summary.paid_invoices, tone: "paid" },
    { label: "Awaiting payment", value: summary.awaiting_payment_invoices, tone: "awaiting" },
    { label: "Approved", value: summary.approved_invoices, tone: "approved" },
    { label: "Review", value: summary.review_invoices, tone: "review" },
    { label: "Processing", value: summary.processing_invoices, tone: "processing" },
    { label: "Other controls", value: summary.on_hold_invoices + summary.duplicate_invoices + summary.rejected_invoices, tone: "other" },
  ];
  const statusTotal = Math.max(statuses.reduce((total, item) => total + item.value, 0), 1);
  return <div className="chart-grid">
    <section className="panel chart-card chart-wide"><div className="panel-heading"><div><span className="eyebrow">Volume trend</span><h2>Monthly invoice volume</h2></div><span className="muted-text">{summary.total_invoices} total records</span></div><div className="chart-bars">{volume.slice(-8).map((point) => <div className="chart-bar" key={point.label}><strong>{point.count}</strong><i style={{ height: `${Math.max(8, (point.count / volumeMax) * 100)}%` }} /><small>{point.label}</small></div>)}</div></section>
    <section className="panel chart-card"><div className="panel-heading"><div><span className="eyebrow">Concentration</span><h2>Vendor spend</h2></div></div>{vendors.length ? <div className="chart-list">{vendors.map((vendor) => <div className="chart-list-row" key={vendor.vendor_name}><div><span>{vendor.vendor_name}</span><strong>{formatINR(vendor.total_spend)}</strong></div><div className="bar-track"><i style={{ width: `${Math.max(3, (vendor.total_spend / vendorMax) * 100)}%` }} /></div></div>)}</div> : <p className="inline-empty">Vendor spend will appear after invoices are projected.</p>}</section>
    <section className="panel chart-card"><div className="panel-heading"><div><span className="eyebrow">Cash position</span><h2>Payment status</h2></div></div><div className="status-stack">{statuses.map((item) => <i className={`status-segment ${item.tone}`} key={item.label} style={{ width: `${Math.max(1, (item.value / statusTotal) * 100)}%` }} />)}</div><div className="chart-legend">{statuses.map((item) => <span key={item.label}><i className={`legend-dot ${item.tone}`} />{item.label}<strong>{item.value}</strong></span>)}</div></section>
    <section className="panel chart-card"><div className="panel-heading"><div><span className="eyebrow">Tax ledger</span><h2>Tax breakdown</h2></div><span className="money-total">{formatINR(gst?.total_tax || summary.total_tax)}</span></div>{taxes.length ? <div className="chart-list">{taxes.map(([taxType, amount]) => <div className="chart-list-row" key={taxType}><div><span>{taxType.replaceAll("_", " ")}</span><strong>{formatINR(Number(amount))}</strong></div><div className="bar-track"><i className="tax-bar" style={{ width: `${Math.max(3, (Number(amount) / taxMax) * 100)}%` }} /></div></div>)}</div> : <p className="inline-empty">Tax breakdown will appear after tax rows are extracted.</p>}</section>
    <section className="panel chart-card chart-wide"><div className="panel-heading"><div><span className="eyebrow">Quality signal</span><h2>Invoice processing accuracy</h2></div><span className="confidence-score"><strong>{Math.round(summary.average_confidence * 100)}%</strong> average confidence</span></div><div className="chart-bars accuracy-bars">{volume.slice(-8).map((point) => <div className="chart-bar" key={`accuracy-${point.label}`}><strong>{Math.round(point.confidence * 100)}%</strong><i style={{ height: `${Math.max(8, point.confidence * 100 / accuracyMax)}%` }} /><small>{point.label}</small></div>)}</div><p className="chart-caption">Confidence is a deterministic extraction-quality signal; human review remains the final control.</p></section>
  </div>;
}

function monthlyTrend(trends: APAnalytics["trends"]): { label: string; count: number; confidence: number }[] {
  const grouped = new Map<string, { count: number; confidenceTotal: number; points: number }>();
  trends.forEach((point) => {
    const key = point.date.slice(0, 7);
    const current = grouped.get(key) || { count: 0, confidenceTotal: 0, points: 0 };
    current.count += point.document_count;
    current.confidenceTotal += point.average_confidence;
    current.points += 1;
    grouped.set(key, current);
  });
  return [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([key, value]) => ({
    label: new Date(`${key}-01T00:00:00`).toLocaleDateString("en-IN", { month: "short", year: "2-digit" }),
    count: value.count,
    confidence: value.points ? value.confidenceTotal / value.points : 0,
  }));
}

type PendingUpload = {
  id: string;
  file: File;
  previewUrl: string;
  progress: number;
  status: "ready" | "uploading" | "uploaded" | "error";
  error?: string;
};

function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function UploadPage() {
  const [queue, setQueue] = useState<{ id: string; name: string; status: string; invoiceId?: string }[]>([]);
  const [pendingFiles, setPendingFiles] = useState<PendingUpload[]>([]);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState("");
  const onDrop = useCallback((files: File[]) => {
    if (!files.length) return;
    setMessage("");
    setPendingFiles((current) => {
      const remaining = Math.max(0, 25 - current.length);
      return [...current, ...files.slice(0, remaining).map((file) => ({
        id: `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
        file,
        previewUrl: URL.createObjectURL(file),
        progress: 0,
        status: "ready" as const,
      }))];
    });
  }, []);
  const dropzone = useDropzone({
    onDrop,
    onDropRejected: (rejections) => setMessage(`${rejections.length} file${rejections.length === 1 ? " was" : "s were"} rejected. Check type, size, or the 25-file limit.`),
    multiple: true,
    maxFiles: 25,
    maxSize: 20 * 1024 * 1024,
    disabled: uploading,
    accept: { "application/pdf": [".pdf"], "image/jpeg": [".jpg", ".jpeg"], "image/png": [".png"], "image/tiff": [".tif", ".tiff"] },
  });
  const removePending = (id: string) => {
    setPendingFiles((current) => {
      const item = current.find((candidate) => candidate.id === id);
      if (item) URL.revokeObjectURL(item.previewUrl);
      return current.filter((candidate) => candidate.id !== id);
    });
  };
  const uploadSelectedFiles = async () => {
    const candidates = pendingFiles.filter((item) => item.status === "ready" || item.status === "error");
    if (!candidates.length) return;
    setUploading(true); setMessage("");
    const uploaded: { candidate: PendingUpload; document: DocumentUploadResponse }[] = [];
    await Promise.all(candidates.map(async (candidate) => {
      setPendingFiles((current) => current.map((item) => item.id === candidate.id ? { ...item, status: "uploading", progress: 1, error: undefined } : item));
      try {
        const document = await uploadDocument(candidate.file, (progress) => {
          setPendingFiles((current) => current.map((item) => item.id === candidate.id ? { ...item, progress } : item));
        });
        uploaded.push({ candidate, document });
        setPendingFiles((current) => current.map((item) => item.id === candidate.id ? { ...item, status: "uploaded", progress: 100 } : item));
      } catch (error) {
        const detail = (error as { response?: { data?: { detail?: string } } }).response?.data?.detail || "Upload failed";
        setPendingFiles((current) => current.map((item) => item.id === candidate.id ? { ...item, status: "error", error: String(detail) } : item));
      }
    }));
    uploaded.forEach(({ candidate }) => URL.revokeObjectURL(candidate.previewUrl));
    setPendingFiles((current) => current.filter((item) => !uploaded.some(({ candidate }) => candidate.id === item.id)));
    setQueue((current) => [...uploaded.map(({ candidate, document }) => ({ id: document.document_id, name: candidate.file.name, status: document.status })), ...current]);
    setMessage(`${uploaded.length} invoice${uploaded.length === 1 ? "" : "s"} added to the processing queue${uploaded.length < candidates.length ? "; review failed uploads below" : "."}`);
    setUploading(false);
  };
  useEffect(() => {
    if (!queue.some((item) => ["pending", "preprocessing", "ocr", "extracting", "validating"].includes(item.status))) return;
    const timer = window.setInterval(() => {
      void Promise.all(queue.map(async (item) => {
        if (item.status === "failed" || (item.status === "completed" && item.invoiceId)) return item;
        try {
          const response = await apiClient.get<DocumentResponse>(`/documents/${item.id}`);
          let invoiceId = item.invoiceId;
          if (response.data.status === "completed" && !invoiceId) {
            try { const invoice = await apiClient.get<Invoice>(`/documents/${item.id}/invoice`); invoiceId = invoice.data.id; } catch { /* projection may still be committing */ }
          }
          return { ...item, status: response.data.status, invoiceId };
        } catch { return item; }
      })).then(setQueue);
    }, 1800);
    return () => window.clearInterval(timer);
  }, [queue]);
  return <>
    <PageHeader eyebrow="Ingestion" title="Upload invoices into the ledger" description="Drop PDFs or images here. The local pipeline keeps the source document, field evidence, and review state together." />
    <InvoiceUploader dropzone={dropzone} uploading={uploading} />
    {pendingFiles.length > 0 && <section className="panel selected-upload-panel"><div className="panel-heading"><div><span className="eyebrow">Before processing</span><h2>Selected invoices</h2></div><span className="muted-text">{pendingFiles.length}/25 files</span></div><div className="selected-files">{pendingFiles.map((item) => <div className="selected-file" key={item.id}><div className="selected-thumb">{item.file.type.startsWith("image/") ? <img src={item.previewUrl} alt="Invoice preview" /> : item.file.type === "application/pdf" ? <iframe src={item.previewUrl} title={`${item.file.name} preview`} /> : <Files size={22} />}</div><div className="selected-file-main"><strong>{item.file.name}</strong><small>{formatFileSize(item.file.size)} · {item.status === "error" ? item.error : item.status === "uploaded" ? "Uploaded" : item.status === "uploading" ? `Uploading ${item.progress}%` : "Ready to upload"}</small>{item.status === "uploading" && <div className="upload-progress"><i style={{ width: `${item.progress}%` }} /></div>}</div><button type="button" className="icon-button tiny-icon" aria-label={`Remove ${item.file.name}`} disabled={item.status === "uploading"} onClick={(event) => { event.stopPropagation(); removePending(item.id); }}><X size={14} /></button></div>)}</div><div className="selected-upload-actions"><button className="secondary-button" type="button" onClick={() => pendingFiles.forEach((item) => removePending(item.id))} disabled={uploading}>Remove all</button><button className="primary-button" type="button" onClick={() => void uploadSelectedFiles()} disabled={uploading || !pendingFiles.some((item) => item.status === "ready" || item.status === "error")}><FileUp size={15} /> Upload {pendingFiles.filter((item) => item.status === "ready" || item.status === "error").length} file{pendingFiles.filter((item) => item.status === "ready" || item.status === "error").length === 1 ? "" : "s"}</button></div></section>}
    {message && <div className="notice success"><Check size={16} />{message}</div>}
    <section className="panel upload-queue"><div className="panel-heading"><div><span className="eyebrow">Live queue</span><h2>Processing activity</h2></div><span className="muted-text">{queue.length} documents</span></div>{queue.length === 0 ? <EmptyState icon={Files} title="Nothing waiting" body="Uploaded files will show their pipeline stage and AP link here." /> : <div className="queue-list">{queue.map((item) => <div className="queue-item" key={item.id}><span className="file-icon"><Files size={17} /></span><div><strong>{item.name}</strong><small>{item.id.slice(0, 8)} · {item.status}</small></div><span className={`queue-status ${item.status}`}>{["pending", "preprocessing", "ocr", "extracting", "validating"].includes(item.status) && <Loader2 size={13} className="spin" />}{item.status === "completed" ? "Ready for review" : item.status === "failed" ? "Failed" : item.status}</span>{item.invoiceId ? <Link className="secondary-button tiny" to={`/invoices/${item.invoiceId}`}>Review <ArrowRight size={13} /></Link> : <span className="muted-text">Waiting</span>}</div>)}</div>}</section>
  </>;
}

export function InvoicesPage() {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<InvoiceList | null>(null);
  const [loading, setLoading] = useState(true);
  const search = params.get("search") || "";
  const status = params.get("status") || "";
  const load = useCallback(async () => { setLoading(true); try { const response = await apiClient.get<InvoiceList>("/invoices", { params: { search: search || undefined, status: status || undefined, page_size: 50 } }); setData(response.data); } finally { setLoading(false); } }, [search, status]);
  useEffect(() => { void load(); }, [load]);
  const setFilter = (key: string, value: string) => { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); setParams(next); };
  return <>
    <PageHeader eyebrow="Invoice ledger" title="All invoices" description="Search the structured AP record, inspect evidence, and move work through the control states." action={<><button className="secondary-button" onClick={() => void downloadFile("/invoices/export?format=xlsx", "invoices.xlsx")}><FileDown size={15} /> Export XLSX</button><Link className="primary-button" to="/upload"><Plus size={15} /> Add invoice</Link></>} />
    <div className="filter-bar"><div className="filter-search"><Search size={16} /><Input className="filter-input" value={search} onChange={(event) => setFilter("search", event.target.value)} placeholder="Search invoice, vendor, GSTIN, PO…" /></div><select value={status} onChange={(event) => setFilter("status", event.target.value)}><option value="">All statuses</option><option value="review_required">Review required</option><option value="approved">Approved</option><option value="awaiting_payment">Awaiting payment</option><option value="paid">Paid</option><option value="on_hold">On hold</option><option value="duplicate">Duplicate</option></select><button className="icon-button" onClick={() => void load()} aria-label="Refresh invoices"><RefreshCw size={16} /></button></div>
    <section className="panel table-panel">{loading ? <LoadingRow /> : data && data.invoices.length ? <InvoiceTable invoices={data.invoices} /> : <EmptyState icon={ReceiptIndianRupee} title="No invoices match" body="Try a different filter or upload your first invoice." action={<Link className="primary-button" to="/upload">Upload invoice</Link>} />}</section>
  </>;
}

export function ReviewQueuePage() {
  const [data, setData] = useState<InvoiceList | null>(null);
  useEffect(() => { void apiClient.get<InvoiceList>("/invoices?status=review_required&page_size=50").then((response) => setData(response.data)); }, []);
  return <><PageHeader eyebrow="Human-in-the-loop" title="Review queue" description="Resolve low-confidence fields and risk signals before anything moves to payment." action={<Link className="secondary-button" to="/invoices"><Files size={15} /> Browse all invoices</Link>} /><section className="panel table-panel">{data?.invoices.length ? <InvoiceTable invoices={data.invoices} /> : data ? <EmptyState icon={BadgeCheck} title="Queue is clear" body="No invoices currently require human review." action={<Link className="primary-button" to="/upload">Upload next invoice</Link>} /> : <LoadingRow />}</section></>;
}

export function InvoicePage() {
  const { invoiceId } = useParams();
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [overrideNeeded, setOverrideNeeded] = useState(false);
  const [showPayment, setShowPayment] = useState(false);
  const load = useCallback(async () => { if (!invoiceId) return; setLoading(true); try { const response = await apiClient.get<Invoice>(`/invoices/${invoiceId}`); setInvoice(response.data); } catch { setError("Invoice could not be loaded."); } finally { setLoading(false); } }, [invoiceId]);
  useEffect(() => { void load(); }, [load]);
  const action = async (name: string, override = false) => { if (!invoiceId) return; setActionError(""); try { const response = await apiClient.post<Invoice>(`/invoices/${invoiceId}/actions`, { action: name, override, actor: "local_user" }); setInvoice(response.data); setOverrideNeeded(false); } catch (requestError) { const detail = (requestError as { response?: { data?: { detail?: string } } }).response?.data?.detail || "That workflow action could not be completed."; setActionError(detail); if (name === "approve") setOverrideNeeded(true); } };
  if (loading) return <LoadingRow />;
  if (!invoice || error) return <div className="notice error"><AlertTriangle size={16} />{error || "Invoice not found."}</div>;
  const extraction = invoice.extraction;
  const blocking = invoice.validations.some((item) => !item.passed && item.severity === "error");
  const readyForApproval = invoice.status === "review_required" && invoice.overall_confidence >= 0.85 && !blocking && invoice.risk_level !== "high" && invoice.match_status !== "mismatch";
  return <>
    <div className="detail-breadcrumb"><Link to="/invoices"><ArrowLeft size={14} /> Invoices</Link><span>/</span><span>{invoice.invoice_number || "Unnumbered invoice"}</span></div>
    <PageHeader eyebrow={`${invoice.filename || "Invoice document"} · ${invoice.document_id.slice(0, 8)}`} title={invoice.invoice_number || "Unnumbered invoice"} description={`${invoice.vendor?.name || "Unknown vendor"} · ${formatDate(invoice.invoice_date)}`} action={<div className="detail-actions"><StatusPill status={invoice.status} /><StatusPill status={invoice.processing_status || "completed"} /><RiskBadge level={invoice.risk_level} score={invoice.risk_score} /></div>} />
    {invoice.status === "review_required" && <div className={`readiness-banner ${readyForApproval ? "ready" : "needs-review"}`}><span className="readiness-dot" /><strong>{readyForApproval ? "Ready for approval" : "Needs review"}</strong><small>{readyForApproval ? "High-confidence extraction with no blocking controls." : "Resolve uncertain fields, validation flags, or risk signals before approval."}</small></div>}
    {actionError && <div className="notice warning"><ShieldAlert size={16} /><span>{actionError}</span>{overrideNeeded && <button className="text-button" onClick={() => void action("approve", true)}>Approve with override</button>}<button className="icon-button tiny-icon" onClick={() => setActionError("")}><X size={14} /></button></div>}
    <div className="detail-actions-row"><button className="secondary-button" onClick={() => void action("hold")}><CalendarClock size={15} /> Hold</button>{invoice.status === "on_hold" && <button className="secondary-button" onClick={() => void action("release")}><RefreshCw size={15} /> Release</button>}{["review_required", "on_hold", "duplicate"].includes(invoice.status) && <button className="primary-button" onClick={() => void action("approve")}><Check size={15} /> Approve</button>}{invoice.status === "approved" && <button className="primary-button" onClick={() => void action("queue_payment")}><WalletCards size={15} /> Queue payment</button>}{["approved", "awaiting_payment"].includes(invoice.status) && <button className="secondary-button" onClick={() => setShowPayment(!showPayment)}><CircleDollarSign size={15} /> Record payment</button>}<button className="secondary-button" onClick={() => void downloadFile(`/invoices/${invoice.id}/export?format=json`, `${invoice.invoice_number || "invoice"}.json`)}><FileDown size={15} /> JSON</button></div>
    {showPayment && <PaymentForm invoice={invoice} onSaved={(next) => { setInvoice(next); setShowPayment(false); }} />}
    <div className="review-layout"><InvoiceViewer invoice={invoice} /><div className="review-column"><section className="panel"><div className="panel-heading"><div><span className="eyebrow">Evidence-led extraction</span><h2>Review fields</h2></div><span className="confidence-score"><strong>{Math.round(invoice.overall_confidence * 100)}%</strong> confidence</span></div><div className="field-grid"><ExtractionEditor label="Invoice number" path="invoice_number.value" value={extraction?.invoice_number?.value || invoice.invoice_number || ""} confidence={extraction?.invoice_number?.confidence} invoiceId={invoice.id} onSaved={setInvoice} /><ExtractionEditor label="Invoice date" path="invoice_date" value={extraction?.invoice_date || invoice.invoice_date || ""} invoiceId={invoice.id} onSaved={setInvoice} /><ExtractionEditor label="Due date" path="due_date" value={extraction?.due_date || invoice.due_date || ""} invoiceId={invoice.id} onSaved={setInvoice} /><ExtractionEditor label="PO reference" path="po_reference.value" value={extraction?.po_reference?.value || invoice.po_number || ""} confidence={extraction?.po_reference?.confidence} invoiceId={invoice.id} onSaved={setInvoice} /><ExtractionEditor label="Vendor" path="vendor.name.value" value={extraction?.vendor?.name?.value || invoice.vendor?.name || ""} confidence={extraction?.vendor?.name?.confidence} invoiceId={invoice.id} onSaved={setInvoice} /><ExtractionEditor label="GSTIN" path="vendor.gstin.value" value={extraction?.vendor?.gstin?.value || invoice.vendor?.gstin || ""} confidence={extraction?.vendor?.gstin?.confidence} invoiceId={invoice.id} onSaved={setInvoice} /><ExtractionEditor label="Vendor PAN" path="vendor.pan.value" value={extraction?.vendor?.pan?.value || invoice.vendor?.pan || ""} confidence={extraction?.vendor?.pan?.confidence} invoiceId={invoice.id} onSaved={setInvoice} /><ExtractionEditor label="Buyer PAN" path="buyer.pan.value" value={extraction?.buyer?.pan?.value || ""} confidence={extraction?.buyer?.pan?.confidence} invoiceId={invoice.id} onSaved={setInvoice} /><ExtractionEditor label="Payment terms" path="payment_terms" value={extraction?.payment_terms || ""} invoiceId={invoice.id} onSaved={setInvoice} /></div></section><InvoiceFinancials invoice={invoice} /><POMatchPanel invoice={invoice} /><EInvoicePanel invoice={invoice} /><InvoiceQAPanel invoice={invoice} /><ValidationPanel invoice={invoice} /><RiskPanel invoice={invoice} /><WorkflowPanel invoice={invoice} /><CorrectionsPanel invoice={invoice} /></div></div>
  </>;
}


function InvoiceFinancials({ invoice }: { invoice: Invoice }) {
  return <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Financials</span><h2>Totals and line items</h2></div><span className="money-total">{formatINR(invoice.grand_total)}</span></div><div className="financial-strip"><div><span>Subtotal</span><strong>{formatINR(invoice.subtotal)}</strong></div><div><span>Tax</span><strong>{formatINR(invoice.tax_total)}</strong></div><div><span>Outstanding</span><strong>{formatINR(invoice.outstanding_amount)}</strong></div></div>{invoice.items.length ? <div className="line-items"><div className="line-head"><span>Description</span><span>HSN</span><span>Qty</span><span>Rate</span><span>GST</span><span>Amount</span></div>{invoice.items.map((item) => <div className="line-row" key={item.id}><span>{item.description}</span><span>{item.hsn_sac || "—"}</span><span>{item.quantity}</span><span>{formatINR(item.unit_price)}</span><span>{item.gst_rate ? `${item.gst_rate}%` : "—"}</span><strong>{formatINR(item.line_total)}</strong></div>)}</div> : <p className="inline-empty">No structured line items were extracted.</p>}</section>;
}

function POMatchPanel({ invoice }: { invoice: Invoice }) {
  if (!invoice.po_number) return null;
  const details = invoice.match_details || {};
  const statusClass = invoice.match_status === "matched" ? "status-approved" : invoice.match_status === "mismatch" ? "status-rejected" : "status-on_hold";
  const message = typeof details.match_message === "string" ? details.match_message : invoice.match_status.replaceAll("_", " ");
  const groups = [
    ["Quantity", "quantity_mismatches"],
    ["Rates", "rate_mismatches"],
    ["Tax", "tax_mismatches"],
    ["Receipts", "receipt_mismatches"],
    ["Vendor", "vendor_mismatches"],
  ] as const;
  const money = (key: string) => {
    const value = details[key];
    return typeof value === "number" || typeof value === "string" ? formatINR(Number(value)) : "—";
  };
  return <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Procurement control</span><h2>{details.match_type === "three_way" ? "Three-way match" : "PO match"}</h2></div><span className={`status-pill ${statusClass}`}><i />{message}</span></div><div className="financial-strip"><div><span>PO</span><strong>{invoice.po_number}</strong></div><div><span>PO total</span><strong>{money("po_total")}</strong></div><div><span>Invoice total</span><strong>{money("invoice_total")}</strong></div><div><span>Tax difference</span><strong>{money("tax_difference")}</strong></div></div>{groups.some(([, key]) => Array.isArray(details[key]) && details[key].length > 0) ? <div className="validation-list">{groups.flatMap(([label, key]) => Array.isArray(details[key]) ? details[key].map((entry, index) => <div className="validation-row failed" key={`${key}-${index}`}><span><AlertTriangle size={14} /></span><div><strong>{label} check</strong><small>{typeof entry === "object" ? JSON.stringify(entry) : String(entry)}</small></div><em>review</em></div>) : [])}</div> : <div className="clear-state"><BadgeCheck size={17} /> {message}</div>}</section>;
}

function EInvoicePanel({ invoice }: { invoice: Invoice }) {
  const einvoice = invoice.extraction?.einvoice;
  const comparisons = Object.entries(einvoice?.comparison_results || {});
  const comparisonStatus = einvoice?.comparison_status || "not_checked";
  const comparisonLabel = comparisonStatus === "match" ? "QR/OCR match" : comparisonStatus === "mismatch" ? "QR/OCR mismatch" : comparisonStatus === "not_comparable" ? "Not comparable" : "Not checked";
  const comparisonClass = comparisonStatus === "match" ? "status-approved" : comparisonStatus === "mismatch" ? "status-rejected" : "status-on_hold";
  return <section className="panel"><div className="panel-heading"><div><span className="eyebrow">E-invoice evidence</span><h2>QR comparison</h2></div><span className={`status-pill ${einvoice?.qr_detected ? "status-approved" : "status-on_hold"}`}><i />{einvoice?.qr_detected ? "QR detected" : "No QR detected"}</span></div><div className="financial-strip"><div><span>IRN</span><strong className="mono-cell">{einvoice?.irn || "—"}</strong></div><div><span>Acknowledgement</span><strong className="mono-cell">{einvoice?.ack_number || "—"}</strong></div><div><span>Comparison</span><strong className={`status-pill ${comparisonClass}`}><i />{comparisonLabel}</strong></div><div><span>Source</span><strong>OpenCV local detector</strong></div></div>{comparisons.length > 0 && <div className="validation-list">{comparisons.map(([field, result]) => <div className={`validation-row ${result.status === "match" ? "passed" : result.status === "mismatch" ? "failed" : ""}`} key={field}><span>{result.status === "match" ? <Check size={14} /> : result.status === "mismatch" ? <AlertTriangle size={14} /> : <BadgeCheck size={14} />}</span><div><strong>{field.replaceAll("_", " ")}</strong><small>OCR: {result.ocr_value || "not extracted"} · QR: {result.qr_value || "not available"}{result.difference ? ` · Difference: ${result.difference}` : ""}</small></div><em>{result.status.replaceAll("_", " ")}</em></div>)}</div>}{einvoice?.qr_detected && comparisons.length === 0 && <div className="inline-empty">QR payload was detected, but it did not contain fields that could be compared with OCR.</div>}</section>;
}

function InvoiceQAPanel({ invoice }: { invoice: Invoice }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<InvoiceQuestionResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim()) return;
    setError("");
    setLoading(true);
    try {
      const response = await apiClient.post<InvoiceQuestionResponse>(`/invoices/${invoice.id}/qa`, { question });
      setAnswer(response.data);
    } catch { setError("Invoice AI could not answer this question."); } finally { setLoading(false); }
  };
  return <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Ask Invoice AI</span><h2>Question this invoice</h2></div><span className="muted-text">Invoice JSON + OCR only</span></div><form className="qa-form" onSubmit={submit}><input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="What is the payment due date?" /><button className="primary-button" disabled={loading}>{loading ? <Loader2 size={14} className="spin" /> : "Ask"}</button></form>{error && <div className="qa-error">{error}</div>}{answer && <div className="qa-answer"><div className="qa-answer-heading"><strong>{answer.answer}</strong><span className={`status-pill ${answer.provider.startsWith("ollama/") ? "status-approved" : "status-on_hold"}`}><i />{answer.provider}</span></div><small>{answer.grounded ? "Grounded to invoice JSON + OCR" : "Unverified response"} · {answer.evidence.join(" · ")}</small></div>}</section>;
}

function formatRiskDetails(details: Record<string, unknown>) {
  return Object.entries(details)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => {
      const rendered = typeof value === "object" ? JSON.stringify(value) : String(value);
      return `${key.replaceAll("_", " ")}: ${rendered}`;
    })
    .join(" · ");
}

function RiskPanel({ invoice }: { invoice: Invoice }) {
  return <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Invoice risk &amp; anomalies</span><h2>Deterministic, explainable signals</h2></div><RiskBadge level={invoice.risk_level} score={invoice.risk_score} /></div>{invoice.risk_flags.length ? <div className="risk-list">{invoice.risk_flags.map((flag) => { const details = formatRiskDetails(flag.details || {}); return <div className="risk-row" key={flag.id}><ShieldAlert size={15} /><div><strong>{flag.message}</strong><small>{flag.code.replaceAll("_", " ")} · +{flag.points} points{details ? ` · ${details}` : ""}</small></div></div>; })}</div> : <div className="clear-state"><BadgeCheck size={17} /> No deterministic risk contributions were detected.</div>}</section>;
}
function WorkflowPanel({ invoice }: { invoice: Invoice }) { return <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Audit trail</span><h2>Workflow history</h2></div></div>{invoice.workflow.length ? <div className="timeline">{invoice.workflow.map((event) => <div className="timeline-row" key={event.id}><span className="timeline-dot" /><div><strong>{event.action.replaceAll("_", " ")}</strong><small>{event.from_status || "created"} → {event.to_status} · {event.actor} · {event.created_at ? formatDate(event.created_at) : "now"}</small>{event.comment && <p>{event.comment}</p>}</div></div>)}</div> : <p className="inline-empty">No workflow events yet. This invoice is ready for the first human decision.</p>}</section>; }
function CorrectionsPanel({ invoice }: { invoice: Invoice }) {
  return <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Learning loop</span><h2>Human corrections</h2></div><span className="muted-text">{invoice.corrections.length} saved</span></div>{invoice.corrections.length ? <div className="timeline corrections-list">{invoice.corrections.map((entry) => <div className="timeline-row" key={entry.id}><span className="timeline-dot" /><div><strong>{entry.field_path.replaceAll(".value", "").replaceAll("_", " ")}</strong><small>{entry.predicted ?? entry.old_value ?? "missing"} → {entry.correct ?? entry.new_value} · {entry.corrected_by}</small></div></div>)}</div> : <p className="inline-empty">Edits made during review will be retained here as prediction → correction training examples.</p>}</section>;
}

function PaymentForm({ invoice, onSaved }: { invoice: Invoice; onSaved: (invoice: Invoice) => void }) {
  const [amount, setAmount] = useState(String(invoice.outstanding_amount));
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [method, setMethod] = useState("bank_transfer");
  const [saving, setSaving] = useState(false);
  const submit = async (event: FormEvent) => { event.preventDefault(); setSaving(true); try { const response = await apiClient.post<Invoice>(`/invoices/${invoice.id}/payments`, { amount: Number(amount), payment_date: date, method, actor: "local_user" }); onSaved(response.data); } finally { setSaving(false); } };
  return <form className="payment-form panel" onSubmit={submit}><div><span className="eyebrow">Payment entry</span><h2>Record a payment</h2></div><div className="form-row"><label>Amount<input type="number" min="0.01" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} /></label><label>Date<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label><label>Method<select value={method} onChange={(event) => setMethod(event.target.value)}><option value="bank_transfer">Bank transfer</option><option value="upi">UPI</option><option value="cheque">Cheque</option><option value="cash">Cash</option></select></label><button className="primary-button" disabled={saving}>{saving ? <Loader2 size={15} className="spin" /> : <Check size={15} />} Save payment</button></div></form>;
}

export function VendorsPage() {
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState(""); const [gstin, setGstin] = useState("");
  const load = useCallback(() => { void apiClient.get<Vendor[]>("/vendors").then((response) => setVendors(response.data)); }, []);
  useEffect(() => load(), [load]);
  const submit = async (event: FormEvent) => { event.preventDefault(); await apiClient.post("/vendors", { name, gstin: gstin || null }); setName(""); setGstin(""); setShowForm(false); load(); };
  return <><PageHeader eyebrow="Vendor master" title="Vendors" description="Keep supplier identity, GST details, spend, and outstanding exposure attached to every invoice." action={<button className="primary-button" onClick={() => setShowForm(!showForm)}><Plus size={15} /> New vendor</button>} />{showForm && <form className="inline-form panel" onSubmit={submit}><label>Vendor name<input required value={name} onChange={(event) => setName(event.target.value)} placeholder="ABC Technologies Pvt Ltd" /></label><label>GSTIN<input value={gstin} onChange={(event) => setGstin(event.target.value)} placeholder="27ABCDE1234F1Z5" /></label><button className="primary-button">Create vendor</button></form>}<section className="panel table-panel">{vendors.length ? <div className="vendor-card-grid">{vendors.map((vendor) => <VendorCard key={vendor.id} vendor={vendor} />)}</div> : <EmptyState icon={Store} title="No vendors yet" body="Vendors are also created automatically when a new GSTIN appears on an invoice." />}</section></>;
}

export function PurchaseOrdersPage() {
  const [orders, setOrders] = useState<PurchaseOrder[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [showReceiptForm, setShowReceiptForm] = useState(false);
  const [number, setNumber] = useState("");
  const [vendorName, setVendorName] = useState("");
  const [description, setDescription] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [rate, setRate] = useState("0");
  const [taxTotal, setTaxTotal] = useState("0");
  const [receiptOrderId, setReceiptOrderId] = useState("");
  const [receiptItemId, setReceiptItemId] = useState("");
  const [receiptNumber, setReceiptNumber] = useState("");
  const [receiptQuantity, setReceiptQuantity] = useState("1");
  const [savingReceipt, setSavingReceipt] = useState(false);
  const load = useCallback(() => {
    void apiClient.get<PurchaseOrder[]>("/purchase-orders").then((response) => setOrders(response.data));
  }, []);
  useEffect(() => load(), [load]);
  useEffect(() => {
    const order = orders.find((item) => item.id === receiptOrderId) || orders[0];
    if (order && order.id !== receiptOrderId) setReceiptOrderId(order.id);
    if (order && !order.items.some((item) => item.id === receiptItemId)) setReceiptItemId(order.items[0]?.id || "");
  }, [orders, receiptItemId, receiptOrderId]);
  const selectedReceiptOrder = orders.find((item) => item.id === receiptOrderId);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await apiClient.post("/purchase-orders", {
      number,
      vendor_name: vendorName || null,
      tax_total: Number(taxTotal),
      items: [{ description, quantity: Number(quantity), unit_price: Number(rate), line_total: Number(quantity) * Number(rate) }],
    });
    setNumber(""); setVendorName(""); setDescription(""); setQuantity("1"); setRate("0"); setTaxTotal("0"); setShowForm(false); load();
  };
  const submitReceipt = async (event: FormEvent) => {
    event.preventDefault();
    if (!receiptOrderId || !receiptItemId) return;
    setSavingReceipt(true);
    try {
      await apiClient.post(`/purchase-orders/${receiptOrderId}/receipts`, {
        purchase_order_id: receiptOrderId,
        receipt_number: receiptNumber,
        receipt_date: new Date().toISOString().slice(0, 10),
        items: [{ purchase_order_item_id: receiptItemId, quantity_received: Number(receiptQuantity) }],
      });
      setReceiptNumber(""); setReceiptQuantity("1"); setShowReceiptForm(false); load();
    } finally { setSavingReceipt(false); }
  };
  return <>
    <PageHeader eyebrow="Procurement controls" title="Purchase orders" description="Create POs, record goods receipts, and compare vendor, tax, quantity, rate, and total through two-way or three-way matching." action={<><button className="secondary-button" onClick={() => setShowReceiptForm(!showReceiptForm)}><ClipboardCheck size={15} /> Record receipt</button><button className="primary-button" onClick={() => setShowForm(!showForm)}><Plus size={15} /> New PO</button></>} />
    {showForm && <form className="inline-form panel po-form" onSubmit={submit}><label>PO number<input required value={number} onChange={(event) => setNumber(event.target.value)} placeholder="PO-1024" /></label><label>Vendor name<input value={vendorName} onChange={(event) => setVendorName(event.target.value)} placeholder="ABC Technologies" /></label><label>Item description<input required value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Laptop" /></label><label>Qty<input type="number" min="0" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label><label>Rate<input type="number" min="0" value={rate} onChange={(event) => setRate(event.target.value)} /></label><label>Tax total<input type="number" min="0" step="0.01" value={taxTotal} onChange={(event) => setTaxTotal(event.target.value)} /></label><button className="primary-button">Create PO</button></form>}
    {showReceiptForm && <form className="inline-form panel po-form" onSubmit={submitReceipt}><label>Purchase order<select required value={receiptOrderId} onChange={(event) => { setReceiptOrderId(event.target.value); setReceiptItemId(orders.find((order) => order.id === event.target.value)?.items[0]?.id || ""); }}><option value="">Select PO</option>{orders.map((order) => <option key={order.id} value={order.id}>{order.number} · {order.vendor?.name || "Unlinked vendor"}</option>)}</select></label><label>PO item<select required value={receiptItemId} onChange={(event) => setReceiptItemId(event.target.value)}>{selectedReceiptOrder?.items.map((item) => <option key={item.id} value={item.id}>{item.description} · {item.quantity} units</option>)}</select></label><label>Receipt number<input required value={receiptNumber} onChange={(event) => setReceiptNumber(event.target.value)} placeholder="GR-1024" /></label><label>Received qty<input type="number" min="0" step="0.01" value={receiptQuantity} onChange={(event) => setReceiptQuantity(event.target.value)} /></label><button className="primary-button" disabled={savingReceipt}>{savingReceipt ? <Loader2 size={15} className="spin" /> : <Check size={15} />} Save receipt</button></form>}
    <section className="panel table-panel">{orders.length ? <table className="invoice-table"><thead><tr><th>PO</th><th>Vendor</th><th>Items</th><th>Receipts</th><th>Total</th><th>Status</th></tr></thead><tbody>{orders.map((order) => <tr key={order.id}><td><strong>{order.number}</strong><small>{formatDate(order.order_date)}</small></td><td>{order.vendor?.name || "Unlinked vendor"}</td><td>{order.items.length}</td><td>{order.receipts?.length || 0}</td><td className="money-cell">{formatINR(order.total)}</td><td><span className="status-pill status-approved"><i />{order.status}</span></td></tr>)}</tbody></table> : <EmptyState icon={PackageCheck} title="No purchase orders" body="Create a PO to turn invoice matching into a real control." />}</section>
  </>;
}

export function PaymentsPage() {
  const [rows, setRows] = useState<PaymentDue[]>([]); const [overdue, setOverdue] = useState(false);
  const load = useCallback(() => { void apiClient.get<PaymentDue[]>("/payments", { params: { overdue } }).then((response) => setRows(response.data)); }, [overdue]); useEffect(() => load(), [load]);
  return <><PageHeader eyebrow="Cash operations" title="Payment queue" description="See what is outstanding, what is overdue, and open the invoice record to post a partial or final payment." action={<button className={`secondary-button ${overdue ? "selected" : ""}`} onClick={() => setOverdue(!overdue)}><CalendarClock size={15} /> {overdue ? "Showing overdue" : "Show overdue"}</button>} /><section className="panel table-panel">{rows.length ? <table className="invoice-table"><thead><tr><th>Invoice</th><th>Vendor</th><th>Due</th><th>Outstanding</th><th>Status</th><th /></tr></thead><tbody>{rows.map((row) => <tr key={row.invoice_id}><td><Link className="invoice-link" to={`/invoices/${row.invoice_id}`}>{row.invoice_number || "Unnumbered"}</Link></td><td>{row.vendor || "Unknown"}</td><td className={row.overdue ? "overdue-text" : ""}>{formatDate(row.due_date)}</td><td className="money-cell">{formatINR(row.outstanding_amount)}</td><td><StatusPill status={row.status} /></td><td><Link className="row-arrow" to={`/invoices/${row.invoice_id}`}><ChevronRight size={16} /></Link></td></tr>)}</tbody></table> : <EmptyState icon={WalletCards} title="No outstanding payments" body="Approved invoices will appear here when they enter the payment queue." />}</section></>;
}

export function AnalyticsPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null); const [vendors, setVendors] = useState<Vendor[]>([]);
  useEffect(() => { void Promise.all([apiClient.get<DashboardSummary>("/dashboard/summary"), apiClient.get<Vendor[]>("/vendors")]).then(([summaryResponse, vendorResponse]) => { setSummary(summaryResponse.data); setVendors(vendorResponse.data); }); }, []);
  const maxSpend = Math.max(...vendors.map((vendor) => vendor.total_spend), 1);
  return <>
    <PageHeader eyebrow="Reporting" title="Analytics" description="A compact operating view of payable exposure, aging, vendor concentration, and control quality." action={<button className="secondary-button" onClick={() => void downloadFile("/invoices/export?format=csv", "invoices.csv")}><FileDown size={15} /> Export CSV</button>} />
    {summary ? <>
      <div className="metric-grid"><MetricCard label="Total payable" value={formatINR(summary.outstanding_total)} detail="Open invoice exposure" icon={CircleDollarSign} tone="green" /><MetricCard label="Overdue" value={formatINR(summary.overdue_total)} detail="Needs immediate attention" icon={AlertTriangle} tone="red" /><MetricCard label="Tax captured" value={formatINR(summary.total_tax)} detail="Extracted tax rows" icon={ReceiptIndianRupee} tone="violet" /><MetricCard label="High-risk invoices" value={String(summary.high_risk_count)} detail="Explainable risk signals" icon={ShieldAlert} tone="amber" /></div>
      <div className="analytics-grid"><section className="panel"><div className="panel-heading"><div><span className="eyebrow">Exposure</span><h2>AP aging</h2></div></div><AgingBars buckets={summary.aging} /></section><section className="panel"><div className="panel-heading"><div><span className="eyebrow">Concentration</span><h2>Vendor spend</h2></div></div><div className="vendor-bars">{vendors.slice(0, 7).map((vendor) => <div className="vendor-bar" key={vendor.id}><div><span>{vendor.name}</span><strong>{formatINR(vendor.total_spend)}</strong></div><div className="bar-track"><i style={{ width: `${Math.max(3, vendor.total_spend / maxSpend * 100)}%` }} /></div></div>)}</div></section></div>
    </> : <LoadingRow />}
  </>;
}

export function NotFound() { return <div className="empty-state page-empty"><AlertTriangle size={28} /><h3>Page not found</h3><p>That AP workspace route does not exist.</p><Link className="primary-button" to="/dashboard">Back to dashboard</Link></div>; }
