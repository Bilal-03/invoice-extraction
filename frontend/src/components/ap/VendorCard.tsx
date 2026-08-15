import { Link } from "react-router-dom";
import type { Vendor } from "../../lib/api-client";
import { formatINR } from "../../lib/api-client";

export function VendorCard({ vendor }: { vendor: Vendor }) {
  return (
    <article className="vendor-card">
      <div><strong>{vendor.name}</strong><small>{vendor.gstin || "GSTIN not detected"}</small></div>
      <div className="vendor-card-metrics"><span><em>Invoices</em><b>{vendor.invoice_count}</b></span><span><em>Spend</em><b>{formatINR(vendor.total_spend)}</b></span><span><em>Outstanding</em><b>{formatINR(vendor.outstanding)}</b></span></div>
      <Link className="secondary-button tiny" to={`/invoices?search=${encodeURIComponent(vendor.name)}`}>View invoices</Link>
    </article>
  );
}
