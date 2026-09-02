"use client";

import React from "react";
import { useSearchParams } from "next/navigation";
import {
  Activity,
  AlertTriangle,
  Braces,
  Clock,
  DollarSign,
  Filter,
  Layers,
  RefreshCw,
  Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatDateTime, formatRelative, useAsync, usePolling } from "@/lib/hooks";
import type { Metrics, Span, Trace } from "@/lib/types";
import { PageHeader } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Modal,
  Panel,
  SectionTitle,
  Skeleton,
  Tabs,
  cn,
} from "@/components/ui/primitives";
import {
  BarList,
  ChartFrame,
  DataTable,
  KIND_COLORS,
  KIND_LABELS,
  Legend,
  StatTile,
  TimeSeries,
  Waterfall,
  formatCount,
  formatMs,
  formatUsd,
} from "@/components/charts";

const WINDOWS = [
  { key: "1", label: "1 h" },
  { key: "24", label: "24 h" },
  { key: "168", label: "7 d" },
  { key: "720", label: "30 d" },
] as const;

function SpanDetail({ span }: { span: Span }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge
          tone={span.status === "error" ? "critical" : "neutral"}
          icon={span.status === "error" ? AlertTriangle : undefined}
        >
          {span.status === "error" ? "erro" : "ok"}
        </Badge>
        <Badge tone="accent">{KIND_LABELS[span.kind] ?? span.kind}</Badge>
        <Badge>{formatMs(span.duration_ms)}</Badge>
        {span.model ? <Badge icon={Braces}>{span.model}</Badge> : null}
        {span.prompt_tokens || span.completion_tokens ? (
          <Badge>
            {span.prompt_tokens} in / {span.completion_tokens} out
          </Badge>
        ) : null}
        {span.cost_usd ? <Badge icon={DollarSign}>{formatUsd(span.cost_usd)}</Badge> : null}
      </div>

      {span.error_message ? (
        <div className="rounded-lg border border-[color-mix(in_srgb,var(--status-critical)_35%,transparent)] bg-[color-mix(in_srgb,var(--status-critical)_10%,transparent)] p-3">
          <p className="text-[11px] font-medium text-[var(--status-critical)]">{span.error_type}</p>
          <p className="mt-1 whitespace-pre-wrap font-mono text-[11px] text-[var(--text-secondary)]">
            {span.error_message}
          </p>
        </div>
      ) : null}

      {Object.keys(span.attributes ?? {}).length ? (
        <div>
          <p className="mb-1.5 text-[11px] font-medium text-[var(--text-muted)]">Atributos</p>
          <div className="rounded-lg border border-white/8 bg-black/30 p-3">
            <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-[10px] leading-relaxed text-[var(--text-secondary)]">
              {JSON.stringify(span.attributes, null, 2)}
            </pre>
          </div>
        </div>
      ) : null}

      {span.input_preview ? (
        <details open={span.kind === "llm"}>
          <summary className="cursor-pointer text-[11px] text-[var(--text-muted)] hover:text-[var(--text-secondary)]">
            Entrada enviada
          </summary>
          <pre className="mt-1.5 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-white/8 bg-black/30 p-3 font-mono text-[10px] leading-relaxed text-[var(--text-secondary)]">
            {span.input_preview}
          </pre>
        </details>
      ) : null}

      {span.output_preview ? (
        <details open={span.kind === "llm"}>
          <summary className="cursor-pointer text-[11px] text-[var(--text-muted)] hover:text-[var(--text-secondary)]">
            Saída recebida
          </summary>
          <pre className="mt-1.5 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-white/8 bg-black/30 p-3 font-mono text-[10px] leading-relaxed text-[var(--text-secondary)]">
            {span.output_preview}
          </pre>
        </details>
      ) : null}
    </div>
  );
}

function TraceModal({ traceId, onClose }: { traceId: string | null; onClose: () => void }) {
  const [selected, setSelected] = React.useState<string | null>(null);
  const trace = useAsync<Trace | null>(
    () => (traceId ? api.trace(traceId) : Promise.resolve(null)),
    [traceId],
  );

  const spans = trace.data?.spans ?? [];
  const selectedSpan = spans.find((s) => s.id === selected) ?? null;

  return (
    <Modal
      open={!!traceId}
      onClose={onClose}
      wide
      title={trace.data?.name ?? "Trace"}
      subtitle={
        trace.data
          ? `${formatMs(trace.data.duration_ms)} · ${trace.data.span_count} spans · ${
              trace.data.llm_calls
            } chamadas de LLM · ${formatUsd(trace.data.total_cost_usd)}`
          : undefined
      }
    >
      {trace.loading ? (
        <Skeleton className="h-64" />
      ) : trace.error ? (
        <ErrorState error={trace.error} onRetry={trace.reload} />
      ) : trace.data ? (
        <div className="space-y-4">
          {trace.data.error_message ? (
            <div className="rounded-lg border border-[color-mix(in_srgb,var(--status-critical)_35%,transparent)] bg-[color-mix(in_srgb,var(--status-critical)_10%,transparent)] p-3 text-[11px] text-[var(--status-critical)]">
              {trace.data.error_message}
            </div>
          ) : null}

          {Object.keys(trace.data.metadata ?? {}).length ? (
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(trace.data.metadata).map(([key, value]) => (
                <Badge key={key}>
                  {key}: {String(value)}
                </Badge>
              ))}
            </div>
          ) : null}

          <div>
            <p className="mb-2 flex items-center gap-1.5 text-[11px] font-medium text-[var(--text-secondary)]">
              <Layers className="h-3 w-3" />
              Cascata de execução
            </p>
            <Waterfall
              spans={spans}
              totalMs={trace.data.duration_ms}
              onSelect={setSelected}
              selectedId={selected}
            />
          </div>

          {selectedSpan ? (
            <div className="animate-fade-up rounded-xl border border-white/8 bg-white/[0.02] p-4">
              <p className="mb-2.5 font-mono text-xs text-[var(--accent-soft)]">{selectedSpan.name}</p>
              <SpanDetail span={selectedSpan} />
            </div>
          ) : (
            <p className="rounded-xl border border-dashed border-white/8 px-4 py-6 text-center text-[11px] text-[var(--text-muted)]">
              Clique em uma etapa da cascata para inspecionar prompts, tokens, custo e erros.
            </p>
          )}
        </div>
      ) : null}
    </Modal>
  );
}

function TraceRow({ trace, onOpen }: { trace: Trace; onOpen: () => void }) {
  return (
    <button
      onClick={onOpen}
      className="grid w-full grid-cols-[1fr_auto] items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-white/[0.04] sm:grid-cols-[minmax(0,2fr)_repeat(4,minmax(0,1fr))]"
    >
      <div className="min-w-0">
        <p className="flex items-center gap-2 truncate font-mono text-xs text-[var(--text-primary)]">
          <span
            aria-hidden
            className={cn(
              "h-1.5 w-1.5 shrink-0 rounded-full",
              trace.status === "error" ? "bg-[var(--status-critical)]" : "bg-[var(--status-good)]",
            )}
          />
          {trace.name}
        </p>
        <p className="mt-0.5 truncate text-[11px] text-[var(--text-muted)]">
          {formatRelative(trace.started_at)} · {trace.span_count} spans
        </p>
      </div>
      <span className="tabular hidden text-right text-xs text-[var(--text-secondary)] sm:block">
        {formatMs(trace.duration_ms)}
      </span>
      <span className="tabular hidden text-right text-xs text-[var(--text-muted)] sm:block">
        {trace.llm_calls} LLM
      </span>
      <span className="tabular hidden text-right text-xs text-[var(--text-muted)] sm:block">
        {formatCount(trace.total_tokens)} tok
      </span>
      <span className="tabular text-right text-xs text-[var(--text-muted)]">
        {formatUsd(trace.total_cost_usd)}
      </span>
    </button>
  );
}

function ObservabilityDashboard() {
  const searchParams = useSearchParams();
  const [windowHours, setWindowHours] = React.useState<(typeof WINDOWS)[number]["key"]>("168");
  const [statusFilter, setStatusFilter] = React.useState<"all" | "ok" | "error">("all");
  // Deep links like /observability?trace=<id> open straight into the waterfall.
  const [openTrace, setOpenTrace] = React.useState<string | null>(() => searchParams.get("trace"));
  const [live, setLive] = React.useState(true);

  const metrics = useAsync<Metrics>(() => api.metrics(Number(windowHours)), [windowHours]);
  const traces = useAsync<Trace[]>(
    () => api.traces({ limit: 60, status: statusFilter === "all" ? undefined : statusFilter }),
    [statusFilter],
  );

  usePolling(() => {
    metrics.reload();
    traces.reload();
  }, 15_000, live);

  const m = metrics.data;

  return (
    <>
      <PageHeader
        title="Observabilidade"
        description="Cada operação de IA é rastreada ponta a ponta: latência por etapa, tokens, custo, prompts e erros."
        actions={
          <>
            <Button
              icon={Zap}
              onClick={() => setLive((v) => !v)}
              className={cn(live && "text-[var(--status-good)]")}
            >
              {live ? "Ao vivo" : "Pausado"}
            </Button>
            <Button
              icon={RefreshCw}
              onClick={() => {
                metrics.reload();
                traces.reload();
              }}
            >
              Atualizar
            </Button>
          </>
        }
      />

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <Tabs
          active={windowHours}
          onChange={setWindowHours}
          tabs={WINDOWS.map((w) => ({ key: w.key, label: w.label }))}
        />
        <span className="text-[11px] text-[var(--text-muted)]">janela de análise</span>
      </div>

      {metrics.loading && !m ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : metrics.error ? (
        <Panel>
          <ErrorState error={metrics.error} onRetry={metrics.reload} />
        </Panel>
      ) : !m || m.totals.traces === 0 ? (
        <Panel>
          <EmptyState
            icon={Activity}
            title="Nenhuma execução registrada nesta janela"
            description="Ranqueie uma vaga, cadastre um currículo ou converse com o copiloto para gerar traces."
          />
        </Panel>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <StatTile label="Execuções" value={formatCount(m.totals.traces)} hint={`${m.totals.spans} spans`} icon={Activity} />
            <StatTile
              label="Latência p95"
              value={formatMs(m.totals.p95_ms)}
              hint={`p50 ${formatMs(m.totals.p50_ms)} · p99 ${formatMs(m.totals.p99_ms)}`}
              icon={Clock}
            />
            <StatTile
              label="Taxa de erro"
              value={`${(m.totals.error_rate * 100).toFixed(1)}%`}
              hint={`${m.totals.errors} execuções com falha`}
              tone={m.totals.error_rate > 0.05 ? "critical" : m.totals.error_rate > 0 ? "warning" : "good"}
              icon={AlertTriangle}
            />
            <StatTile
              label="Tokens"
              value={formatCount(m.totals.tokens)}
              hint={`${m.totals.llm_calls} chamadas de LLM`}
              icon={Braces}
            />
            <StatTile
              label="Custo acumulado"
              value={formatUsd(m.totals.cost_usd)}
              hint="soma reportada pelo provedor"
              icon={DollarSign}
            />
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Panel className="p-5">
              <ChartFrame
                title="Volume de execuções ao longo do tempo"
                hint="Agregado por hora"
                table={
                  <DataTable
                    columns={["Hora", "Execuções", "Erros", "p95", "Custo"]}
                    rows={m.timeseries.map((t) => [
                      formatDateTime(t.bucket),
                      t.count,
                      t.errors,
                      formatMs(t.p95_ms),
                      formatUsd(t.cost_usd),
                    ])}
                  />
                }
              >
                <TimeSeries data={m.timeseries} valueKey="count" valueFormat={formatCount} />
              </ChartFrame>
            </Panel>

            <Panel className="p-5">
              <ChartFrame
                title="Latência p95 ao longo do tempo"
                hint="Percentil 95 por hora"
                table={
                  <DataTable
                    columns={["Hora", "p95"]}
                    rows={m.timeseries.map((t) => [formatDateTime(t.bucket), formatMs(t.p95_ms)])}
                  />
                }
              >
                <TimeSeries
                  data={m.timeseries}
                  valueKey="p95_ms"
                  color="var(--series-2)"
                  valueFormat={formatMs}
                />
              </ChartFrame>
            </Panel>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <Panel className="p-5">
              <ChartFrame
                title="Tempo por camada do pipeline"
                hint="Tempo próprio: a duração de cada span menos a dos filhos"
                legend={
                  <Legend
                    items={m.by_kind.slice(0, 6).map((k) => ({
                      label: KIND_LABELS[k.kind] ?? k.kind,
                      color: KIND_COLORS[k.kind] ?? "var(--series-1)",
                    }))}
                  />
                }
                table={
                  <DataTable
                    columns={["Camada", "Execuções", "Erros", "p50", "p95", "Tempo próprio"]}
                    rows={m.by_kind.map((k) => [
                      KIND_LABELS[k.kind] ?? k.kind,
                      k.count,
                      k.errors,
                      formatMs(k.p50_ms),
                      formatMs(k.p95_ms),
                      formatMs(k.self_ms),
                    ])}
                  />
                }
              >
                <BarList
                  data={m.by_kind.slice(0, 6).map((k) => ({
                    key: k.kind,
                    label: KIND_LABELS[k.kind] ?? k.kind,
                    value: k.self_ms,
                    secondary: `${k.count} spans · p95 ${formatMs(k.p95_ms)}${k.errors ? ` · ${k.errors} erro(s)` : ""}`,
                  }))}
                  valueFormat={formatMs}
                  colorFor={(key) => KIND_COLORS[key] ?? "var(--series-1)"}
                />
              </ChartFrame>
            </Panel>

            <Panel className="p-5">
              <SectionTitle title="Operações" subtitle="Latência e erro por tipo de execução" icon={Layers} />
              <div className="overflow-x-auto">
                <DataTable
                  columns={["Operação", "Exec.", "p50", "p95", "Erro"]}
                  rows={m.by_operation
                    .slice(0, 12)
                    .map((op) => [
                      op.name,
                      op.count,
                      formatMs(op.p50_ms),
                      formatMs(op.p95_ms),
                      `${(op.error_rate * 100).toFixed(0)}%`,
                    ])}
                />
              </div>
            </Panel>

            <Panel className="p-5">
              <SectionTitle title="Modelos" subtitle="Uso, latência e custo por modelo" icon={Braces} />
              {m.by_model.length === 0 ? (
                <p className="text-xs text-[var(--text-muted)]">Nenhuma chamada de LLM na janela.</p>
              ) : (
                <ul className="space-y-3">
                  {m.by_model.map((model) => (
                    <li key={model.model} className="rounded-lg border border-white/8 bg-white/[0.02] p-3">
                      <p className="truncate font-mono text-[11px] text-[var(--accent-soft)]">
                        {model.model}
                      </p>
                      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                        <div className="flex justify-between">
                          <dt className="text-[var(--text-muted)]">Chamadas</dt>
                          <dd className="tabular text-[var(--text-secondary)]">{model.calls}</dd>
                        </div>
                        <div className="flex justify-between">
                          <dt className="text-[var(--text-muted)]">p95</dt>
                          <dd className="tabular text-[var(--text-secondary)]">{formatMs(model.p95_ms)}</dd>
                        </div>
                        <div className="flex justify-between">
                          <dt className="text-[var(--text-muted)]">Tokens</dt>
                          <dd className="tabular text-[var(--text-secondary)]">
                            {formatCount(model.tokens)}
                          </dd>
                        </div>
                        <div className="flex justify-between">
                          <dt className="text-[var(--text-muted)]">Custo</dt>
                          <dd className="tabular text-[var(--text-secondary)]">
                            {formatUsd(model.cost_usd)}
                          </dd>
                        </div>
                      </dl>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>

          {m.recent_errors.length ? (
            <Panel className="mt-4 p-5">
              <SectionTitle
                title="Erros recentes"
                subtitle="Falhas capturadas dentro dos spans, com o trace de origem"
                icon={AlertTriangle}
              />
              <ul className="space-y-2">
                {m.recent_errors.map((error, i) => (
                  <li
                    key={i}
                    className="flex flex-wrap items-center gap-3 rounded-lg border border-[color-mix(in_srgb,var(--status-critical)_25%,transparent)] bg-[color-mix(in_srgb,var(--status-critical)_7%,transparent)] px-3 py-2"
                  >
                    <Badge tone="critical">{error.error_type ?? "erro"}</Badge>
                    <span className="font-mono text-[11px] text-[var(--text-secondary)]">{error.span}</span>
                    <span className="min-w-0 flex-1 truncate text-[11px] text-[var(--text-muted)]">
                      {error.error_message}
                    </span>
                    <button
                      onClick={() => setOpenTrace(error.trace_id)}
                      className="text-[11px] text-[var(--accent-soft)] hover:underline"
                    >
                      abrir trace
                    </button>
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}
        </>
      )}

      <Panel className="mt-4 p-5">
        <SectionTitle
          title="Traces recentes"
          subtitle="Clique em qualquer execução para abrir a cascata completa"
          icon={Filter}
          action={
            <Tabs
              active={statusFilter}
              onChange={setStatusFilter}
              tabs={[
                { key: "all", label: "Todos" },
                { key: "ok", label: "Sucesso" },
                { key: "error", label: "Erro" },
              ]}
            />
          }
        />
        {traces.loading && !traces.data ? (
          <Skeleton className="h-64" />
        ) : traces.error ? (
          <ErrorState error={traces.error} onRetry={traces.reload} />
        ) : !traces.data?.length ? (
          <EmptyState title="Nenhum trace nesta seleção" />
        ) : (
          <div className="divide-y divide-white/6">
            {traces.data.map((trace) => (
              <TraceRow key={trace.id} trace={trace} onOpen={() => setOpenTrace(trace.id)} />
            ))}
          </div>
        )}
      </Panel>

      {/* Keyed by trace so the selected span resets without an effect. */}
      <TraceModal key={openTrace ?? "none"} traceId={openTrace} onClose={() => setOpenTrace(null)} />
    </>
  );
}

/**
 * `useSearchParams` opts the subtree out of prerendering, so the dashboard sits
 * behind its own Suspense boundary and the shell still renders statically.
 */
export default function ObservabilityPage() {
  return (
    <React.Suspense
      fallback={
        <div className="space-y-4">
          <Skeleton className="h-16 w-64" />
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
          <Skeleton className="h-64" />
        </div>
      }
    >
      <ObservabilityDashboard />
    </React.Suspense>
  );
}
