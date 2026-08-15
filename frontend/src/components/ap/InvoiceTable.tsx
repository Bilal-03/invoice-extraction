import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import type { Invoice } from "../../lib/api-client";
import { formatDate, formatINR } from "../../lib/api-client";
import { RiskBadge } from "./RiskBadge";
import { StatusPill } from "./StatusPill";

export function InvoiceTable({ invoices, compact = false }: { invoices: Invoice[]; compact?: boolean }) {
  return (
    <div className="invoice-table-wrap">
      <table className="invoice-table">
        <thead><tr><th>Invoice</th><th>Vendor</th><th>Due</th><th>Total</th><th>Status</th>{!compact && <th>Risk</th>}<th /></tr></thead>
        <tbody>
          {invoices.map((invoice) => (
            <tr key={invoice.id}>
              <td><Link className="invoice-link" to={`/invoices/${invoice.id}`}>{invoice.invoice_number || "Unnumbered"}</Link><small>{invoice.filename || "Extracted record"}</small></td>
              <td><strong>{invoice.vendor?.name || "Unknown vendor"}</strong><small>{invoice.vendor?.gstin || "GSTIN not detected"}</small></td>
              <td>{formatDate(invoice.due_date)}</td>
              <td className="money-cell">{formatINR(invoice.grand_total)}</td>
              <td><StatusPill status={invoice.status} /></td>
              {!compact && <td><RiskBadge level={invoice.risk_level} score={invoice.risk_score} /></td>}
              <td><Link className="row-arrow" to={`/invoices/${invoice.id}`}><ChevronRight size={16} /></Link></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
