"use client";

import React from "react";
import Link from "next/link";
import {
  Activity,
  ArrowUpRight,
  Briefcase,
  DollarSign,
  Gauge,
  MessageSquareText,
  Sparkles,
  Timer,
  TrendingUp,
  Users,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatRelative, useAsync } from "@/lib/hooks";
import type { Metrics, Overview } from "@/lib/types";
import { PageHeader } from "@/components/layout/AppShell";
import {
  Badge,
  EmptyState,
  ErrorState,
  Panel,
  SectionTitle,
  Skeleton,
} from "@/components/ui/primitives";
import {
  BarList,
  ChartFrame,
  DataTable,
  FunnelChart,
  KIND_COLORS,
  KIND_LABELS,
  Legend,
  StatTile,
  formatMs,
  formatUsd,
} from "@/components/charts";

const ACTIVITY_LABELS: Record<string, string> = {
  created: "Candidatura criada",
  stage_change: "Mudança de etapa",
  note: "Anotação",
  ai_rank: "Ranqueamento por IA",
  ai_explain: "Análise da IA",
  bias_audit: "Auditoria de viés",
};

function LoadingGrid() {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} className="h-24" />
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const overview = useAsync<Overview>(() => api.overview());
  const metrics = useAsync<Metrics>(() => api.metrics(168));

  if (overview.error) {
    return (
      <>
        <PageHeader title="Visão geral" />
        <Panel>
          <ErrorState error={overview.error} onRetry={overview.reload} />
        </Panel>
      </>
    );
  }

  const data = overview.data;
  const m = metrics.data;

  const funnelStages = (data?.by_stage ?? []).filter((s) => s.stage !== "rejected");
  const conversion =
    data && data.applications_total > 0
      ? Math.round((data.hired / data.applications_total) * 100)
      : 0;

  return (
    <>
      <PageHeader
        title="Visão geral"
        description="O estado do funil de contratações e a saúde do pipeline de IA que o alimenta."
        actions={
          <>
            <Link href="/copilot" className="btn btn-ghost px-3.5 py-2">
              <MessageSquareText className="h-4 w-4" />
              Falar com o copiloto
            </Link>
            <Link href="/jobs" className="btn btn-primary px-3.5 py-2">
              <Briefcase className="h-4 w-4" />
              Ver vagas
            </Link>
          </>
        }
      />

      {overview.loading || !data ? (
        <LoadingGrid />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile
            label="Vagas abertas"
            value={data.jobs_open}
            hint={`${data.jobs_total} vagas no total`}
            icon={Briefcase}
          />
          <StatTile
            label="Banco de talentos"
            value={data.candidates_total}
            hint={`${data.applications_total} candidaturas ativas`}
            icon={Users}
          />
          <StatTile
            label="Aderência forte"
            value={data.strong_fit_count}
            hint="candidaturas classificadas pela IA como forte"
            tone={data.strong_fit_count > 0 ? "good" : "default"}
            icon={Sparkles}
          />
          <StatTile
            label="Score médio"
            value={data.avg_ai_score.toFixed(1)}
            unit="/100"
            hint={`${conversion}% das candidaturas chegaram a contratação`}
            icon={TrendingUp}
          />
        </div>
      )}

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Panel className="p-5 lg:col-span-1">
          <SectionTitle
            title="Funil de contratação"
            subtitle="Distribuição das candidaturas por etapa"
            icon={Gauge}
          />
          {overview.loading || !data ? (
            <Skeleton className="h-48" />
          ) : data.applications_total === 0 ? (
            <EmptyState
              title="Nenhuma candidatura ainda"
              description="Publique uma vaga e ranqueie o banco de talentos para preencher o funil."
              action={
                <Link href="/jobs" className="btn btn-primary px-3.5 py-2">
                  Ir para vagas
                </Link>
              }
            />
          ) : (
            <ChartFrame
              title="Etapas"
              hint="Reprovados aparecem separadamente abaixo"
              table={
                <DataTable
                  columns={["Etapa", "Candidaturas"]}
                  rows={data.by_stage.map((s) => [s.label, s.count])}
                />
              }
            >
              <FunnelChart
                stages={funnelStages.map((s) => ({ key: s.stage, label: s.label, count: s.count }))}
              />
              <div className="mt-3 flex items-center justify-between border-t border-white/8 pt-3 text-[11px]">
                <span className="text-[var(--text-muted)]">Reprovados</span>
                <span className="tabular text-[var(--text-secondary)]">{data.rejected}</span>
              </div>
            </ChartFrame>
          )}
        </Panel>

        <Panel className="p-5 lg:col-span-2">
          <SectionTitle
            title="Saúde do pipeline de IA"
            subtitle="Últimos 7 dias de execuções instrumentadas"
            icon={Activity}
            action={
              <Link
                href="/observability"
                className="inline-flex items-center gap-1 text-[11px] text-[var(--accent-soft)] hover:underline"
              >
                Abrir observabilidade
                <ArrowUpRight className="h-3 w-3" />
              </Link>
            }
          />

          {metrics.loading ? (
            <Skeleton className="h-48" />
          ) : metrics.error ? (
            <ErrorState error={metrics.error} onRetry={metrics.reload} />
          ) : !m || m.totals.traces === 0 ? (
            <EmptyState
              title="Nenhuma execução registrada"
              description="Assim que você ranquear uma vaga ou conversar com o copiloto, os traces aparecem aqui."
            />
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <StatTile label="Execuções" value={m.totals.traces} icon={Activity} />
                <StatTile
                  label="Latência p95"
                  value={formatMs(m.totals.p95_ms)}
                  hint={`p50 ${formatMs(m.totals.p50_ms)}`}
                  icon={Timer}
                />
                <StatTile
                  label="Taxa de erro"
                  value={`${(m.totals.error_rate * 100).toFixed(1)}%`}
                  tone={m.totals.error_rate > 0.05 ? "critical" : m.totals.error_rate > 0 ? "warning" : "good"}
                  hint={`${m.totals.errors} falhas`}
                />
                <StatTile
                  label="Custo de LLM"
                  value={formatUsd(m.totals.cost_usd)}
                  hint={`${m.totals.llm_calls} chamadas · ${m.totals.tokens.toLocaleString("pt-BR")} tokens`}
                  icon={DollarSign}
                />
              </div>

              <div className="mt-5">
                <ChartFrame
                  title="Onde o tempo é gasto"
                  hint="Tempo acumulado por camada do pipeline"
                  legend={
                    <Legend
                      items={m.by_kind
                        .slice(0, 6)
                        .map((k) => ({
                          label: KIND_LABELS[k.kind] ?? k.kind,
                          color: KIND_COLORS[k.kind] ?? "var(--series-1)",
                          value: formatMs(k.total_ms),
                        }))}
                    />
                  }
                  table={
                    <DataTable
                      columns={["Camada", "Execuções", "p50", "p95", "Total"]}
                      rows={m.by_kind.map((k) => [
                        KIND_LABELS[k.kind] ?? k.kind,
                        k.count,
                        formatMs(k.p50_ms),
                        formatMs(k.p95_ms),
                        formatMs(k.total_ms),
                      ])}
                    />
                  }
                >
                  <BarList
                    data={m.by_kind.slice(0, 6).map((k) => ({
                      key: k.kind,
                      label: KIND_LABELS[k.kind] ?? k.kind,
                      value: k.total_ms,
                      secondary: `${k.count} execuções · p95 ${formatMs(k.p95_ms)}`,
                    }))}
                    valueFormat={formatMs}
                    colorFor={(key) => KIND_COLORS[key] ?? "var(--series-1)"}
                  />
                </ChartFrame>
              </div>
            </>
          )}
        </Panel>
      </div>

      <Panel className="mt-4 p-5">
        <SectionTitle
          title="Atividade recente"
          subtitle="Tudo que aconteceu no funil, incluindo o que a IA fez"
          icon={Activity}
        />
        {overview.loading || !data ? (
          <Skeleton className="h-40" />
        ) : data.recent_activity.length === 0 ? (
          <EmptyState title="Nada aconteceu ainda" />
        ) : (
          <ul className="divide-y divide-white/6">
            {data.recent_activity.map((activity) => (
              <li key={activity.id} className="flex flex-wrap items-start gap-3 py-2.5">
                <Badge tone={activity.actor === "IA" || activity.actor === "Copiloto IA" ? "accent" : "neutral"}>
                  {activity.actor}
                </Badge>
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-[var(--text-secondary)]">
                    {activity.content ?? ACTIVITY_LABELS[activity.type] ?? activity.type}
                  </p>
                  <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">
                    {activity.candidate ? `${activity.candidate} · ` : ""}
                    {activity.job ?? ""}
                  </p>
                </div>
                <span className="shrink-0 text-[11px] text-[var(--text-muted)]">
                  {formatRelative(activity.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  );
}
