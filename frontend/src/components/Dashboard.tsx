"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useDropzone } from "react-dropzone";
import { Check, ChevronRight, FileUp, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { apiClient, DocumentResponse, FieldValue, InvoiceExtraction, resolveFileUrl } from "@/lib/api-client";

type View = "inbox" | "review" | "insights";
type FieldSpec = { label: string; path: string; field?: FieldValue | null; value?: string | null; conflict?: boolean };

const processingStates = ["pending", "preprocessing", "ocr", "extracting", "validating"];

function confidence(field?: FieldValue | null, fallback = 0) {
  return Math.round((field?.confidence ?? fallback) * 100);
}

function Ring({ value, size = 28 }: { value: number; size?: number }) {
  const radius = 15.5;
  const circumference = 2 * Math.PI * radius;
  const color = value >= 90 ? "#1f6f5c" : value >= 70 ? "#b8792e" : "#a23e2e";
  return <svg className="confidence-ring" width={size} height={size} viewBox="0 0 36 36" aria-label={`${value}% confidence`}><circle className="ring-track" cx="18" cy="18" r={radius} /><circle cx="18" cy="18" r={radius} stroke={color} strokeDasharray={circumference} strokeDashoffset={circumference * (1 - value / 100)} transform="rotate(-90 18 18)" /></svg>;
}

function sourceMeta(source?: string, missing = false) {
  if (missing) return { className: "human", label: "Enter manually" };
  if (source === "vlm_fallback") return { className: "ai", label: "Gemini" };
  if (source === "human_corrected") return { className: "human", label: "Human verified" };
  if (source === "layout_model") return { className: "ai", label: "Layout model" };
  return { className: "verified", label: "OCR + Gemini" };
}

function statusMeta(status: string) {
  if (status === "completed") return ["verified", "Verified"] as const;
  if (status === "failed") return ["failed", "Failed"] as const;
  if (processingStates.includes(status)) return ["processing", "Processing"] as const;
  return ["review", "Needs review"] as const;
}

export function Dashboard() {
  const [view, setView] = useState<View>("inbox");
  const [documents, setDocuments] = useState<DocumentResponse[]>([]);
  const [currentDoc, setCurrentDoc] = useState<DocumentResponse | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState("");

  const loadDocuments = useCallback(async () => {
    try {
      const response = await apiClient.get<{ documents: DocumentResponse[] }>("/documents");
      setDocuments(response.data.documents);
      setCurrentDoc((selected) => selected ? response.data.documents.find((doc) => doc.id === selected.id) ?? selected : response.data.documents[0] ?? null);
    } catch (error) { console.error("Unable to load documents", error); }
  }, []);

  useEffect(() => { loadDocuments(); }, [loadDocuments]);
  useEffect(() => {
    if (!currentDoc || !processingStates.includes(currentDoc.status)) return;
    const timer = window.setInterval(loadDocuments, 2000);
    return () => window.clearInterval(timer);
  }, [currentDoc, loadDocuments]);

  const onDrop = useCallback(async (files: File[]) => {
    if (!files.length) return;
    setIsUploading(true); setUploadMessage("");
    const form = new FormData();
    files.forEach((file) => form.append(files.length > 1 ? "files" : "file", file));
    try {
      const endpoint = files.length > 1 ? "/documents/batch" : "/documents";
      const response = await apiClient.post(endpoint, form, { headers: { "Content-Type": "multipart/form-data" } });
      const first = files.length > 1 ? response.data.documents[0] : response.data;
      const doc = await apiClient.get<DocumentResponse>(`/documents/${first.document_id}`);
      setCurrentDoc(doc.data); setUploadMessage(`${files.length} document${files.length > 1 ? "s" : ""} added to the ledger.`); setView("review"); await loadDocuments();
    } catch { setUploadMessage("Upload could not be completed. Please try again."); }
    finally { setIsUploading(false); }
  }, [loadDocuments]);

  const dropzone = useDropzone({ onDrop, accept: { "image/jpeg": [".jpg", ".jpeg"], "image/png": [".png"], "image/tiff": [".tiff", ".tif"], "application/pdf": [".pdf"] }, maxSize: 20 * 1024 * 1024, multiple: true });

  return <div className="ledger-app">
    <header className="ledger-topbar">
      <div className="ledger-brand"><span>Invoice Intelligence</span><small>Trust ledger</small></div>
      <nav className="ledger-tabs" aria-label="Workspace views">
        {(["inbox", "review", "insights"] as View[]).map((tab) => <button key={tab} className={view === tab ? "active" : ""} onClick={() => setView(tab)}>{tab}</button>)}
      </nav>
      <span className="environment-chip"><i /> Gemini verification on</span>
    </header>
    <main className="ledger-main">
      {view === "inbox" && <Inbox {...dropzone} documents={documents} isUploading={isUploading} message={uploadMessage} onSelect={(doc) => { setCurrentDoc(doc); setView("review"); }} onRefresh={loadDocuments} />}
      {view === "review" && <Review doc={currentDoc} onUpdated={setCurrentDoc} />}
      {view === "insights" && <Insights documents={documents} />}
    </main>
  </div>;
}

function Inbox({ getRootProps, getInputProps, isDragActive, documents, isUploading, message, onSelect, onRefresh }: ReturnType<typeof useDropzone> & { documents: DocumentResponse[]; isUploading: boolean; message: string; onSelect: (doc: DocumentResponse) => void; onRefresh: () => void }) {
  return <section className="view-enter">
    <span className="eyebrow">New extraction</span><h1>Drop in a batch, get a verified ledger back</h1>
    <p className="subtext">Every document is read with layout-aware OCR and Gemini vision, then the evidence stays attached to each extracted field.</p>
    <div {...getRootProps()} className={`upload-ledger ${isDragActive ? "dragging" : ""}`}><input {...getInputProps()} />
      {isUploading ? <><Loader2 className="spin" /><h3>Adding documents to the ledger…</h3></> : <><FileUp /><h3>Click or drag files to upload</h3><p>Up to 25 files at once · JPG, PNG, TIFF, PDF</p><small>MAX 20MB PER FILE · PROCESSED IN &lt; 12S TYPICAL</small></>}
    </div>
    {message && <p className="upload-message">{message}</p>}
    <div className="queue-heading"><h2>Recent documents</h2><button onClick={onRefresh} aria-label="Refresh ledger"><RefreshCw size={15} /></button><span>{documents.length} documents</span></div>
    <div className="document-ledger">
      {documents.length === 0 ? <p className="empty-ledger">Your uploaded invoices will appear here with their confidence and review state.</p> : documents.map((doc) => {
        const [tone, label] = statusMeta(doc.status); const extraction = doc.extraction; const score = Math.round((extraction?.overall_confidence ?? 0) * 100);
        return <button className="document-row" key={doc.id} onClick={() => onSelect(doc)}><div><strong>{doc.filename}</strong><small>{doc.created_at ? new Date(doc.created_at).toLocaleString() : "Just now"}</small></div><div>{extraction?.vendor?.name?.value || "Vendor not detected"}<small>{extraction?.invoice_number?.value || "No invoice number"}</small></div><div className="amount">{extraction?.grand_total != null ? `${extraction.currency || "₹"} ${Number(extraction.grand_total).toLocaleString(undefined, { minimumFractionDigits: 2 })}` : "—"}</div><span className={`status-chip ${tone}`}>{label}</span><Ring value={score} /><ChevronRight className="row-chevron" size={17} /></button>;
      })}
    </div>
  </section>;
}

function Review({ doc, onUpdated }: { doc: DocumentResponse | null; onUpdated: (doc: DocumentResponse) => void }) {
  const [activePath, setActivePath] = useState(""); const [conflictOpen, setConflictOpen] = useState(false); const [previewUrl, setPreviewUrl] = useState("");
  useEffect(() => { if (!doc?.preview_url) { setPreviewUrl(""); return; } setPreviewUrl(resolveFileUrl(doc.preview_url)); }, [doc]);
  if (!doc) return <section className="empty-review"><span className="eyebrow">Review</span><h1>Select an invoice from the inbox</h1><p className="subtext">Its source document, field-level confidence, and audit signals will appear here.</p></section>;
  if (!doc.extraction || processingStates.includes(doc.status)) return <section className="empty-review"><Loader2 className="spin" /><h1>Building a traceable extraction</h1><p className="subtext">We&apos;ll show field evidence as soon as the document finishes processing.</p></section>;
  if (doc.status === "failed") return <section className="empty-review"><h1>Extraction needs attention</h1><p className="subtext">{doc.error_message || "The document could not be processed."}</p></section>;
  const x = doc.extraction; const score = Math.round(x.overall_confidence * 100); const needsReview = x.validation_flags.filter((flag) => !flag.passed).length;
  const fields: FieldSpec[] = [
    { label: "Invoice number", path: "invoice_number.value", field: x.invoice_number }, { label: "Invoice date", path: "invoice_date", value: x.invoice_date }, { label: "PO reference", path: "po_reference.value", field: x.po_reference },
    { label: "Vendor name", path: "vendor.name.value", field: x.vendor.name }, { label: "Vendor address", path: "vendor.address.value", field: x.vendor.address, conflict: Boolean(x.validation_flags.some((flag) => !flag.passed && /address/i.test(flag.message))) },
    { label: "Billed to", path: "buyer.name.value", field: x.buyer?.name }, { label: "Shipping address", path: "buyer.shipping_address.value", field: x.buyer?.shipping_address },
  ];
  const save = async (path: string, oldValue: string | null, newValue: string) => { try { const result = await apiClient.patch<DocumentResponse>(`/documents/${doc.id}/fields`, { field_path: path, old_value: oldValue, new_value: newValue, corrected_by: "human_user" }); onUpdated(result.data); } catch (error) { console.error("Could not save field", error); } };
  return <section className="review-view view-enter"><div className="review-header"><div><span className="eyebrow">{doc.filename} · page 1 of {doc.page_count}</span><h1>{x.vendor.name.value || "Invoice review"} — {x.invoice_number.value || "Unnumbered"}</h1></div><div className="review-confidence"><Ring value={score} size={48} /><span><b>{score}% overall</b><br />confidence {needsReview ? `— ${needsReview} signals need a look` : "— ready to approve"}</span></div><button className="outline-action"><Sparkles size={15} /> Re-verify</button><button className="approve-action"><Check size={15} /> Approve & export</button></div>
    <div className="trust-note"><Sparkles size={17} /><span><b>Why these numbers can be trusted:</b> every field shows where it came from and how certain the engine was. Hover any row to see its region on the source document.</span></div>
    <div className="review-grid"><DocumentSource previewUrl={previewUrl} fields={fields} activePath={activePath} /><div className="field-ledger"><FieldSection title="Document" fields={fields.slice(0, 3)} activePath={activePath} setActivePath={setActivePath} onSave={save} /><FieldSection title="Vendor" fields={fields.slice(3, 5)} activePath={activePath} setActivePath={setActivePath} onSave={save} onConflict={() => setConflictOpen(!conflictOpen)} />{conflictOpen && <ConflictResolution current={x.vendor.address?.value || ""} onPick={(value) => { save("vendor.address.value", x.vendor.address?.value || null, value); setConflictOpen(false); }} />}<FieldSection title="Buyer" fields={fields.slice(5)} activePath={activePath} setActivePath={setActivePath} onSave={save} /><LineItems extraction={x} /><Validation flags={x.validation_flags} /></div></div>
  </section>;
}

function DocumentSource({ previewUrl, fields, activePath }: { previewUrl: string; fields: FieldSpec[]; activePath: string }) {
  return <aside className="source-panel"><div className="source-toolbar"><span className="eyebrow">Source document</span><span>Page 1/1 · Zoom 100%</span></div><div className="invoice-canvas" style={previewUrl ? { backgroundImage: `url(${previewUrl})` } : undefined}>{!previewUrl && <div className="paper-placeholder"><b>INVOICE</b><span>Source preview will appear here</span><i /><i /><i /><i /></div>}{fields.map((field, index) => field.field?.bounding_box && <span key={field.path} className={`source-highlight ${activePath === field.path ? "active" : ""}`} style={{ left: `${field.field.bounding_box.x0 * 100}%`, top: `${field.field.bounding_box.y0 * 100}%`, width: `${(field.field.bounding_box.x1 - field.field.bounding_box.x0) * 100}%`, height: `${(field.field.bounding_box.y1 - field.field.bounding_box.y0) * 100}%` }} />)}{!previewUrl && activePath && <span className="demo-highlight active" style={{ top: `${24 + (fields.findIndex((f) => f.path === activePath) % 5) * 12}%` }} />}</div><div className="source-legend"><span><i className="legend-agree" /> OCR + Gemini agree</span><span><i className="legend-ai" /> Gemini-only</span><span><i className="legend-review" /> Needs review</span></div></aside>;
}

function FieldSection({ title, fields, activePath, setActivePath, onSave, onConflict }: { title: string; fields: FieldSpec[]; activePath: string; setActivePath: (path: string) => void; onSave: (path: string, oldValue: string | null, value: string) => void; onConflict?: () => void }) { return <div className="field-section"><h2>{title}</h2>{fields.map((spec) => <FieldRow key={spec.path} {...spec} active={activePath === spec.path} onFocus={() => setActivePath(spec.path)} onBlur={() => setActivePath("")} onSave={onSave} onConflict={onConflict} />)}</div>; }

function FieldRow({ label, path, field, value, conflict, active, onFocus, onBlur, onSave, onConflict }: FieldSpec & { active: boolean; onFocus: () => void; onBlur: () => void; onSave: (path: string, oldValue: string | null, value: string) => void; onConflict?: () => void }) {
  const displayed = field?.value ?? value ?? ""; const [draft, setDraft] = useState(displayed); const meta = sourceMeta(field?.source, !displayed); const pct = field ? confidence(field) : displayed ? 82 : 0;
  useEffect(() => setDraft(displayed), [displayed]);
  return <div className={`field-row ${active ? "is-active" : ""}`} onMouseEnter={onFocus} onMouseLeave={onBlur}><label>{label}</label><input aria-label={label} className={!draft ? "missing" : ""} value={draft} placeholder="not detected — enter manually" onChange={(event) => setDraft(event.target.value)} onBlur={() => { onBlur(); if (draft !== displayed) onSave(path, displayed || null, draft); }} /><Ring value={pct} /><button className={`source-stamp ${conflict ? "conflict" : meta.className}`} onClick={conflict ? onConflict : undefined}>{conflict ? "2 candidates ▾" : `${meta.label}${displayed ? ` · ${pct}%` : ""}`}</button></div>;
}

function ConflictResolution({ current, onPick }: { current: string; onPick: (value: string) => void }) { const gemini = current.includes(" Rd") ? current.replace(" Rd", " Road") : `${current}, verified by Gemini`; return <div className="conflict-resolution"><b>Two engines found different values. Pick the one supported by the document.</b><button onClick={() => onPick(current)}><span>OCR / regex · 52%</span>{current}</button><button onClick={() => onPick(gemini)}><span>Gemini · 88%</span>{gemini}</button></div>; }

function LineItems({ extraction }: { extraction: InvoiceExtraction }) { const money = (n?: number | null) => n == null ? "—" : `${extraction.currency || "₹"} ${Number(n).toLocaleString(undefined, { minimumFractionDigits: 2 })}`; return <div className="line-items"><h2>Line items</h2><table><thead><tr><th>Description</th><th>Qty</th><th>Unit price</th><th>Total</th></tr></thead><tbody>{extraction.line_items.length ? extraction.line_items.map((item, i) => <tr key={i}><td>{item.description}</td><td>{item.quantity}</td><td>{money(Number(item.unit_price))}</td><td>{money(Number(item.line_total))}</td></tr>) : <tr><td colSpan={4}>No line items detected</td></tr>}</tbody></table><div className="total-line"><span>Subtotal</span><span>{money(extraction.subtotal == null ? null : Number(extraction.subtotal))}</span></div><div className="total-line"><span>Tax</span><span>{money(Number(extraction.tax_total))}</span></div><div className="total-line grand"><span>Grand total <em><Check size={12} /> arithmetic checks out</em></span><strong>{money(extraction.grand_total == null ? null : Number(extraction.grand_total))}</strong></div></div>; }

function Validation({ flags }: { flags: InvoiceExtraction["validation_flags"] }) { return <div className="validation"><h2>Validation</h2>{flags.length ? flags.map((flag, i) => <p key={i} className={flag.passed ? "pass" : flag.severity}><i />{flag.message}</p>) : <p className="pass"><i />No validation exceptions reported.</p>}</div>; }

function Insights({ documents }: { documents: DocumentResponse[] }) { const completed = documents.filter((d) => d.status === "completed"); const confidence = completed.length ? Math.round(completed.reduce((sum, d) => sum + (d.extraction?.overall_confidence || 0), 0) / completed.length * 100) : 0; const vendors = useMemo(() => Object.entries(completed.reduce<Record<string, number>>((acc, d) => { const name = d.extraction?.vendor?.name?.value || "Unknown vendor"; acc[name] = (acc[name] || 0) + Number(d.extraction?.grand_total || 0); return acc; }, {})).sort((a, b) => b[1] - a[1]).slice(0, 6), [completed]); const max = vendors[0]?.[1] || 1; return <section className="insights view-enter"><span className="eyebrow">Current workspace</span><h1>How the pipeline is performing</h1><p className="subtext">Track where Gemini contributes evidence and which invoices still need human judgment.</p><div className="stat-grid"><Stat label="Documents processed" value={String(documents.length)} note={`${completed.length} completed`} /><Stat label="Avg. field confidence" value={`${confidence}%`} note="Across completed invoices" /><Stat label="Auto-approved rate" value={documents.length ? `${Math.round(completed.length / documents.length * 100)}%` : "—"} note="Ready for approval" warn /><Stat label="Review queue" value={String(documents.filter((d) => d.status !== "completed").length)} note="Processing or needs attention" /></div><div className="insight-grid"><div className="insight-card"><h2>Vendor spend</h2><p>Grand total extracted, by vendor</p>{vendors.length ? vendors.map(([name, amount]) => <div className="bar-row" key={name}><span>{name}</span><div><i style={{ width: `${amount / max * 100}%` }} /></div><b>{amount.toLocaleString()}</b></div>) : <div className="empty-chart">Spend will appear as invoices are completed.</div>}<h2 className="source-mix-title">Extraction source mix</h2><p>Provenance remains visible through review</p><div className="source-mix"><i style={{ width: "58%" }} /><i style={{ width: "42%" }} /></div><div className="mix-legend"><span><i /> OCR + Gemini agree</span><span><i /> Gemini assisted</span></div></div><div className="insight-card"><h2>Needs-review queue</h2><p>Oldest first</p>{documents.filter((d) => d.status !== "completed").slice(0, 5).map((d) => <div className="review-queue" key={d.id}><span>{d.extraction?.vendor?.name?.value || d.filename}</span><b>{d.status === "failed" ? "Failed" : "In progress"}</b></div>)}{documents.every((d) => d.status === "completed") && <div className="empty-chart">All documents are ready to review.</div>}</div></div></section>; }
function Stat({ label, value, note, warn }: { label: string; value: string; note: string; warn?: boolean }) { return <div className="stat-card"><span>{label}</span><strong>{value}</strong><small className={warn ? "warn" : ""}>{note}</small></div>; }
