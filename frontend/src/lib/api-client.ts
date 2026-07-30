import axios from 'axios';

// Get the base URL from environment or fallback to localhost
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const apiClient = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Optionally add interceptors here for auth tokens, error handling, etc.
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error.response?.data || error.message);
    return Promise.reject(error);
  }
);

apiClient.interceptors.request.use((config) => {
  if (typeof window !== 'undefined') {
    const token = window.localStorage.getItem('invoice_access_token');
    const apiKey = window.localStorage.getItem('invoice_api_key');
    if (token) config.headers.Authorization = `Bearer ${token}`;
    if (apiKey) config.headers['X-API-Key'] = apiKey;
  }
  return config;
});

export type DocumentStatus = 'pending' | 'preprocessing' | 'ocr' | 'extracting' | 'validating' | 'completed' | 'failed';

export interface FieldValue {
  value: string | null;
  confidence: number;
  source: string;
  bounding_box?: BoundingBox | null;
}

export interface BoundingBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  page: number;
}

export interface VendorDetails {
  name: FieldValue;
  address?: FieldValue | null;
  gstin?: FieldValue | null;
  bank_account?: FieldValue | null;
}

export interface BuyerDetails {
  name?: FieldValue | null;
  billing_address?: FieldValue | null;
  shipping_address?: FieldValue | null;
}

export interface TaxDetails {
  tax_type: string;
  rate_percent?: number | null;
  amount: number;
}

export interface ValidationFlag {
  rule: string;
  passed: boolean;
  message: string;
  severity: 'info' | 'warning' | 'error';
}

export interface LineItem {
  description: string;
  quantity: number;
  unit_price: number;
  discount: number;
  line_total: number;
  confidence: number;
}

export interface InvoiceExtraction {
  invoice_number: FieldValue;
  invoice_date?: string | null;
  due_date?: string | null;
  po_reference?: FieldValue | null;
  payment_terms?: string | null;
  vendor: VendorDetails;
  buyer?: BuyerDetails | null;
  line_items: LineItem[];
  taxes: TaxDetails[];
  subtotal?: number | null;
  discount_total: number;
  tax_total: number;
  shipping_amount: number;
  grand_total?: number | null;
  currency: string;
  overall_confidence: number;
  extraction_source?: string;
  field_locations: Record<string, BoundingBox>;
  validation_flags: ValidationFlag[];
  processing_time_ms: number;
  vlm_input_tokens: number;
  vlm_output_tokens: number;
  estimated_cost_usd: number;
}

export interface DocumentResponse {
  id: string;
  filename: string;
  status: DocumentStatus;
  extraction?: InvoiceExtraction | null;
  error_message?: string | null;
  created_at: string;
  processing_time_ms?: number | null;
  page_count: number;
  file_url?: string | null;
  preview_url?: string | null;
}

export interface AuditEntry {
  id: string;
  document_id: string;
  field_path: string;
  old_value: string | null;
  new_value: string;
  corrected_by: string;
  timestamp: string;
}

export function resolveFileUrl(fileUrl?: string | null): string {
  if (!fileUrl) return '';
  if (/^https?:\/\//.test(fileUrl)) return fileUrl;
  return `${API_BASE_URL}${fileUrl.startsWith('/') ? '' : '/'}${fileUrl}`;
}

export interface AnalyticsSummary {
  total_documents: number;
  completed_documents: number;
  failed_documents: number;
  average_confidence: number;
  average_processing_time_ms: number;
  vlm_fallback_rate: number;
  documents_today: number;
  documents_this_week: number;
  average_cost_usd: number;
}
