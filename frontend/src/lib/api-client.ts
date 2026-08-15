import axios from "axios";

export const API_BASE_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

export const apiClient = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  headers: { "Content-Type": "application/json" },
});

apiClient.interceptors.request.use((config) => {
  const token = window.localStorage.getItem("invoice_access_token");
  const apiKey = window.localStorage.getItem("invoice_api_key");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  if (apiKey) config.headers["X-API-Key"] = apiKey;
  return config;
});

export type InvoiceStatus = "review_required" | "approved" | "awaiting_payment" | "paid" | "rejected" | "duplicate" | "on_hold";
export type RiskLevel = "low" | "medium" | "high";
export type MatchStatus = "not_applicable" | "pending" | "matched" | "partial" | "mismatch";

export interface BoundingBox { x0: number; y0: number; x1: number; y1: number; page: number }
export interface FieldValue { value: string | null; confidence: number; source: string; bounding_box?: BoundingBox | null }
export interface LineItem { description: string; hsn_sac?: string | null; quantity: number; unit_price: number; gst_rate?: number | null; tax_amount: number; discount: number; line_total: number; confidence: number }
export interface TaxDetails { tax_type: string; rate_percent?: number | null; amount: number }
export interface QRComparisonResult { status: "match" | "mismatch" | "not_comparable"; ocr_value?: string | null; qr_value?: string | null; difference?: string | null; message: string }
export interface EInvoiceDetails { qr_detected: boolean; qr_payload?: string | null; irn?: string | null; ack_number?: string | null; qr_fields: Record<string, string>; comparison_status: "match" | "mismatch" | "not_comparable" | "not_checked"; comparison_results: Record<string, QRComparisonResult> }
export interface StandardInvoiceHeader { invoice_number?: string | null; invoice_date?: string | null; due_date?: string | null; po_number?: string | null; currency: string; place_of_supply?: string | null }
export interface StandardParty { name?: string | null; address?: string | null; gstin?: string | null; pan?: string | null; email?: string | null; phone?: string | null }
export interface StandardInvoiceItem { description?: string | null; hsn?: string | null; hsn_sac?: string | null; quantity?: number | null; rate?: number | null; unit_price?: number | null; gst_rate?: number | null; tax_amount?: number | null; amount?: number | null; discount?: number | null; line_total?: number | null }
export interface StandardTaxSummary { cgst: number; sgst: number; igst: number; cess: number; other: number }
export interface StandardTotals { subtotal?: number | null; discount: number; taxable_amount?: number | null; tax: number; grand_total?: number | null }
export interface StandardPayment { terms?: string | null; due_date?: string | null; bank_name?: string | null; ifsc?: string | null; account_number?: string | null }
export interface StandardEInvoice { irn?: string | null; ack_number?: string | null; qr_detected: boolean; qr_payload?: string | null; qr_fields: Record<string, string>; comparison_status: "match" | "mismatch" | "not_comparable" | "not_checked"; comparison_results: Record<string, QRComparisonResult> }
export interface InvoiceDataStandard { document_type: string; invoice: StandardInvoiceHeader; seller: StandardParty; buyer: StandardParty; items: StandardInvoiceItem[]; taxes: StandardTaxSummary; totals: StandardTotals; payment: StandardPayment; einvoice: StandardEInvoice }
export interface ValidationFlag { rule: string; passed: boolean; message: string; severity: "info" | "warning" | "error"; details?: Record<string, unknown> }
export interface OCRToken {
  id: string; document_id: string; page: number; text: string; confidence: number;
  x: number; y: number; width: number; height: number; page_width: number; page_height: number;
  bbox: [number, number, number, number];
}
export interface InvoiceExtraction {
  invoice_number: FieldValue;
  document_type?: string;
  invoice_date?: string | null;
  due_date?: string | null;
  po_reference?: FieldValue | null;
  payment_terms?: string | null;
  vendor: { name: FieldValue; address?: FieldValue | null; gstin?: FieldValue | null; pan?: FieldValue | null; bank_account?: FieldValue | null };
  buyer?: { name?: FieldValue | null; billing_address?: FieldValue | null; shipping_address?: FieldValue | null; gstin?: FieldValue | null; pan?: FieldValue | null } | null;
  line_items: LineItem[];
  taxes: TaxDetails[];
  subtotal?: number | null;
  discount_total: number;
  tax_total: number;
  shipping_amount: number;
  grand_total?: number | null;
  currency: string;
  place_of_supply?: string | null;
  einvoice?: EInvoiceDetails;
  overall_confidence: number;
  validation_flags: ValidationFlag[];
  extraction_source?: string;
  field_locations: Record<string, BoundingBox>;
  standardized_invoice?: InvoiceDataStandard | null;
}

export interface Vendor {
  id: string; name: string; gstin?: string | null; pan?: string | null; address?: string | null; state?: string | null;
  email?: string | null; phone?: string | null; bank_name?: string | null; bank_account?: string | null;
  ifsc?: string | null; payment_terms?: string | null; invoice_count: number; total_spend: number; outstanding: number;
  created_at?: string | null;
}
export interface InvoiceItem { id: string; description: string; sku?: string | null; hsn?: string | null; sac?: string | null; hsn_sac?: string | null; quantity: number; unit?: string | null; unit_price: number; rate?: number; discount: number; taxable_value: number; gst_rate?: number | null; tax_amount: number; tax?: number; line_total: number; confidence: number }
export interface InvoiceTax { id: string; tax_type: string; rate_percent?: number | null; amount: number }
export interface ValidationResult { id: string; rule: string; passed: boolean; severity: "info" | "warning" | "error"; message: string; details: Record<string, unknown>; created_at?: string | null }
export interface RiskFlag { id: string; code: string; points: number; level: RiskLevel; message: string; resolved: boolean; details: Record<string, unknown>; created_at?: string | null }
export interface Payment { id: string; invoice_id: string; amount: number; payment_date: string; method: string; reference?: string | null; status: "confirmed" | "void"; notes?: string | null; created_at?: string | null }
export interface WorkflowEvent { id: string; invoice_id: string; action: string; from_status?: InvoiceStatus | null; to_status: InvoiceStatus; actor: string; comment?: string | null; created_at?: string | null }
export interface AuditEntry { id: string; document_id: string; field_path: string; old_value?: string | null; new_value: string; corrected_by: string; timestamp: string; predicted?: string | null; correct?: string | null }
export interface Invoice {
  id: string; document_id: string; filename?: string | null; preview_url?: string | null; page_count: number; processing_status?: string | null; status: InvoiceStatus; review_reason?: string | null;
  invoice_number?: string | null; duplicate_fingerprint?: string | null; invoice_date?: string | null; due_date?: string | null; po_number?: string | null; currency: string;
  subtotal?: number | null; discount_total: number; taxable_amount?: number | null; tax_total: number; cgst: number; sgst: number; igst: number; grand_total?: number | null;
  outstanding_amount: number; overall_confidence: number; confidence_score: number; ocr_text?: string | null; risk_score: number; risk_level: RiskLevel; match_status: MatchStatus;
  match_details: Record<string, unknown>; vendor?: Vendor | null; extraction?: InvoiceExtraction | null; items: InvoiceItem[]; taxes: InvoiceTax[];
  validations: ValidationResult[]; risk_flags: RiskFlag[]; payments: Payment[]; workflow: WorkflowEvent[]; corrections: AuditEntry[]; standardized_invoice?: InvoiceDataStandard | null; created_at?: string | null; updated_at?: string | null;
}
export interface InvoiceList { invoices: Invoice[]; total: number; page: number; page_size: number; total_pages: number }
export interface DashboardSummary {
  total_invoices: number; processing_invoices: number; review_invoices: number; approved_invoices: number;
  awaiting_payment_invoices: number; paid_invoices: number; rejected_invoices: number; duplicate_invoices: number; on_hold_invoices: number; outstanding_total: number;
  due_this_week: number; overdue_total: number; high_risk_count: number; average_confidence: number; total_tax: number;
  aging: { label: string; amount: number; count: number }[];
}
export interface VendorAnalytics { vendor_name: string; document_count: number; total_spend: number; average_confidence: number; currency: string }
export interface VolumePoint { date: string; document_count: number; average_confidence: number; average_processing_time_ms: number }
export interface APAnalytics { summary: DashboardSummary; vendors: VendorAnalytics[]; trends: VolumePoint[] }
export interface GSTSummary { total_tax: number; invoice_count: number; by_type: Record<string, number> }
export interface PurchaseOrder { id: string; number: string; vendor?: Vendor | null; vendor_id?: string | null; status: string; order_date?: string | null; expected_delivery?: string | null; currency: string; subtotal: number; tax_total: number; total: number; notes?: string | null; items: { id: string; description: string; hsn_sac?: string | null; quantity: number; unit_price: number; tax_rate?: number | null; line_total: number }[]; receipts?: GoodsReceipt[]; created_at?: string | null }
export interface GoodsReceipt { id: string; purchase_order_id: string; receipt_number: string; receipt_date: string; status: string; notes?: string | null; created_at?: string | null }
export interface PaymentDue { invoice_id: string; invoice_number?: string | null; vendor?: string | null; due_date?: string | null; grand_total?: number | null; outstanding_amount: number; status: InvoiceStatus; overdue: boolean }
export interface InvoiceQuestionResponse { question: string; answer: string; evidence: string[]; provider: string; grounded: boolean }
export interface DocumentResponse { id: string; filename: string; status: string; page_count: number; extraction?: InvoiceExtraction | null; standardized_invoice?: InvoiceDataStandard | null; error_message?: string | null; created_at: string; preview_url?: string | null }
export interface ProviderStatus { profile: string; ocr_engine: string; layout_engine?: string; document_parser?: string; configured_provider: string; active_provider: string; available: boolean; deterministic_fallback: boolean; zero_cost_default: boolean; message: string }
export interface DocumentUploadResponse { document_id: string; status: string; message?: string; duplicate_of?: string | null }

export function resolveFileUrl(fileUrl?: string | null): string {
  if (!fileUrl) return "";
  return /^https?:\/\//.test(fileUrl) ? fileUrl : `${API_BASE_URL}${fileUrl.startsWith("/") ? "" : "/"}${fileUrl}`;
}

export async function uploadDocument(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<DocumentUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const response = await apiClient.post<DocumentUploadResponse>("/documents", form, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (event) => {
      const total = event.total || file.size;
      if (total > 0) onProgress?.(Math.min(100, Math.round((event.loaded / total) * 100)));
    },
  });
  return response.data;
}

export async function fetchFileBlob(fileUrl: string): Promise<string> {
  const response = await apiClient.get<Blob>(fileUrl.replace(`${API_BASE_URL}/api/v1`, ""), { responseType: "blob" });
  return URL.createObjectURL(response.data);
}

export async function downloadFile(fileUrl: string, filename: string): Promise<void> {
  const response = await apiClient.get<Blob>(fileUrl.replace(`${API_BASE_URL}/api/v1`, ""), { responseType: "blob" });
  const objectUrl = URL.createObjectURL(response.data);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(objectUrl);
}

export function formatINR(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" }).format(new Date(value));
}
