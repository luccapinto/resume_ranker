"use client";

import React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Building2,
  ChevronRight,
  FileText,
  KanbanSquare,
  ListOrdered,
  RefreshCw,
  Settings2,
  Sparkles,
} from "lucide-react";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import type { Application, Job, KanbanBoard as Board, RankResult, Stage } from "@/lib/types";
import { PageHeader } from "@/components/layout/AppShell";
import {
  Button,
  EmptyState,
  ErrorState,
  Panel,
  SectionTitle,
  SkillChips,
  Skeleton,
  Tabs,
} from "@/components/ui/primitives";
import { RankedCandidateCard } from "@/components/ats/CandidateCard";
import { KanbanBoard } from "@/components/ats/Kanban";
import { PiiViewer } from "@/components/ats/PiiViewer";
import { formatMs } from "@/components/charts";

type TabKey = "ranking" | "pipeline" | "detalhes";

/** The tuning panel — exposes the retrieval knobs instead of hiding them. */
function RankControls({
  weights,
  setWeights,
  rerank,
  setRerank,
  topN,
  setTopN,
  minYears,
  setMinYears,
  explainTop,
  setExplainTop,
}: {
  weights: [number, number, number];
  setWeights: (w: [number, number, number]) => void;
  rerank: boolean;
  setRerank: (v: boolean) => void;
  topN: number;
  setTopN: (v: number) => void;
  minYears: string;
  setMinYears: (v: string) => void;
  explainTop: number;
  setExplainTop: (v: number) => void;
}) {
  const labels = ["Competências", "Trajetória", "Lexical"];
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div>
        <p className="mb-2 text-[11px] font-medium text-[var(--text-secondary)]">
          Pesos da fusão RRF
        </p>
        <div className="space-y-2.5">
          {labels.map((label, i) => (
            <label key={label} className="block">
              <span className="mb-1 flex items-center justify-between text-[11px] text-[var(--text-muted)]">
                {label}
                <span className="tabular text-[var(--text-secondary)]">{weights[i].toFixed(1)}</span>
              </span>
              <input
                type="range"
                min={0}
                max={2}
                step={0.1}
                value={weights[i]}
                onChange={(e) => {
                  const next = [...weights] as [number, number, number];
                  next[i] = Number(e.target.value);
                  setWeights(next);
                }}
                className="w-full accent-[var(--accent)]"
              />
            </label>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        <label className="block">
          <span className="mb-1 block text-[11px] text-[var(--text-muted)]">
            Quantidade de candidatos
          </span>
          <input
            type="number"
            min={1}
            max={30}
            value={topN}
            onChange={(e) => setTopN(Number(e.target.value))}
            className="field w-full px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] text-[var(--text-muted)]">
            Experiência mínima (anos) — filtro rígido
          </span>
          <input
            type="number"
            min={0}
            step={0.5}
            placeholder="sem filtro"
            value={minYears}
            onChange={(e) => setMinYears(e.target.value)}
            className="field w-full px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] text-[var(--text-muted)]">
            Gerar análise da IA para os N primeiros
          </span>
          <select
            className="field w-full px-3 py-2 text-sm"
            value={explainTop}
            onChange={(e) => setExplainTop(Number(e.target.value))}
          >
            <option value={0}>Não gerar (mais rápido)</option>
            <option value={1}>Top 1</option>
            <option value={3}>Top 3</option>
            <option value={5}>Top 5</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
          <input
            type="checkbox"
            checked={rerank}
            onChange={(e) => setRerank(e.target.checked)}
            className="h-3.5 w-3.5 accent-[var(--accent)]"
          />
          Reranking com cross-encoder
        </label>
      </div>
    </div>
  );
}

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const jobId = Number(params.id);

  const [tab, setTab] = React.useState<TabKey>("ranking");
  const [showControls, setShowControls] = React.useState(false);
  const [weights, setWeights] = React.useState<[number, number, number]>([1, 1, 0.5]);
  const [rerank, setRerank] = React.useState(true);
  const [topN, setTopN] = React.useState(10);
  const [minYears, setMinYears] = React.useState("");
  const [explainTop, setExplainTop] = React.useState(0);

  // The sliders edit a draft; only "Reexecutar busca" promotes it to `applied`,
  // which is what the ranking request actually depends on. Keeping the request
  // in `useAsync` means the page ranks on arrival without an imperative effect.
  const [applied, setApplied] = React.useState({
    weights: [1, 1, 0.5] as number[],
    rerank: true,
    topN: 10,
    minYears: "",
    explainTop: 0,
  });

  const job = useAsync<Job>(() => api.job(jobId), [jobId]);
  const board = useAsync<Board>(() => api.board(jobId), [jobId]);

  const [rankMs, setRankMs] = React.useState<number | null>(null);
  const rankStartedRef = React.useRef(0);
  const ranking = useAsync<RankResult>(() => {
    rankStartedRef.current = performance.now();
    return api
      .rankJob(jobId, {
        top_n: applied.topN,
        rerank: applied.rerank,
        weights: applied.weights,
        min_experience_years: applied.minYears ? Number(applied.minYears) : null,
        explain_top: applied.explainTop,
      })
      .then((result) => {
        setRankMs(performance.now() - rankStartedRef.current);
        board.reload();
        return result;
      });
  }, [jobId, JSON.stringify(applied)]);

  const runRanking = React.useCallback(() => {
    setApplied({ weights, rerank, topN, minYears, explainTop });
    ranking.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [weights, rerank, topN, minYears, explainTop]);

  if (job.error) {
    return (
      <Panel>
        <ErrorState error={job.error} onRetry={job.reload} />
      </Panel>
    );
  }

  const data = job.data;

  return (
    <>
      <PageHeader
        breadcrumb={
          <nav className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)]">
            <Link href="/jobs" className="inline-flex items-center gap-1 hover:text-[var(--text-secondary)]">
              <ArrowLeft className="h-3 w-3" />
              Vagas
            </Link>
            <ChevronRight className="h-3 w-3" />
            <span className="text-[var(--text-secondary)]">{data?.title ?? "…"}</span>
          </nav>
        }
        title={data?.title ?? "Carregando…"}
        description={
          data
            ? [data.department, data.location, data.work_model, data.employment_type]
                .filter(Boolean)
                .join(" · ")
            : undefined
        }
        actions={
          <>
            <Button icon={Settings2} onClick={() => setShowControls((v) => !v)}>
              Ajustar busca
            </Button>
            <Button variant="primary" icon={Sparkles} onClick={runRanking} loading={ranking.loading}>
              Ranquear candidatos
            </Button>
          </>
        }
      />

      {data ? (
        <div className="mb-5 grid gap-4 lg:grid-cols-3">
          <Panel className="p-4 lg:col-span-2">
            <SectionTitle title="Requisitos extraídos pela IA" icon={FileText} />
            <div className="space-y-3">
              <div>
                <p className="mb-1 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
                  Obrigatórias
                </p>
                <SkillChips skills={data.must_have_skills} tone="accent" max={14} />
              </div>
              <div>
                <p className="mb-1 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
                  Desejáveis
                </p>
                <SkillChips skills={data.nice_to_have_skills} max={12} />
              </div>
              <div>
                <p className="mb-1 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
                  Mapeadas na taxonomia ESCO
                </p>
                <SkillChips skills={data.skills} tone="good" max={16} />
              </div>
            </div>
          </Panel>

          <Panel className="p-4">
            <SectionTitle title="Resumo da vaga" icon={Building2} />
            <dl className="space-y-2 text-xs">
              {[
                ["Senioridade", data.seniority],
                ["Experiência exigida", data.experience_years ? `${data.experience_years} anos` : null],
                ["Posições", `${data.headcount}`],
                ["Responsável", data.owner],
                [
                  "Faixa salarial",
                  data.salary_min && data.salary_max
                    ? `R$ ${data.salary_min.toLocaleString("pt-BR")} – ${data.salary_max.toLocaleString("pt-BR")}`
                    : null,
                ],
                ["Candidaturas", `${data.applications_count ?? 0}`],
              ].map(([label, value]) =>
                value ? (
                  <div key={String(label)} className="flex items-baseline justify-between gap-3">
                    <dt className="text-[var(--text-muted)]">{label}</dt>
                    <dd className="text-right text-[var(--text-secondary)]">{value}</dd>
                  </div>
                ) : null,
              )}
            </dl>
            {data.profile ? (
              <a
                href={api.profilePdfUrl(data.profile_id)}
                target="_blank"
                rel="noreferrer"
                className="btn btn-ghost mt-3 w-full py-2"
              >
                <FileText className="h-4 w-4" />
                Ver descrição em PDF
              </a>
            ) : null}
          </Panel>
        </div>
      ) : (
        <Skeleton className="mb-5 h-40" />
      )}

      {showControls ? (
        <Panel className="mb-5 animate-fade-up p-4">
          <SectionTitle
            title="Parâmetros do motor de busca"
            subtitle="Os pesos controlam a fusão RRF entre as três estratégias de recuperação. Mexer aqui muda o ranking na hora."
            icon={Settings2}
          />
          <RankControls
            weights={weights}
            setWeights={setWeights}
            rerank={rerank}
            setRerank={setRerank}
            topN={topN}
            setTopN={setTopN}
            minYears={minYears}
            setMinYears={setMinYears}
            explainTop={explainTop}
            setExplainTop={setExplainTop}
          />
          <div className="mt-4 flex justify-end">
            <Button variant="primary" icon={RefreshCw} onClick={runRanking} loading={ranking.loading}>
              Reexecutar busca
            </Button>
          </div>
        </Panel>
      ) : null}

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Tabs
          active={tab}
          onChange={setTab}
          tabs={[
            { key: "ranking", label: "Ranking da IA", icon: ListOrdered, count: ranking.data?.results.length },
            { key: "pipeline", label: "Funil", icon: KanbanSquare, count: board.data?.total },
            { key: "detalhes", label: "Documento e PII", icon: FileText },
          ]}
        />
        {tab === "ranking" && rankMs ? (
          <span className="tabular text-[11px] text-[var(--text-muted)]">
            {ranking.data?.results.length ?? 0} candidatos em {formatMs(rankMs)}
            {ranking.data?.trace_id ? (
              <>
                {" · "}
                <Link
                  href={`/observability?trace=${ranking.data.trace_id}`}
                  className="text-[var(--accent-soft)] hover:underline"
                >
                  ver trace
                </Link>
              </>
            ) : null}
          </span>
        ) : null}
      </div>

      {tab === "ranking" ? (
        ranking.loading && !ranking.data ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-36" />
            ))}
          </div>
        ) : ranking.error ? (
          <Panel>
            <ErrorState error={ranking.error} onRetry={runRanking} />
          </Panel>
        ) : !ranking.data || ranking.data.results.length === 0 ? (
          <Panel>
            <EmptyState
              title="Nenhum candidato encontrado"
              description="Adicione currículos ao banco de talentos ou afrouxe os filtros rígidos."
              action={
                <Link href="/candidates" className="btn btn-primary px-3.5 py-2">
                  Ir para talentos
                </Link>
              }
            />
          </Panel>
        ) : (
          <div className="space-y-3">
            {ranking.data.results.map((entry) => (
              <RankedCandidateCard
                key={entry.candidate.id}
                entry={entry}
                jobProfileId={data?.profile_id}
              />
            ))}
          </div>
        )
      ) : null}

      {tab === "pipeline" ? (
        board.loading ? (
          <Skeleton className="h-72" />
        ) : board.error ? (
          <Panel>
            <ErrorState error={board.error} onRetry={board.reload} />
          </Panel>
        ) : board.data ? (
          <KanbanBoard
            columns={board.data.stages}
            onMove={(applicationId: number, stage: Stage) => {
              board.setData((current) => {
                if (!current) return current;
                let moved: Application | null = null;
                const stages = current.stages.map((column) => ({
                  ...column,
                  applications: column.applications.filter((a) => {
                    if (a.id !== applicationId) return true;
                    moved = { ...a, stage };
                    return false;
                  }),
                }));
                return {
                  ...current,
                  stages: stages.map((column) =>
                    column.key === stage && moved
                      ? { ...column, applications: [moved, ...column.applications] }
                      : column,
                  ),
                };
              });
            }}
          />
        ) : null
      ) : null}

      {tab === "detalhes" ? (
        data?.profile ? (
          <Panel className="p-5">
            <SectionTitle
              title="O que a IA realmente leu"
              subtitle="Comparação lado a lado entre o documento original e o texto anonimizado enviado ao modelo."
              icon={FileText}
            />
            <PiiViewer profile={data.profile} />
          </Panel>
        ) : (
          <Skeleton className="h-72" />
        )
      ) : null}
    </>
  );
}
