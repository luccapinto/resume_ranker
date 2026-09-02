"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BrainCircuit,
  Briefcase,
  LayoutDashboard,
  Menu,
  MessageSquareText,
  ScaleIcon,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { RuntimeConfig } from "@/lib/types";
import { cn, StatusDot } from "@/components/ui/primitives";

const NAV = [
  { href: "/", label: "Visão geral", icon: LayoutDashboard, exact: true },
  { href: "/jobs", label: "Vagas", icon: Briefcase },
  { href: "/candidates", label: "Talentos", icon: Users },
  { href: "/copilot", label: "Copiloto", icon: MessageSquareText },
  { href: "/fairness", label: "Equidade", icon: ScaleIcon },
  { href: "/observability", label: "Observabilidade", icon: Activity },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = React.useState(false);
  const [config, setConfig] = React.useState<RuntimeConfig | null>(null);
  const [online, setOnline] = React.useState<boolean | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const [cfg] = await Promise.all([api.config(), api.health()]);
        if (!cancelled) {
          setConfig(cfg);
          setOnline(true);
        }
      } catch {
        if (!cancelled) setOnline(false);
      }
    };
    check();
    const timer = setInterval(check, 30_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const isActive = (item: (typeof NAV)[number]) =>
    item.exact ? pathname === item.href : pathname.startsWith(item.href);

  return (
    <div className="flex min-h-screen">
      {/* Mobile overlay */}
      {open ? (
        <div
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={() => setOpen(false)}
          aria-hidden
        />
      ) : null}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-white/8 bg-[rgba(12,12,16,0.92)] backdrop-blur-xl transition-transform lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between gap-2 px-5 py-5">
          <Link href="/" className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)]">
              <BrainCircuit className="h-4.5 w-4.5 text-white" />
            </span>
            <span className="leading-tight">
              <span className="block text-sm font-semibold tracking-tight">Resume Ranker</span>
              <span className="block text-[10px] uppercase tracking-widest text-[var(--text-muted)]">
                ATS com IA
              </span>
            </span>
          </Link>
          <button
            className="rounded-lg p-1.5 text-[var(--text-muted)] hover:bg-white/8 lg:hidden"
            onClick={() => setOpen(false)}
            aria-label="Fechar menu"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-1 px-3">
          {NAV.map((item) => {
            const active = isActive(item);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setOpen(false)}
                className={cn(
                  "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors",
                  active
                    ? "bg-white/[0.08] font-medium text-[var(--text-primary)]"
                    : "text-[var(--text-muted)] hover:bg-white/[0.04] hover:text-[var(--text-secondary)]",
                )}
              >
                <item.icon
                  className={cn("h-4 w-4", active && "text-[var(--accent-soft)]")}
                  aria-hidden
                />
                {item.label}
                {active ? (
                  <span
                    aria-hidden
                    className="ml-auto h-1.5 w-1.5 rounded-full bg-[var(--accent-soft)]"
                  />
                ) : null}
              </Link>
            );
          })}
        </nav>

        <div className="space-y-2.5 border-t border-white/8 px-5 py-4">
          <StatusDot
            ok={online === true}
            label={online === null ? "Verificando API…" : online ? "API conectada" : "API offline"}
          />
          {config ? (
            <dl className="space-y-1 text-[10px] leading-relaxed text-[var(--text-muted)]">
              <div className="flex justify-between gap-2">
                <dt>LLM</dt>
                <dd className="truncate text-right text-[var(--text-secondary)]" title={config.llm_model}>
                  {config.llm_model.split("/").pop()}
                </dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt>Embeddings</dt>
                <dd className="truncate text-right text-[var(--text-secondary)]" title={config.embedding_model}>
                  {config.embedding_model.split(":").pop()?.split("/").pop()}
                </dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt>Reranker</dt>
                <dd className="truncate text-right text-[var(--text-secondary)]" title={config.reranker_model}>
                  {config.reranker_model.split("/").pop()}
                </dd>
              </div>
            </dl>
          ) : null}
          <div className="flex items-center gap-1.5 rounded-lg border border-white/8 bg-white/[0.03] px-2 py-1.5 text-[10px] text-[var(--text-muted)]">
            <ShieldCheck className="h-3 w-3 shrink-0 text-[var(--status-good)]" />
            PII anonimizada antes de qualquer LLM
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-white/8 bg-[rgba(8,8,11,0.72)] px-4 py-3 backdrop-blur-xl lg:hidden">
          <button
            onClick={() => setOpen(true)}
            className="rounded-lg p-1.5 text-[var(--text-secondary)] hover:bg-white/8"
            aria-label="Abrir menu"
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="text-sm font-semibold">Resume Ranker</span>
        </header>

        <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</main>
      </div>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  breadcrumb?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {breadcrumb ? <div className="mb-2">{breadcrumb}</div> : null}
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
        {description ? (
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-[var(--text-muted)]">
            {description}
          </p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}
