import { Fingerprint, Landmark, SearchCheck, ShieldCheck } from "lucide-react";

import { ActivationPanel } from "@/components/cycles/activation-panel";

const principles = [
  {
    icon: SearchCheck,
    title: "Evidence before narrative",
    body: "Every decision retains its formula, timestamp, source, and provenance. AI explains; deterministic rules decide.",
  },
  {
    icon: ShieldCheck,
    title: "Risk is explicit",
    body: "Venuz preserves at least 20% cash and enforces position and sector limits before any Paper order is eligible.",
  },
  {
    icon: Fingerprint,
    title: "Durably idempotent",
    body: "Every visitor joins the same current cycle. Retries cannot multiply analyses, provider usage, or orders.",
  },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-[#f4f1e8] text-slate-950">
      <div className="border-b border-amber-300 bg-amber-200 px-4 py-2 text-center text-xs font-bold tracking-[0.2em] text-slate-950">
        ALPACA PAPER TRADING · NO REAL MONEY
      </div>
      <nav
        aria-label="Primary navigation"
        className="mx-auto flex max-w-7xl items-center justify-between px-6 py-6 lg:px-10"
      >
        <a href="#top" className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-slate-950 font-bold text-amber-300">
            V
          </span>
          <span>
            <span className="block text-lg font-semibold">Venuz</span>
            <span className="block text-[0.65rem] uppercase tracking-[0.2em] text-slate-500">
              Evidence-first equities
            </span>
          </span>
        </a>
        <span className="hidden items-center gap-2 text-sm text-slate-600 sm:flex">
          <Landmark aria-hidden="true" className="size-4" />
          Alpaca Paper only
        </span>
      </nav>
      <section
        id="top"
        className="mx-auto grid max-w-7xl gap-12 px-6 pb-20 pt-10 lg:grid-cols-[1.2fr_0.8fr] lg:px-10 lg:pt-20"
      >
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-emerald-800">
            Deterministic fundamental strategy
          </p>
          <h1 className="mt-5 max-w-4xl text-5xl font-semibold leading-[1.02] tracking-[-0.055em] sm:text-7xl">
            Know why before a trade is simulated.
          </h1>
          <p className="mt-7 max-w-2xl text-lg leading-8 text-slate-600">
            Venuz screens high-quality US equities, explains every rule with
            real evidence, and submits only to Alpaca Paper after every safety
            guard passes.
          </p>
        </div>
        <ActivationPanel />
      </section>
      <section className="border-y border-slate-300 bg-white">
        <div className="mx-auto max-w-7xl px-6 py-16 lg:px-10">
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">
            Built to stop safely
          </p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight">
            One transparent cycle, shared by everyone.
          </h2>
          <div className="mt-10 grid gap-5 md:grid-cols-3">
            {principles.map(({ icon: Icon, title, body }) => (
              <article
                key={title}
                className="rounded-2xl border border-slate-200 bg-[#faf9f5] p-6"
              >
                <Icon aria-hidden="true" className="size-5 text-emerald-800" />
                <h3 className="mt-5 text-lg font-semibold">{title}</h3>
                <p className="mt-3 text-sm leading-6 text-slate-600">{body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>
      <section id="setup" className="mx-auto max-w-7xl px-6 py-12 lg:px-10">
        <h2 className="text-xl font-semibold">
          Run Venuz with your own credentials
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
          Clone the repository and follow the README. Never paste keys into the
          browser; all broker and provider secrets belong in the API
          environment.
        </p>
      </section>
      <footer className="mx-auto flex max-w-7xl flex-col gap-2 px-6 py-8 text-sm text-slate-500 sm:flex-row sm:justify-between lg:px-10">
        <p>Venuz · Global cycle · Alpaca Paper only</p>
        <p>Not financial advice. No real performance is represented.</p>
      </footer>
    </main>
  );
}
