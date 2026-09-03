import Link from "next/link";
import type { ReactNode } from "react";

const links = [
  ["/", "Overview"],
  ["/screener", "Screener"],
  ["/companies/AAPL", "Thesis"],
  ["/providers", "Providers"],
  ["/sign-in", "Sign in"],
] as const;

export function PaperShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-[#f6f7f4] text-slate-950">
      <div className="bg-amber-100 px-4 py-2 text-center text-xs font-bold tracking-[0.16em] text-amber-950">
        PAPER TRADING - NO REAL MONEY
      </div>
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-6 py-5 sm:flex-row sm:items-center sm:justify-between lg:px-10">
          <Link
            href="/"
            className="text-xl font-semibold tracking-tight focus-visible:outline-2 focus-visible:outline-offset-4"
          >
            Venuz
          </Link>
          <nav
            aria-label="Analysis navigation"
            className="flex flex-wrap gap-2"
          >
            {links.map(([href, label]) => (
              <Link
                key={href}
                href={href}
                className="rounded-full px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 focus-visible:outline-2"
              >
                {label}
              </Link>
            ))}
          </nav>
        </div>
      </header>
      {children}
      <footer className="mx-auto max-w-7xl px-6 py-10 text-sm text-slate-500 lg:px-10">
        Evidence-first analysis. No orders in this phase. Not financial advice.
      </footer>
    </div>
  );
}
