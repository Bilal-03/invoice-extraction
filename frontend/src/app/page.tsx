import { Dashboard } from "@/components/Dashboard";
import { FileCheck2, Gauge, ShieldCheck } from "lucide-react";

export default function Home() {
  return (
    <div className="flex flex-col gap-8 pb-10">
      <header className="relative overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-br from-slate-900 via-slate-950 to-indigo-950/80 px-6 py-8 shadow-2xl shadow-indigo-950/30 sm:px-9 sm:py-10">
        <div className="absolute -right-16 -top-20 h-64 w-64 rounded-full bg-cyan-400/15 blur-3xl" />
        <div className="relative flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-300/10 px-3 py-1 text-xs font-medium text-cyan-200">
              <Gauge className="h-3.5 w-3.5" /> Document operations workspace
            </div>
            <h1 className="text-4xl font-extrabold tracking-tight text-white lg:text-5xl">
              Invoice Intelligence
            </h1>
            <p className="max-w-[640px] text-base leading-7 text-slate-300 sm:text-lg">
              Process invoices, resolve exceptions, and understand spend from one focused workspace.
            </p>
            <div className="flex flex-wrap gap-x-5 gap-y-2 pt-1 text-sm text-slate-300">
              <span className="inline-flex items-center gap-1.5"><FileCheck2 className="h-4 w-4 text-emerald-300" /> Native PDF fast path</span>
              <span className="inline-flex items-center gap-1.5"><ShieldCheck className="h-4 w-4 text-violet-300" /> Auditable corrections</span>
            </div>
          </div>
        </div>
      </header>

      <Dashboard />
    </div>
  );
}
