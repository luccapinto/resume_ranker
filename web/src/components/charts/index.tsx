"use client";

/**
 * Hand-rolled SVG charts.
 *
 * Conventions applied throughout (they are not stylistic preferences):
 * - one value axis per chart, never two;
 * - categorical colour comes from the validated `--series-*` slots, assigned in
 *   fixed order and keyed to the *entity*, so filtering never repaints survivors;
 * - a legend is present whenever there are ≥ 2 series, and identity is never
 *   carried by colour alone;
 * - marks are thin, data-ends are rounded 4px against the baseline, and adjacent
 *   fills keep a 2px surface gap;
 * - grid and axes are recessive; every chart has a hover layer and a table view.
 */

import React from "react";
import { Table2 } from "lucide-react";
import { cn } from "@/components/ui/primitives";

export const SERIES = [
  "var(--series-1)",
  "var(--series-2)",
  "var(--series-3)",
  "var(--series-4)",
  "var(--series-5)",
  "var(--series-6)",
] as const;

export const ORDINAL = [
  "var(--ordinal-1)",
  "var(--ordinal-2)",
  "var(--ordinal-3)",
  "var(--ordinal-4)",
  "var(--ordinal-5)",
  "var(--ordinal-6)",
] as const;

/** Span kinds get a stable colour each — the map is the entity→colour contract. */
export const KIND_COLORS: Record<string, string> = {
  llm: "var(--series-1)",
  embedding: "var(--series-2)",
  vector: "var(--series-3)",
  rerank: "var(--series-4)",
  pii: "var(--series-5)",
  logic: "var(--series-6)",
  tool: "var(--series-1)",
  parse: "var(--series-3)",
  db: "var(--series-6)",
};

export const KIND_LABELS: Record<string, string> = {
  llm: "LLM",
  embedding: "Embedding",
  vector: "Busca vetorial",
  rerank: "Reranking",
  pii: "Anonimização PII",
  logic: "Lógica",
  tool: "Ferramenta",
  parse: "Parsing",
  db: "Banco",
};

export function formatMs(ms: number): string {
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)} min`;
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${Math.round(ms)} ms`;
}

export function formatUsd(value: number): string {
  if (value === 0) return "US$ 0";
  if (value < 0.01) return `US$ ${value.toFixed(5)}`;
  return `US$ ${value.toFixed(4)}`;
}

export function formatCount(value: number): string {
  return new Intl.NumberFormat("pt-BR").format(value);
}

/* ── Table view toggle ────────────────────────────────────────────────── */
function TableToggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      aria-pressed={open}
      className="inline-flex items-center gap-1.5 rounded-lg border border-white/8 px-2 py-1 text-[10px] text-[var(--text-muted)] transition-colors hover:border-white/16 hover:text-[var(--text-secondary)]"
    >
      <Table2 className="h-3 w-3" />
      {open ? "Ver gráfico" : "Ver dados"}
    </button>
  );
}

export function ChartFrame({
  title,
  hint,
  legend,
  table,
  children,
  className,
}: {
  title: string;
  hint?: string;
  legend?: React.ReactNode;
  table?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const [showTable, setShowTable] = React.useState(false);
  return (
    <div className={cn("flex h-full flex-col", className)}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-xs font-semibold tracking-tight text-[var(--text-secondary)]">{title}</h3>
          {hint ? <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">{hint}</p> : null}
        </div>
        {table ? <TableToggle open={showTable} onToggle={() => setShowTable((v) => !v)} /> : null}
      </div>
      {showTable && table ? (
        <div className="flex-1 overflow-auto">{table}</div>
      ) : (
        <div className="flex-1">{children}</div>
      )}
      {legend && !showTable ? <div className="mt-3">{legend}</div> : null}
    </div>
  );
}

export function Legend({
  items,
}: {
  items: { label: string; color: string; value?: string }[];
}) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)]">
          <span
            aria-hidden
            className="h-2 w-2 shrink-0 rounded-[2px]"
            style={{ background: item.color }}
          />
          <span className="text-[var(--text-secondary)]">{item.label}</span>
          {item.value ? <span className="tabular">{item.value}</span> : null}
        </li>
      ))}
    </ul>
  );
}

/* ── Stat tile ────────────────────────────────────────────────────────── */
export function StatTile({
  label,
  value,
  unit,
  hint,
  tone = "default",
  icon: Icon,
}: {
  label: string;
  value: string | number;
  unit?: string;
  hint?: string;
  tone?: "default" | "good" | "warning" | "critical";
  icon?: React.ElementType;
}) {
  const toneColor = {
    default: "var(--text-primary)",
    good: "var(--status-good)",
    warning: "var(--status-warning)",
    critical: "var(--status-critical)",
  }[tone];

  return (
    <div className="panel panel-hover px-4 py-3.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">
          {label}
        </span>
        {Icon ? <Icon className="h-3.5 w-3.5 text-[var(--text-muted)]" /> : null}
      </div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className="text-2xl font-semibold leading-none" style={{ color: toneColor }}>
          {value}
        </span>
        {unit ? <span className="text-xs text-[var(--text-muted)]">{unit}</span> : null}
      </div>
      {hint ? <p className="mt-1.5 text-[11px] leading-snug text-[var(--text-muted)]">{hint}</p> : null}
    </div>
  );
}

/* ── Horizontal bar list ──────────────────────────────────────────────── */
export function BarList({
  data,
  valueFormat = formatCount,
  colorFor,
}: {
  data: { key: string; label: string; value: number; secondary?: string }[];
  valueFormat?: (n: number) => string;
  colorFor?: (key: string, index: number) => string;
}) {
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <ul className="flex flex-col gap-2.5">
      {data.map((d, i) => {
        const color = colorFor ? colorFor(d.key, i) : SERIES[i % SERIES.length];
        const pct = (d.value / max) * 100;
        return (
          <li key={d.key} className="group">
            <div className="mb-1 flex items-baseline justify-between gap-3">
              <span className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                <span aria-hidden className="h-2 w-2 rounded-[2px]" style={{ background: color }} />
                {d.label}
              </span>
              <span className="tabular text-xs text-[var(--text-primary)]">{valueFormat(d.value)}</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-white/[0.05]">
              <div
                className="h-full rounded-full transition-[width] duration-500"
                style={{ width: `${Math.max(pct, 1.5)}%`, background: color }}
                title={`${d.label}: ${valueFormat(d.value)}`}
              />
            </div>
            {d.secondary ? (
              <p className="mt-1 text-[10px] text-[var(--text-muted)]">{d.secondary}</p>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

/* ── Funnel ───────────────────────────────────────────────────────────── */
export function FunnelChart({
  stages,
  onSelect,
  activeStage,
}: {
  stages: { key: string; label: string; count: number }[];
  onSelect?: (key: string) => void;
  activeStage?: string | null;
}) {
  const max = Math.max(...stages.map((s) => s.count), 1);
  return (
    <ul className="flex flex-col gap-2">
      {stages.map((stage, i) => {
        const pct = (stage.count / max) * 100;
        const color = ORDINAL[Math.min(i, ORDINAL.length - 1)];
        const isActive = activeStage === stage.key;
        return (
          <li key={stage.key}>
            <button
              type="button"
              onClick={onSelect ? () => onSelect(stage.key) : undefined}
              disabled={!onSelect}
              aria-pressed={isActive}
              className={cn(
                "w-full rounded-lg px-2 py-1.5 text-left transition-colors",
                onSelect && "hover:bg-white/[0.04]",
                isActive && "bg-white/[0.06]",
              )}
            >
              <div className="mb-1 flex items-baseline justify-between gap-3">
                <span className="text-xs text-[var(--text-secondary)]">{stage.label}</span>
                <span className="tabular text-xs font-medium text-[var(--text-primary)]">
                  {stage.count}
                </span>
              </div>
              <div className="h-2.5 w-full overflow-hidden rounded-full bg-white/[0.05]">
                <div
                  className="h-full rounded-full transition-[width] duration-500"
                  style={{ width: `${Math.max(pct, 2)}%`, background: color }}
                />
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/* ── Score meter ──────────────────────────────────────────────────────── */
export function ScoreRing({
  value,
  size = 56,
  label,
  tone,
}: {
  value: number;
  size?: number;
  label?: string;
  tone?: string;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  const stroke = 5;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const color =
    tone ?? (clamped >= 75 ? "var(--status-good)" : clamped >= 50 ? "var(--status-warning)" : "var(--status-critical)");

  return (
    <div className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" role="img" aria-label={`Score ${clamped.toFixed(0)} de 100`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--grid)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - clamped / 100)}
          style={{ transition: "stroke-dashoffset 600ms cubic-bezier(0.22,1,0.36,1)" }}
        />
      </svg>
      <span className="absolute flex flex-col items-center leading-none">
        <span className="tabular text-sm font-semibold text-[var(--text-primary)]">
          {clamped.toFixed(0)}
        </span>
        {label ? <span className="mt-0.5 text-[9px] text-[var(--text-muted)]">{label}</span> : null}
      </span>
    </div>
  );
}

/* ── Time series (single measure, crosshair + tooltip) ────────────────── */
export function TimeSeries({
  data,
  valueKey,
  color = "var(--series-1)",
  valueFormat = formatCount,
  height = 150,
}: {
  data: { bucket: string; [key: string]: number | string }[];
  valueKey: string;
  color?: string;
  valueFormat?: (n: number) => string;
  height?: number;
}) {
  const [hover, setHover] = React.useState<number | null>(null);
  const width = 640;
  const pad = { top: 12, right: 12, bottom: 22, left: 44 };

  if (data.length === 0) {
    return (
      <div className="flex h-[150px] items-center justify-center text-xs text-[var(--text-muted)]">
        Sem dados no período.
      </div>
    );
  }

  const values = data.map((d) => Number(d[valueKey]) || 0);
  const maxValue = Math.max(...values, 1);
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;

  const x = (i: number) => pad.left + (data.length === 1 ? innerW / 2 : (i / (data.length - 1)) * innerW);
  const y = (v: number) => pad.top + innerH - (v / maxValue) * innerH;

  const line = values.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const area = `${line} L${x(values.length - 1).toFixed(1)},${pad.top + innerH} L${x(0).toFixed(1)},${pad.top + innerH} Z`;

  const ticks = [0, 0.5, 1].map((t) => maxValue * t);
  const hovered = hover !== null ? data[hover] : null;

  const label = (bucket: string) =>
    new Date(bucket).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit" });

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ height }}
        role="img"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          const relative = ((event.clientX - rect.left) / rect.width) * width;
          const index = Math.round(((relative - pad.left) / innerW) * (data.length - 1));
          setHover(Math.max(0, Math.min(data.length - 1, index)));
        }}
      >
        <defs>
          <linearGradient id={`fill-${valueKey}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.28" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>

        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={pad.left}
              x2={width - pad.right}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--grid)"
              strokeWidth="1"
            />
            <text
              x={pad.left - 8}
              y={y(t) + 3}
              textAnchor="end"
              className="tabular"
              fontSize="9"
              fill="var(--text-muted)"
            >
              {valueFormat(t)}
            </text>
          </g>
        ))}

        <path d={area} fill={`url(#fill-${valueKey})`} />
        <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />

        {data.length <= 30
          ? values.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r="2.5" fill={color} />)
          : null}

        {hover !== null ? (
          <g>
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={pad.top}
              y2={pad.top + innerH}
              stroke="var(--border-strong)"
              strokeWidth="1"
              strokeDasharray="3 3"
            />
            <circle
              cx={x(hover)}
              cy={y(values[hover])}
              r="4.5"
              fill={color}
              stroke="var(--surface-1)"
              strokeWidth="2"
            />
          </g>
        ) : null}

        <text x={pad.left} y={height - 6} fontSize="9" fill="var(--text-muted)">
          {label(String(data[0].bucket))}
        </text>
        {data.length > 1 ? (
          <text x={width - pad.right} y={height - 6} textAnchor="end" fontSize="9" fill="var(--text-muted)">
            {label(String(data[data.length - 1].bucket))}
          </text>
        ) : null}
      </svg>

      {hovered ? (
        <div
          className="pointer-events-none absolute top-1 z-10 rounded-lg border border-white/12 bg-[var(--surface-2)] px-2.5 py-1.5 text-[11px] shadow-xl"
          style={{
            left: `${(x(hover!) / width) * 100}%`,
            transform: `translateX(${hover! > data.length / 2 ? "-105%" : "5%"})`,
          }}
        >
          <p className="text-[var(--text-muted)]">{label(String(hovered.bucket))}</p>
          <p className="tabular mt-0.5 font-medium text-[var(--text-primary)]">
            {valueFormat(Number(hovered[valueKey]) || 0)}
          </p>
        </div>
      ) : null}
    </div>
  );
}

/* ── Trace waterfall ──────────────────────────────────────────────────── */
export function Waterfall({
  spans,
  totalMs,
  onSelect,
  selectedId,
}: {
  spans: {
    id: string;
    name: string;
    kind: string;
    status: string;
    depth: number;
    duration_ms: number;
    started_at_offset_ms: number;
  }[];
  totalMs: number;
  onSelect?: (id: string) => void;
  selectedId?: string | null;
}) {
  const total = Math.max(totalMs, 1);
  return (
    <ul className="flex flex-col gap-1">
      {spans.map((span) => {
        const left = (span.started_at_offset_ms / total) * 100;
        const width = Math.max((span.duration_ms / total) * 100, 0.6);
        const isError = span.status === "error";
        const color = isError ? "var(--status-critical)" : KIND_COLORS[span.kind] ?? "var(--series-1)";
        const selected = selectedId === span.id;
        return (
          <li key={span.id}>
            <button
              type="button"
              onClick={onSelect ? () => onSelect(span.id) : undefined}
              className={cn(
                "grid w-full grid-cols-[minmax(160px,240px)_1fr_64px] items-center gap-3 rounded-lg px-2 py-1.5 text-left transition-colors",
                onSelect && "hover:bg-white/[0.04]",
                selected && "bg-white/[0.07]",
              )}
            >
              <span
                className="truncate text-[11px] text-[var(--text-secondary)]"
                style={{ paddingLeft: `${span.depth * 12}px` }}
                title={span.name}
              >
                <span
                  aria-hidden
                  className="mr-1.5 inline-block h-2 w-2 rounded-[2px] align-middle"
                  style={{ background: color }}
                />
                {span.name}
              </span>
              <span className="relative block h-4 rounded bg-white/[0.03]">
                <span
                  className="absolute top-1/2 h-2 -translate-y-1/2 rounded"
                  style={{ left: `${left}%`, width: `${width}%`, background: color }}
                  title={`${span.name} — ${formatMs(span.duration_ms)}`}
                />
              </span>
              <span className="tabular text-right text-[11px] text-[var(--text-muted)]">
                {formatMs(span.duration_ms)}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/* ── Simple data table (used as the table view of every chart) ────────── */
export function DataTable({
  columns,
  rows,
}: {
  columns: string[];
  rows: (string | number)[][];
}) {
  return (
    <table className="w-full text-left text-[11px]">
      <thead>
        <tr className="border-b border-white/8">
          {columns.map((c) => (
            <th key={c} className="px-2 py-1.5 font-medium text-[var(--text-muted)]">
              {c}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i} className="border-b border-white/[0.04]">
            {row.map((cell, j) => (
              <td key={j} className={cn("px-2 py-1.5 text-[var(--text-secondary)]", j > 0 && "tabular")}>
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
