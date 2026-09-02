"use client";

import React from "react";
import Link from "next/link";
import {
  ArrowRight,
  Award,
  Braces,
  ChevronDown,
  Clock,
  FileSearch,
  Layers,
  Quote,
  ShieldAlert,
  Sparkles,
  Target,
} from "lucide-react";
import type { MatchExplanation, RankedCandidate } from "@/lib/types";
import { api } from "@/lib/api";
import { Badge, Button, FitBadge, Panel, SkillChips, cn } from "@/components/ui/primitives";
import { ScoreRing, formatMs } from "@/components/charts";

const STRATEGY_LABELS: Record<string, string> = {
  skills: "Vetor de competências",
  narrative: "Vetor de trajetória",
  lexical: "Busca lexical (esparsa)",
};

function Avatar({ initials, rank }: { initials: string; rank?: number }) {
  return (
    <div className="relative shrink-0">
      <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-[color-mix(in_srgb,var(--accent)_45%,transparent)] to-[color-mix(in_srgb,var(--accent-2)_45%,transparent)] text-sm font-semibold text-white">
        {initials}
      </div>
      {rank ? (
        <span className="tabular absolute -left-1.5 -top-1.5 flex h-5 w-5 items-center justify-center rounded-full border border-white/15 bg-[var(--surface-2)] text-[10px] font-semibold text-[var(--text-primary)]">
          {rank}
        </span>
      ) : null}
    </div>
  );
}

/** Why this person surfaced: which retrieval strategies found them, and at what rank. */
function RetrievalTrace({ entry }: { entry: RankedCandidate }) {
  const strategies = Object.entries(entry.strategy_ranks);
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
      <p className="mb-2 flex items-center gap-1.5 text-[11px] font-medium text-[var(--text-secondary)]">
        <Layers className="h-3 w-3" />
        Como este candidato foi encontrado
      </p>
      {strategies.length === 0 ? (
        <p className="text-[11px] text-[var(--text-muted)]">Nenhuma estratégia registrada.</p>
      ) : (
        <ul className="space-y-1.5">
          {strategies.map(([key, rank]) => (
            <li key={key} className="flex items-center justify-between gap-3 text-[11px]">
              <span className="text-[var(--text-muted)]">{STRATEGY_LABELS[key] ?? key}</span>
              <span className="tabular text-[var(--text-secondary)]">
                #{rank}
                {entry.strategy_scores?.[key as keyof typeof entry.strategy_scores] !== undefined ? (
                  <span className="ml-1.5 text-[var(--text-muted)]">
                    ({entry.strategy_scores[key as keyof typeof entry.strategy_scores]?.toFixed(3)})
                  </span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-2.5 flex flex-wrap items-center gap-2 border-t border-white/6 pt-2.5 text-[11px] text-[var(--text-muted)]">
        <span>
          RRF: <span className="tabular text-[var(--text-secondary)]">#{entry.rrf_rank ?? "—"}</span>
        </span>
        <ArrowRight className="h-3 w-3" />
        <span>
          Após reranking:{" "}
          <span className="tabular text-[var(--text-secondary)]">#{entry.rank}</span>
        </span>
        {entry.rrf_rank && entry.rrf_rank !== entry.rank ? (
          <Badge tone="accent">
            {entry.rrf_rank > entry.rank ? `subiu ${entry.rrf_rank - entry.rank}` : `desceu ${entry.rank - entry.rrf_rank}`}
          </Badge>
        ) : null}
      </div>
    </div>
  );
}

export function ExplanationPanel({ explanation }: { explanation: MatchExplanation }) {
  const check = explanation.hallucination_check;
  const allVerified = check.total > 0 && check.verified === check.total;

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-white/8 bg-white/[0.02] p-3.5">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <FitBadge fit={explanation.fit} />
          <Badge tone="neutral" icon={Sparkles}>
            confiança {(explanation.confidence * 100).toFixed(0)}%
          </Badge>
          <Badge tone="neutral" icon={Braces} title={explanation.generated_by}>
            {explanation.generated_by.split("/").pop()}
          </Badge>
        </div>
        <p className="text-sm leading-relaxed text-[var(--text-secondary)]">{explanation.explanation}</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">
            Pontos fortes
          </p>
          <ul className="space-y-1.5">
            {explanation.strengths.map((s) => (
              <li key={s} className="flex gap-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[var(--status-good)]" />
                {s}
              </li>
            ))}
            {explanation.strengths.length === 0 ? (
              <li className="text-xs text-[var(--text-muted)]">—</li>
            ) : null}
          </ul>
        </div>
        <div>
          <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">
            Lacunas
          </p>
          <ul className="space-y-1.5">
            {explanation.gaps.map((g) => (
              <li key={g} className="flex gap-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[var(--status-warning)]" />
                {g}
              </li>
            ))}
            {explanation.gaps.length === 0 ? (
              <li className="text-xs text-[var(--text-muted)]">—</li>
            ) : null}
          </ul>
        </div>
      </div>

      <div>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">
            <Quote className="h-3 w-3" />
            Evidências citadas
          </p>
          <Badge
            tone={allVerified ? "good" : check.verified > 0 ? "warning" : "critical"}
            icon={allVerified ? Award : ShieldAlert}
          >
            {check.verified}/{check.total} verificadas no currículo
          </Badge>
        </div>
        <ul className="space-y-2">
          {explanation.citations.map((c, i) => (
            <li
              key={i}
              className={cn(
                "rounded-lg border-l-2 bg-white/[0.02] px-3 py-2 text-xs italic leading-relaxed",
                c.verified
                  ? "border-l-[var(--status-good)] text-[var(--text-secondary)]"
                  : "border-l-[var(--status-critical)] text-[var(--text-muted)]",
              )}
            >
              “{c.text}”
              {!c.verified ? (
                <span className="ml-2 inline-flex items-center gap-1 not-italic text-[10px] text-[var(--status-critical)]">
                  <ShieldAlert className="h-3 w-3" />
                  não encontrada literalmente — possível alucinação
                </span>
              ) : null}
            </li>
          ))}
          {explanation.citations.length === 0 ? (
            <li className="text-xs text-[var(--text-muted)]">Nenhuma citação retornada.</li>
          ) : null}
        </ul>
      </div>

      {explanation.interview_questions.length ? (
        <div>
          <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-[var(--text-muted)]">
            <FileSearch className="h-3 w-3" />
            Perguntas sugeridas para a entrevista
          </p>
          <ol className="space-y-1.5">
            {explanation.interview_questions.map((q, i) => (
              <li key={i} className="flex gap-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                <span className="tabular text-[var(--text-muted)]">{i + 1}.</span>
                {q}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </div>
  );
}

export function RankedCandidateCard({
  entry,
  jobProfileId,
  onOpenCandidate,
}: {
  entry: RankedCandidate;
  jobProfileId?: number;
  onOpenCandidate?: (entry: RankedCandidate) => void;
}) {
  const [expanded, setExpanded] = React.useState(false);
  const [explanation, setExplanation] = React.useState<MatchExplanation | null>(
    entry.explanation ?? null,
  );
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [elapsed, setElapsed] = React.useState<number | null>(null);

  const signals = entry.signals;
  const coverage = Math.round((signals?.skill_coverage ?? 0) * 100);

  const explain = async () => {
    if (explanation || !jobProfileId) {
      setExpanded((v) => !v);
      return;
    }
    setExpanded(true);
    setLoading(true);
    setError(null);
    const started = performance.now();
    try {
      const result = await api.explainPair(entry.profile_id, jobProfileId);
      setExplanation(result);
      setElapsed(performance.now() - started);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao gerar a análise.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Panel hover data-testid="ranked-candidate" className="animate-fade-up overflow-hidden">
      <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-start">
        <Avatar initials={entry.candidate.initials} rank={entry.rank} />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <button
                onClick={() => onOpenCandidate?.(entry)}
                className="truncate text-sm font-semibold text-[var(--text-primary)] transition-colors hover:text-[var(--accent-soft)]"
              >
                {entry.candidate.display_name}
              </button>
              <p className="mt-0.5 truncate text-xs text-[var(--text-muted)]">
                {entry.candidate.headline ?? "—"}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <FitBadge fit={entry.fit} />
              <ScoreRing value={entry.score_normalized} label="score" />
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-[var(--text-muted)]">
            <Badge>{entry.candidate.seniority ?? "—"}</Badge>
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3 w-3" />
              {entry.candidate.experience_years ?? 0} anos
            </span>
            <span className="inline-flex items-center gap-1">
              <Target className="h-3 w-3" />
              {coverage}% das competências da vaga
            </span>
            {signals?.experience_delta_years !== undefined ? (
              <span
                className={cn(
                  signals.experience_delta_years >= 0
                    ? "text-[var(--status-good)]"
                    : "text-[var(--status-warning)]",
                )}
              >
                {signals.experience_delta_years >= 0 ? "+" : ""}
                {signals.experience_delta_years} ano(s) vs. requisito
              </span>
            ) : null}
            {entry.stage ? <Badge tone="accent">{entry.stage}</Badge> : null}
          </div>

          <div className="mt-3 space-y-2">
            <div>
              <p className="mb-1 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
                Competências em comum
              </p>
              <SkillChips
                skills={signals?.matched_skills ?? []}
                tone="good"
                max={8}
                emptyLabel="Nenhuma competência da vaga foi encontrada."
              />
            </div>
            {signals?.missing_skills?.length ? (
              <div>
                <p className="mb-1 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
                  Lacunas
                </p>
                <SkillChips skills={signals.missing_skills} tone="warning" max={6} />
              </div>
            ) : null}
          </div>

          <div className="mt-3.5 flex flex-wrap items-center gap-2">
            <Button
              onClick={explain}
              variant="ghost"
              icon={expanded ? ChevronDown : Sparkles}
              loading={loading}
              className={cn(expanded && "text-[var(--text-primary)]")}
            >
              {explanation ? (expanded ? "Ocultar análise" : "Ver análise da IA") : "Analisar com IA"}
            </Button>
            <Link href={`/candidates/${entry.candidate.id}`} className="btn btn-ghost px-3.5 py-2">
              Perfil completo
            </Link>
            {elapsed ? (
              <span className="tabular text-[10px] text-[var(--text-muted)]">
                análise em {formatMs(elapsed)}
              </span>
            ) : null}
          </div>
        </div>
      </div>

      {expanded ? (
        <div className="animate-fade-up space-y-4 border-t border-white/8 bg-black/20 p-4">
          <RetrievalTrace entry={entry} />
          {loading ? (
            <div className="space-y-2">
              <div className="skeleton h-3 w-3/4" />
              <div className="skeleton h-3 w-full" />
              <div className="skeleton h-3 w-5/6" />
            </div>
          ) : error ? (
            <p className="text-xs text-[var(--status-critical)]">{error}</p>
          ) : explanation ? (
            <ExplanationPanel explanation={explanation} />
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
}
