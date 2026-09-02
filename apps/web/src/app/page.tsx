import {
  ArrowRight,
  Database,
  FileSearch,
  Fingerprint,
  Landmark,
  ShieldCheck,
} from "lucide-react";

import { ApiHealth } from "@/components/health/api-health";

const principles = [
  {
    icon: FileSearch,
    title: "Evidencia antes que narrativa",
    body: "Cada decisión conservará fórmula, fecha, fuente y procedencia. La IA explica; las reglas deterministas deciden.",
  },
  {
    icon: ShieldCheck,
    title: "Riesgo explícito",
    body: "El sistema protege 20% de efectivo y limita posiciones y sectores antes de habilitar cualquier acción.",
  },
  {
    icon: Fingerprint,
    title: "Auditable de extremo a extremo",
    body: "Análisis, aprobaciones y futuros cambios de órdenes quedan vinculados por identificadores e inputs verificables.",
  },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-[#f6f7f4] text-slate-950">
      <div className="border-b border-amber-300 bg-amber-100 px-4 py-2 text-center text-xs font-bold tracking-[0.18em] text-amber-950 sm:text-sm">
        PAPER TRADING — NO REAL MONEY
      </div>

      <nav
        aria-label="Navegación principal"
        className="mx-auto flex max-w-7xl items-center justify-between px-6 py-6 lg:px-10"
      >
        <a
          href="#inicio"
          className="flex items-center gap-3 rounded-md focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-slate-900"
        >
          <span className="grid size-10 place-items-center rounded-xl bg-slate-950 text-sm font-bold text-amber-300">
            V
          </span>
          <span>
            <span className="block text-lg font-semibold tracking-tight">
              Venuz
            </span>
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
        id="inicio"
        className="mx-auto grid max-w-7xl gap-12 px-6 pb-16 pt-12 lg:grid-cols-[1.25fr_0.75fr] lg:px-10 lg:pb-24 lg:pt-20"
      >
        <div>
          <p className="mb-5 text-sm font-semibold uppercase tracking-[0.18em] text-emerald-800">
            Estrategia fundamental determinista
          </p>
          <h1 className="max-w-4xl text-5xl font-semibold leading-[1.02] tracking-[-0.055em] text-slate-950 sm:text-6xl lg:text-7xl">
            Entender el porqué antes de simular una operación.
          </h1>
          <p className="mt-7 max-w-2xl text-lg leading-8 text-slate-600 sm:text-xl">
            Venuz identifica acciones estadounidenses de calidad, aplica reglas
            de valoración y riesgo transparentes y conserva la evidencia de cada
            conclusión.
          </p>
          <a
            href="#fundacion"
            className="mt-9 inline-flex items-center gap-2 rounded-full bg-slate-950 px-6 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-slate-950"
          >
            Explorar la fundación
            <ArrowRight aria-hidden="true" className="size-4" />
          </a>
        </div>

        <aside className="self-end rounded-3xl border border-slate-200 bg-white p-6 shadow-[0_24px_80px_-48px_rgba(15,23,42,0.45)] sm:p-8">
          <div className="mb-6 flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-xl bg-emerald-50 text-emerald-800">
              <Database aria-hidden="true" className="size-5" />
            </span>
            <div>
              <p className="font-semibold">Estado de la fundación</p>
              <p className="text-sm text-slate-500">
                Contrato público y seguro
              </p>
            </div>
          </div>
          <ApiHealth />
        </aside>
      </section>

      <section
        id="fundacion"
        aria-labelledby="foundation-title"
        className="border-y border-slate-200 bg-white"
      >
        <div className="mx-auto max-w-7xl px-6 py-16 lg:px-10 lg:py-20">
          <div className="max-w-2xl">
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">
              Controles desde el primer día
            </p>
            <h2
              id="foundation-title"
              className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl"
            >
              Una base diseñada para fallar de forma segura.
            </h2>
          </div>
          <div className="mt-10 grid gap-5 md:grid-cols-3">
            {principles.map(({ icon: Icon, title, body }) => (
              <article
                key={title}
                className="rounded-2xl border border-slate-200 bg-[#fafbf8] p-6"
              >
                <Icon aria-hidden="true" className="size-5 text-emerald-800" />
                <h3 className="mt-5 text-lg font-semibold">{title}</h3>
                <p className="mt-3 text-sm leading-6 text-slate-600">{body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <footer className="mx-auto flex max-w-7xl flex-col gap-3 px-6 py-8 text-sm text-slate-500 sm:flex-row sm:items-center sm:justify-between lg:px-10">
        <p>Venuz · Fundación local · Sin órdenes habilitadas</p>
        <p>
          No es asesoría financiera. Rendimientos reales no están representados.
        </p>
      </footer>
    </main>
  );
}
