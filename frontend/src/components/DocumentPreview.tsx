"use client";

import { useCallback, useEffect, useState } from "react";
import { Edit2, AlertCircle, Save, Download, FileImage, Loader2, History, ShieldAlert, ChevronLeft, ChevronRight } from "lucide-react";

import { apiClient, AuditEntry, DocumentResponse, FieldValue, resolveFileUrl } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { 
  Table, 
  TableBody, 
  TableCell, 
  TableHead, 
  TableHeader, 
  TableRow 
} from "@/components/ui/table";

interface DocumentPreviewProps {
  doc: DocumentResponse;
  onFieldUpdated: (updatedDoc: DocumentResponse) => void;
}

export function DocumentPreview({ doc, onFieldUpdated }: DocumentPreviewProps) {
  const [editingField, setEditingField] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([]);
  const [previewUrl, setPreviewUrl] = useState("");
  const [originalUrl, setOriginalUrl] = useState("");
  const [previewPage, setPreviewPage] = useState(0);

  const extraction = doc.extraction;
  const isProcessing = ["pending", "preprocessing", "ocr", "extracting", "validating"].includes(doc.status);

  const loadAudit = useCallback(async () => {
    try {
      const response = await apiClient.get<AuditEntry[]>(`/documents/${doc.id}/audit`);
      setAuditEntries(response.data);
    } catch (error) {
      console.error("Failed to load audit history", error);
    }
  }, [doc.id]);

  useEffect(() => {
    let cancelled = false;
    apiClient.get<AuditEntry[]>(`/documents/${doc.id}/audit`).then((response) => {
      if (!cancelled) setAuditEntries(response.data);
    }).catch((error) => console.error("Failed to load audit history", error));
    return () => { cancelled = true; };
  }, [doc.id]);

  useEffect(() => {
    let originalObjectUrl = "";
    let previewObjectUrl = "";
    const loadPreview = async () => {
      const resolved = resolveFileUrl(doc.file_url);
      if (!resolved) return;
      if (doc.file_url?.startsWith("http")) {
        setOriginalUrl(resolved);
      } else {
        const apiPath = doc.file_url?.replace(/^\/api\/v1/, "") || "";
        const response = await apiClient.get<Blob>(apiPath, { responseType: "blob" });
        originalObjectUrl = URL.createObjectURL(response.data);
        setOriginalUrl(originalObjectUrl);
      }
      const previewPath = doc.preview_url?.replace(/^\/api\/v1/, "") || `/documents/${doc.id}/preview`;
      const previewResponse = await apiClient.get<Blob>(previewPath, { params: { page: previewPage + 1 }, responseType: "blob" });
      previewObjectUrl = URL.createObjectURL(previewResponse.data);
      setPreviewUrl(previewObjectUrl);
    };
    loadPreview().catch((error) => console.error("Failed to load document preview", error));
    return () => {
      if (originalObjectUrl) URL.revokeObjectURL(originalObjectUrl);
      if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
    };
  }, [doc.file_url, doc.id, doc.preview_url, previewPage]);

  if (isProcessing) {
    return (
      <Card className="border-white/10 bg-white/5 backdrop-blur-xl min-h-[500px] flex flex-col items-center justify-center">
        <Loader2 className="w-12 h-12 text-primary animate-spin mb-4" />
        <h3 className="text-xl font-medium">Processing Document</h3>
        <p className="text-muted-foreground mt-2 text-center max-w-sm">
          Currently running through the OCR and extraction pipeline. 
          This usually takes 5-10 seconds depending on the complexity of the invoice.
        </p>
        <Badge variant="secondary" className="mt-6 font-mono">{doc.status}</Badge>
      </Card>
    );
  }

  if (doc.status === "failed" || !extraction) {
    return (
      <Card className="border-red-500/20 bg-red-500/5 backdrop-blur-xl">
        <CardContent className="p-12 text-center flex flex-col items-center">
          <AlertCircle className="w-12 h-12 text-red-500 mb-4" />
          <h3 className="text-xl font-medium text-red-500">Extraction Failed</h3>
          <p className="text-red-400 mt-2">{doc.error_message || "An unknown error occurred during processing."}</p>
        </CardContent>
      </Card>
    );
  }

  const handleSaveEdit = async (fieldPath: string, oldValue: string | null) => {
    setIsSaving(true);
    try {
      const res = await apiClient.patch<DocumentResponse>(`/documents/${doc.id}/fields`, {
        field_path: fieldPath,
        old_value: oldValue,
        new_value: editValue,
        corrected_by: "human_user"
      });
      
      onFieldUpdated(res.data);
      await loadAudit();
      setEditingField(null);
    } catch (error) {
      console.error("Failed to update field", error);
    } finally {
      setIsSaving(false);
    }
  };

  const startEditing = (fieldPath: string, currentValue: string | null) => {
    setEditingField(fieldPath);
    setEditValue(currentValue || "");
  };

  const renderConfidenceBadge = (confidence: number) => {
    if (confidence >= 0.9) return <Badge variant="default" className="bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20 text-[10px] px-1 py-0 h-4 ml-2">{(confidence * 100).toFixed(0)}%</Badge>;
    if (confidence >= 0.6) return <Badge variant="secondary" className="bg-amber-500/10 text-amber-500 hover:bg-amber-500/20 text-[10px] px-1 py-0 h-4 ml-2">{(confidence * 100).toFixed(0)}%</Badge>;
    return <Badge variant="destructive" className="bg-red-500/10 text-red-500 hover:bg-red-500/20 text-[10px] px-1 py-0 h-4 ml-2">{(confidence * 100).toFixed(0)}%</Badge>;
  };

  const renderEditableField = (label: string, fieldPath: string, field: FieldValue | null | undefined, formatter?: (val: string) => string) => {
    const isEditing = editingField === fieldPath;
    const value = field?.value;
    const displayValue = value ? (formatter ? formatter(value) : value) : "Not found";
    const confidence = field?.confidence || 0;
    const isLowConfidence = confidence < 0.6;
    
    return (
      <div className="flex flex-col space-y-1.5 p-3 rounded-lg border border-transparent hover:border-white/10 hover:bg-white/5 transition-colors group">
        <Label className="text-xs text-muted-foreground flex items-center">
          {label}
          {field && renderConfidenceBadge(confidence)}
          {field?.source === "human_corrected" && (
            <Badge variant="outline" className="text-[10px] px-1 py-0 h-4 ml-2 text-primary border-primary/50">Edited</Badge>
          )}
        </Label>
        
        {isEditing ? (
          <div className="flex items-center gap-2 mt-1">
            <Input 
              value={editValue} 
              onChange={(e) => setEditValue(e.target.value)}
              className="h-8 text-sm bg-black/50"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSaveEdit(fieldPath, value || null);
                if (e.key === 'Escape') setEditingField(null);
              }}
            />
            <Button size="icon" className="h-8 w-8" onClick={() => handleSaveEdit(fieldPath, value || null)} disabled={isSaving}>
              {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            </Button>
          </div>
        ) : (
          <div className="flex items-center justify-between mt-1">
            <span className={`text-sm font-medium ${!value ? 'text-muted-foreground italic' : ''} ${isLowConfidence && value ? 'text-amber-500' : ''}`}>
              {displayValue}
            </span>
            <Button 
              variant="ghost" 
              size="icon" 
              className="h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity" 
              onClick={() => startEditing(fieldPath, value || null)}
            >
              <Edit2 className="h-3 w-3 text-muted-foreground" />
            </Button>
          </div>
        )}
      </div>
    );
  };

  const overlays = [
    { label: "Invoice #", field: extraction.invoice_number, color: "border-blue-400 bg-blue-400/15" },
    { label: "Vendor", field: extraction.vendor.name, color: "border-emerald-400 bg-emerald-400/15" },
    { label: "GSTIN", field: extraction.vendor.gstin, color: "border-amber-400 bg-amber-400/15" },
  ].filter((item) => item.field?.bounding_box?.page === previewPage);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 h-[calc(100vh-200px)] min-h-[600px]">
      
      {/* Left: Document Image Viewer */}
      <Card className="border-white/10 bg-black/40 backdrop-blur-xl overflow-hidden flex flex-col">
        <CardHeader className="p-4 border-b border-white/10 bg-white/5 flex flex-row items-center justify-between">
          <div className="flex items-center gap-2 truncate">
            <FileImage className="h-4 w-4 text-muted-foreground shrink-0" />
            <CardTitle className="text-sm font-medium truncate">{doc.filename}</CardTitle>
          </div>
          <div className="flex items-center gap-1">
            {doc.page_count > 1 && <>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setPreviewPage((page) => Math.max(0, page - 1))} disabled={previewPage === 0}><ChevronLeft className="h-4 w-4" /></Button>
              <span className="px-1 text-xs text-muted-foreground">{previewPage + 1}/{doc.page_count}</span>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setPreviewPage((page) => Math.min(doc.page_count - 1, page + 1))} disabled={previewPage >= doc.page_count - 1}><ChevronRight className="h-4 w-4" /></Button>
            </>}
            <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={() => window.open(originalUrl, '_blank')} disabled={!originalUrl} aria-label="Download original document">
              <Download className="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-0 flex-1 relative overflow-auto bg-black/50 flex items-center justify-center">
          {!previewUrl ? (
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          ) : (
            <div className="relative inline-block max-h-full max-w-full">
              {/* Browser image rendering is intentional: the URL can be an authenticated blob URL. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={previewUrl} alt="Uploaded invoice" className="block max-h-full max-w-full object-contain" />
              {overlays.map(({ label, field, color }) => {
                const box = field?.bounding_box;
                if (!box) return null;
                return (
                  <div
                    key={label}
                    title={`${label}: ${field?.value || ""}`}
                    className={`absolute border-2 ${color}`}
                    style={{ left: `${box.x0 * 100}%`, top: `${box.y0 * 100}%`, width: `${(box.x1 - box.x0) * 100}%`, height: `${(box.y1 - box.y0) * 100}%` }}
                  >
                    <span className="absolute -top-5 left-0 whitespace-nowrap rounded bg-black/80 px-1 text-[10px] text-white">{label}</span>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Right: Extracted Data Form */}
      <Card className="border-white/10 bg-white/5 backdrop-blur-xl overflow-hidden flex flex-col shadow-2xl">
        <CardHeader className="p-4 border-b border-white/10 bg-white/5">
          <div className="flex justify-between items-start">
            <div>
              <CardTitle>Extracted Data</CardTitle>
              <CardDescription>
                {extraction.extraction_source === 'vlm_fallback' ? (
                  <Badge variant="secondary" className="mt-1 bg-purple-500/20 text-purple-400 hover:bg-purple-500/30">AI Deep Extraction</Badge>
                ) : (
                  <Badge variant="secondary" className="mt-1 bg-blue-500/20 text-blue-400 hover:bg-blue-500/30">OCR + Rules Engine</Badge>
                )}
              </CardDescription>
            </div>
            <div className="text-right">
              <div className="text-2xl font-bold text-primary">
                {(extraction.overall_confidence * 100).toFixed(0)}%
              </div>
              <div className="text-xs text-muted-foreground">Confidence</div>
            </div>
          </div>
        </CardHeader>
        
        <CardContent className="p-0 flex-1 overflow-auto">
          <div className="p-4 space-y-6">
            
            {/* Vendor Details */}
            <section>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3 px-2">Vendor Information</h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 bg-black/20 rounded-xl p-2 border border-white/5">
                {renderEditableField("Vendor Name", "vendor.name.value", extraction.vendor.name)}
                {renderEditableField("GSTIN / Tax ID", "vendor.gstin.value", extraction.vendor.gstin)}
                <div className="col-span-1 md:col-span-2">
                  {renderEditableField("Address", "vendor.address.value", extraction.vendor.address)}
                </div>
              </div>
            </section>

            {/* Buyer Details */}
            <section>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3 px-2">Buyer Information</h4>
              <div className="grid grid-cols-1 gap-2 bg-black/20 rounded-xl p-2 border border-white/5">
                {renderEditableField("Buyer Name", "buyer.name.value", extraction.buyer?.name)}
                {renderEditableField("Billing Address", "buyer.billing_address.value", extraction.buyer?.billing_address)}
                {renderEditableField("Shipping Address", "buyer.shipping_address.value", extraction.buyer?.shipping_address)}
              </div>
            </section>

            {/* Invoice Details */}
            <section>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3 px-2">Invoice Details</h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 bg-black/20 rounded-xl p-2 border border-white/5">
                {renderEditableField("Invoice Number", "invoice_number.value", extraction.invoice_number)}
                {renderEditableField("Invoice Date", "invoice_date", { value: extraction.invoice_date || null, confidence: 0.8, source: "ocr_regex" })}
                {renderEditableField("Due Date", "due_date", { value: extraction.due_date || null, confidence: 0.8, source: "ocr_regex" })}
                {renderEditableField("PO / Order Reference", "po_reference.value", extraction.po_reference)}
                {renderEditableField("Payment Terms", "payment_terms", { value: extraction.payment_terms || null, confidence: 0.75, source: "ocr_regex" })}
                {renderEditableField("Currency", "currency", { value: extraction.currency || null, confidence: 0.9, source: "ocr_regex" })}
              </div>
            </section>

            {/* Line Items */}
            <section>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3 px-2">Line Items</h4>
              <div className="rounded-xl border border-white/10 overflow-hidden bg-black/20">
                <Table>
                  <TableHeader className="bg-white/5">
                    <TableRow className="border-white/10 hover:bg-transparent">
                      <TableHead>Description</TableHead>
                      <TableHead className="text-right">Qty</TableHead>
                      <TableHead className="text-right">Price</TableHead>
                      <TableHead className="text-right">Discount</TableHead>
                      <TableHead className="text-right">Total</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {extraction.line_items?.length > 0 ? (
                      extraction.line_items.map((item, idx) => (
                        <TableRow key={idx} className="border-white/10 hover:bg-white/5">
                          <TableCell className="font-medium text-xs max-w-[200px] truncate" title={item.description}>
                            {item.description}
                          </TableCell>
                          <TableCell className="text-right text-xs">{item.quantity}</TableCell>
                          <TableCell className="text-right text-xs">{item.unit_price}</TableCell>
                          <TableCell className="text-right text-xs">{item.discount}</TableCell>
                          <TableCell className="text-right text-xs">{item.line_total}</TableCell>
                        </TableRow>
                      ))
                    ) : (
                      <TableRow>
                        <TableCell colSpan={5} className="text-center text-muted-foreground py-6">
                          No line items detected
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            </section>

            {/* Tax Details */}
            <section>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-3 px-2">Tax Breakdown</h4>
              <div className="rounded-xl border border-white/10 overflow-hidden bg-black/20">
                <Table>
                  <TableHeader className="bg-white/5">
                    <TableRow className="border-white/10 hover:bg-transparent">
                      <TableHead>Type</TableHead>
                      <TableHead className="text-right">Rate</TableHead>
                      <TableHead className="text-right">Amount</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {extraction.taxes?.length ? extraction.taxes.map((tax, idx) => (
                      <TableRow key={`${tax.tax_type}-${idx}`} className="border-white/10 hover:bg-white/5">
                        <TableCell className="text-xs">{tax.tax_type}</TableCell>
                        <TableCell className="text-right text-xs">{tax.rate_percent != null ? `${tax.rate_percent}%` : "-"}</TableCell>
                        <TableCell className="text-right text-xs">{tax.amount}</TableCell>
                      </TableRow>
                    )) : (
                      <TableRow><TableCell colSpan={3} className="text-center text-muted-foreground py-6">No tax details detected</TableCell></TableRow>
                    )}
                  </TableBody>
                </Table>
              </div>
            </section>

            {/* Totals */}
            <section className="bg-black/40 rounded-xl p-4 border border-white/10 space-y-2">
              {renderEditableField("Subtotal", "subtotal", { value: extraction.subtotal?.toString() || null, confidence: extraction.overall_confidence, source: extraction.extraction_source || "ocr_regex" })}
              {renderEditableField("Discount", "discount_total", { value: extraction.discount_total?.toString() || "0", confidence: extraction.overall_confidence, source: extraction.extraction_source || "ocr_regex" })}
              {renderEditableField("Tax Total", "tax_total", { value: extraction.tax_total?.toString() || "0", confidence: extraction.overall_confidence, source: extraction.extraction_source || "ocr_regex" })}
              {renderEditableField("Shipping", "shipping_amount", { value: extraction.shipping_amount?.toString() || "0", confidence: extraction.overall_confidence, source: extraction.extraction_source || "ocr_regex" })}
              {renderEditableField("Grand Total", "grand_total", { value: extraction.grand_total?.toString() || null, confidence: extraction.overall_confidence, source: extraction.extraction_source || "ocr_regex" })}
            </section>

            <section>
              <h4 className="mb-3 flex items-center gap-2 px-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground"><ShieldAlert className="h-4 w-4" /> Validation</h4>
              <div className="space-y-2">
                {extraction.validation_flags?.map((flag) => (
                  <div key={`${flag.rule}-${flag.message}`} className={`rounded-lg border p-3 text-xs ${flag.passed ? "border-emerald-500/20 bg-emerald-500/5 text-emerald-200" : flag.severity === "error" ? "border-red-500/30 bg-red-500/10 text-red-200" : "border-amber-500/30 bg-amber-500/10 text-amber-200"}`}>
                    <span className="font-semibold">{flag.rule.replaceAll("_", " ")}</span>: {flag.message}
                  </div>
                ))}
              </div>
            </section>

            <section>
              <h4 className="mb-3 flex items-center gap-2 px-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground"><History className="h-4 w-4" /> Audit history</h4>
              <div className="space-y-2">
                {auditEntries.length === 0 ? <p className="px-2 text-xs text-muted-foreground">No human corrections yet.</p> : auditEntries.map((entry) => (
                  <div key={entry.id} className="rounded-lg border border-white/10 bg-black/20 p-3 text-xs">
                    <div className="flex justify-between gap-2"><span className="font-medium">{entry.field_path}</span><span className="text-muted-foreground">{new Date(entry.timestamp).toLocaleString()}</span></div>
                    <p className="mt-1 text-muted-foreground"><span className="line-through">{entry.old_value || "empty"}</span> → <span className="text-foreground">{entry.new_value}</span> · {entry.corrected_by}</p>
                  </div>
                ))}
              </div>
            </section>

          </div>
        </CardContent>
      </Card>
      
    </div>
  );
}
