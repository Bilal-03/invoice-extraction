import { Dashboard } from "@/components/Dashboard";
import { AuthControls } from "@/components/AuthControls";

export default function Home() {
  return (
    <div className="flex flex-col gap-8 pb-10">
      <header className="flex flex-col gap-4 pt-6 pb-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <h1 className="text-4xl font-extrabold tracking-tight lg:text-5xl bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-600">
            Invoice Intelligence
          </h1>
          <p className="text-muted-foreground text-lg max-w-[600px]">
            Upload, validate, review, and audit invoices with layout-aware document intelligence.
          </p>
        </div>
        <AuthControls />
      </header>

      <Dashboard />
    </div>
  );
}
