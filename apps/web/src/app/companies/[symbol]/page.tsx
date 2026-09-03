import { PaperShell } from "@/components/analysis/paper-shell";
import { CompanyClient } from "@/components/analysis/company-client";

export default async function CompanyPage({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const { symbol } = await params;
  return (
    <PaperShell>
      <CompanyClient symbol={symbol.toUpperCase()} />
    </PaperShell>
  );
}
