import { PaperShell } from "@/components/analysis/paper-shell";
import { ProvidersClient } from "@/components/analysis/providers-client";

export default function ProvidersPage() {
  return (
    <PaperShell>
      <main className="mx-auto max-w-7xl px-6 py-12 lg:px-10">
        <p className="text-sm font-semibold uppercase tracking-[0.16em] text-emerald-800">
          Sanitized integration status
        </p>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight">
          Providers and request budget
        </h1>
        <div className="mt-8">
          <ProvidersClient />
        </div>
      </main>
    </PaperShell>
  );
}
