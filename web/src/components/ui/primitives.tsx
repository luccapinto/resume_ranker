"use client";

import React from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Info,
  Loader2,
  MinusCircle,
  XCircle,
} from "lucide-react";
import type { Fit } from "@/lib/types";

export function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

/* ── Surfaces ─────────────────────────────────────────────────────────── */
export function Panel({
  className,
  children,
  hover = false,
  ...rest
}: React.HTMLAttributes<HTMLDivElement> & { hover?: boolean }) {
  return (
    <div className={cn("panel", hover && "panel-hover", className)} {...rest}>
      {children}
    </div>
  );
}

export function SectionTitle({
  title,
  subtitle,
  icon: Icon,
  action,
}: {
  title: string;
  subtitle?: string;
  icon?: React.ElementType;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-4">
      <div className="flex items-start gap-3">
        {Icon ? (
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/5 text-[var(--accent-soft)]">
            <Icon className="h-4 w-4" />
          </span>
        ) : null}
        <div>
          <h2 className="text-sm font-semibold tracking-tight text-[var(--text-primary)]">{title}</h2>
          {subtitle ? (
            <p className="mt-0.5 text-xs leading-relaxed text-[var(--text-muted)]">{subtitle}</p>
          ) : null}
        </div>
      </div>
      {action}
    </div>
  );
}

/* ── Badges ───────────────────────────────────────────────────────────── */
const badgeTones = {
  neutral: "bg-white/5 text-[var(--text-secondary)] border-white/10",
  accent: "bg-[color-mix(in_srgb,var(--accent)_18%,transparent)] text-[var(--accent-soft)] border-[color-mix(in_srgb,var(--accent)_35%,transparent)]",
  good: "bg-[color-mix(in_srgb,var(--status-good)_16%,transparent)] text-[var(--status-good)] border-[color-mix(in_srgb,var(--status-good)_35%,transparent)]",
  warning:
    "bg-[color-mix(in_srgb,var(--status-warning)_16%,transparent)] text-[var(--status-warning)] border-[color-mix(in_srgb,var(--status-warning)_35%,transparent)]",
  critical:
    "bg-[color-mix(in_srgb,var(--status-critical)_16%,transparent)] text-[var(--status-critical)] border-[color-mix(in_srgb,var(--status-critical)_38%,transparent)]",
} as const;

export type BadgeTone = keyof typeof badgeTones;

export function Badge({
  children,
  tone = "neutral",
  icon: Icon,
  className,
  title,
}: {
  children: React.ReactNode;
  tone?: BadgeTone;
  icon?: React.ElementType;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium leading-none",
        badgeTones[tone],
        className,
      )}
    >
      {Icon ? <Icon className="h-3 w-3 shrink-0" /> : null}
      {children}
    </span>
  );
}

/** Fit is a status, so it always ships with an icon *and* the word — never colour alone. */
export function FitBadge({ fit, className }: { fit: Fit | null | undefined; className?: string }) {
  const map: Record<Fit, { tone: BadgeTone; icon: React.ElementType; label: string }> = {
    forte: { tone: "good", icon: CheckCircle2, label: "Aderência forte" },
    moderado: { tone: "warning", icon: AlertTriangle, label: "Aderência moderada" },
    baixo: { tone: "critical", icon: MinusCircle, label: "Aderência baixa" },
  };
  if (!fit || !map[fit]) return <Badge className={className}>Sem análise</Badge>;
  const { tone, icon, label } = map[fit];
  return (
    <Badge tone={tone} icon={icon} className={className}>
      {label}
    </Badge>
  );
}

export function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-[var(--text-muted)]">
      <span
        aria-hidden
        className={cn("h-1.5 w-1.5 rounded-full", ok ? "bg-[var(--status-good)] pulse-dot" : "bg-[var(--status-critical)]")}
      />
      {label}
    </span>
  );
}

/* ── Buttons ──────────────────────────────────────────────────────────── */
export function Button({
  children,
  variant = "ghost",
  loading = false,
  icon: Icon,
  className,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost";
  loading?: boolean;
  icon?: React.ElementType;
}) {
  return (
    <button
      className={cn("btn", variant === "primary" ? "btn-primary" : "btn-ghost", "px-3.5 py-2", className)}
      disabled={rest.disabled || loading}
      {...rest}
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin" />
      ) : Icon ? (
        <Icon className="h-4 w-4" />
      ) : null}
      {children}
    </button>
  );
}

/* ── Feedback ─────────────────────────────────────────────────────────── */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} />;
}

export function EmptyState({
  title,
  description,
  icon: Icon = Info,
  action,
}: {
  title: string;
  description?: string;
  icon?: React.ElementType;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/5 text-[var(--text-muted)]">
        <Icon className="h-5 w-5" />
      </span>
      <div>
        <p className="text-sm font-medium text-[var(--text-secondary)]">{title}</p>
        {description ? (
          <p className="mx-auto mt-1 max-w-sm text-xs leading-relaxed text-[var(--text-muted)]">
            {description}
          </p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-[color-mix(in_srgb,var(--status-critical)_14%,transparent)] text-[var(--status-critical)]">
        <XCircle className="h-5 w-5" />
      </span>
      <div>
        <p className="text-sm font-medium text-[var(--text-secondary)]">Algo falhou</p>
        <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-[var(--text-muted)]">{error}</p>
      </div>
      {onRetry ? (
        <Button onClick={onRetry} variant="ghost">
          Tentar novamente
        </Button>
      ) : null}
    </div>
  );
}

/* ── Chips ────────────────────────────────────────────────────────────── */
export function SkillChips({
  skills,
  tone = "neutral",
  max = 12,
  emptyLabel = "—",
}: {
  skills: string[];
  tone?: BadgeTone;
  max?: number;
  emptyLabel?: string;
}) {
  if (!skills?.length) {
    return <span className="text-xs text-[var(--text-muted)]">{emptyLabel}</span>;
  }
  const shown = skills.slice(0, max);
  const rest = skills.length - shown.length;
  return (
    <div className="flex flex-wrap gap-1.5">
      {shown.map((s) => (
        <Badge key={s} tone={tone}>
          {s}
        </Badge>
      ))}
      {rest > 0 ? <Badge title={skills.slice(max).join(", ")}>+{rest}</Badge> : null}
    </div>
  );
}

/* ── Tabs ─────────────────────────────────────────────────────────────── */
export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: { key: T; label: string; icon?: React.ElementType; count?: number }[];
  active: T;
  onChange: (key: T) => void;
}) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1 rounded-xl border border-white/8 bg-white/[0.03] p-1">
      {tabs.map((tab) => {
        const isActive = tab.key === active;
        return (
          <button
            key={tab.key}
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(tab.key)}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
              isActive
                ? "bg-white/10 text-[var(--text-primary)]"
                : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]",
            )}
          >
            {tab.icon ? <tab.icon className="h-3.5 w-3.5" /> : null}
            {tab.label}
            {typeof tab.count === "number" ? (
              <span className="tabular rounded bg-white/8 px-1.5 py-0.5 text-[10px] text-[var(--text-muted)]">
                {tab.count}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

/* ── Modal ────────────────────────────────────────────────────────────── */
export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  React.useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", handler);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", handler);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm sm:p-8">
      <div
        className="absolute inset-0"
        onClick={onClose}
        aria-hidden
      />
      <Panel
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn(
          "animate-fade-up relative z-10 my-auto w-full",
          wide ? "max-w-5xl" : "max-w-2xl",
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-white/8 px-6 py-4">
          <div>
            <h3 className="text-sm font-semibold text-[var(--text-primary)]">{title}</h3>
            {subtitle ? <p className="mt-0.5 text-xs text-[var(--text-muted)]">{subtitle}</p> : null}
          </div>
          <button
            onClick={onClose}
            aria-label="Fechar"
            className="rounded-lg p-1.5 text-[var(--text-muted)] transition-colors hover:bg-white/8 hover:text-[var(--text-primary)]"
          >
            <XCircle className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[75vh] overflow-y-auto px-6 py-5">{children}</div>
      </Panel>
    </div>
  );
}
