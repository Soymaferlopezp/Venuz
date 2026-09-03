import type { Status, ValuationStatus } from "@/lib/api-contracts";

const styles: Record<Status | ValuationStatus, string> = {
  strong_green: "border-emerald-300 bg-emerald-100 text-emerald-950",
  green: "border-emerald-200 bg-emerald-50 text-emerald-800",
  yellow: "border-amber-200 bg-amber-50 text-amber-900",
  red: "border-red-200 bg-red-50 text-red-800",
  insufficient: "border-slate-200 bg-slate-50 text-slate-600",
};

export function StatusPill({ status }: { status: Status | ValuationStatus }) {
  return (
    <span
      className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${styles[status]}`}
    >
      {status.replace("_", " ")}
    </span>
  );
}
