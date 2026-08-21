import { useEffect, useState } from "react";
import {
  BarChart3,
  ClipboardCheck,
  LayoutDashboard,
  PackageCheck,
  PanelLeft,
  Plus,
  ReceiptIndianRupee,
  Search,
  Store,
  UploadCloud,
  WalletCards,
} from "lucide-react";
import {
  Link,
  NavLink,
  Navigate,
  Outlet,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";
import { apiClient, type ProviderStatus } from "./lib/api-client";
import { Input } from "./components/ui/input";
import DashboardPage from "./pages/Dashboard";
import InvoiceDetailsPage from "./pages/InvoiceDetails";
import InvoicesPage from "./pages/Invoices";
import AnalyticsPage from "./pages/Analytics";
import PaymentsPage from "./pages/Payments";
import PurchaseOrdersPage from "./pages/PurchaseOrders";
import ReviewQueuePage from "./pages/Review";
import UploadPage from "./pages/Upload";
import VendorsPage from "./pages/Vendors";
import { NotFound } from "./pages/screens";
const navItems = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/upload", label: "Upload invoices", icon: UploadCloud },
  { to: "/invoices", label: "Invoices", icon: ReceiptIndianRupee },
  { to: "/review", label: "Review queue", icon: ClipboardCheck },
  { to: "/vendors", label: "Vendors", icon: Store },
  { to: "/purchase-orders", label: "Purchase orders", icon: PackageCheck },
  { to: "/payments", label: "Payments", icon: WalletCards },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
];

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/invoices" element={<InvoicesPage />} />
        <Route path="/invoices/:invoiceId" element={<InvoiceDetailsPage />} />
        <Route path="/review" element={<ReviewQueuePage />} />
        <Route path="/vendors" element={<VendorsPage />} />
        <Route path="/purchase-orders" element={<PurchaseOrdersPage />} />
        <Route path="/payments" element={<PaymentsPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [provider, setProvider] = useState<ProviderStatus | null>(null);
  const navigate = useNavigate();
  useEffect(() => {
    void apiClient.get<ProviderStatus>("/provider/status").then((response) => setProvider(response.data)).catch(() => undefined);
  }, []);
  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? "open" : ""}`}>
        <div className="brand-lockup">
          <img className="brand-mark" src="/brand/invoice-intelligence-mark.svg" alt="" aria-hidden="true" />
          <div><strong>Invoice Intelligence</strong><span>AP operations console</span></div>
        </div>
        <div className="sidebar-label">Workspace</div>
        <nav className="nav-list">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} onClick={() => setSidebarOpen(false)} className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <Icon size={17} strokeWidth={1.8} /><span>{label}</span>
              {label === "Review queue" && <span className="nav-dot" />}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="provider-card"><span className={`live-dot ${provider?.available ? "available" : ""}`} /><div><strong>{provider?.active_provider || "Deterministic OCR + rules"}</strong><small>{provider?.message || "Local AI optional · zero-cost default"}</small></div></div>
          <div className="workspace-user"><span className="avatar">AP</span><div><strong>AP workspace</strong><small>Single-tenant ledger</small></div></div>
        </div>
      </aside>
      <main className="main-area">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label="Toggle navigation"><PanelLeft size={19} /></button>
          <div className="topbar-search"><Search size={16} /><Input className="topbar-input" value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && search.trim()) navigate(`/invoices?search=${encodeURIComponent(search.trim())}`); }} placeholder="Search invoices, vendors, GSTINs…" /><kbd>⌘ K</kbd></div>
          <div className="topbar-actions"><span className="environment-tag"><i /> local workspace</span><Link className="primary-button compact" to="/upload"><Plus size={15} /> New invoice</Link></div>
        </header>
        <div className="page-wrap"><Outlet /></div>
      </main>
    </div>
  );
}
