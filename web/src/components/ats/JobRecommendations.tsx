"use client";

import React from "react";
import Link from "next/link";
import { ArrowLeftRight, Briefcase, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import type { Candidate, Job, MatchedJob } from "@/lib/types";
import { Badge, EmptyState, ErrorState, Panel, SectionTitle, Skeleton } from "@/components/ui/primitives";
import { ScoreRing } from "@/components/charts";

/**
 * The engine is bidirectional: the same three vectors that rank candidates for a
 * job also rank jobs for a candidate. This panel runs that reverse query — which
 * openings does this person fit? — against the `jobs` collection.
 */
export function JobRecommendations({ candidate }: { candidate: Candidate }) {
  const matches = useAsync<MatchedJob[]>(
    () => api.matchJobsForCandidate(candidate.profile_id, 5),
    [candidate.profile_id],
  );
  const jobs = useAsync<Job[]>(() => api.jobs());

  const jobByProfile = React.useMemo(() => {
    const map = new Map<number, Job>();
    for (const job of jobs.data ?? []) map.set(job.profile_id, job);
    return map;
  }, [jobs.data]);

  const appliedTo = new Set((candidate.applications ?? []).map((a) => a.job_id));

  return (
    <Panel className="p-5">
      <SectionTitle
        title="Vagas recomendadas para este candidato"
        subtitle="A mesma busca híbrida, invertida: o currículo vira a consulta e as vagas são o índice."
        icon={ArrowLeftRight}
      />

      {matches.loading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-16" />
          ))}
        </div>
      ) : matches.error ? (
        <ErrorState error={matches.error} onRetry={matches.reload} />
      ) : !matches.data?.length ? (
        <EmptyState
          icon={Briefcase}
          title="Nenhuma vaga compatível encontrada"
          description="Publique vagas para que o motor tenha o que recomendar."
        />
      ) : (
        <ul className="divide-y divide-white/6">
          {matches.data.map((match) => {
            const job = jobByProfile.get(match.id);
            const already = job ? appliedTo.has(job.id) : false;
            return (
              <li key={match.id} className="flex items-center gap-3 py-2.5">
                <span className="tabular w-5 shrink-0 text-center text-xs text-[var(--text-muted)]">
                  {match.rank}
                </span>
                <div className="min-w-0 flex-1">
                  {job ? (
                    <Link
                      href={`/jobs/${job.id}`}
                      className="block truncate text-xs font-medium text-[var(--text-primary)] hover:text-[var(--accent-soft)]"
                    >
                      {job.title}
                    </Link>
                  ) : (
                    <span className="block truncate text-xs text-[var(--text-secondary)]">
                      {match.profile.extracted_profile?.role_title ?? `Vaga ${match.id}`}
                    </span>
                  )}
                  <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-[var(--text-muted)]">
                    {job
                      ? [job.seniority, job.location, job.work_model].filter(Boolean).join(" · ")
                      : "—"}
                    {already ? <Badge tone="accent">já candidatado</Badge> : null}
                  </p>
                </div>
                <ScoreRing value={match.score_normalized} size={40} />
              </li>
            );
          })}
        </ul>
      )}

      <p className="mt-3 flex items-start gap-1.5 border-t border-white/8 pt-3 text-[11px] leading-relaxed text-[var(--text-muted)]">
        <Sparkles className="mt-0.5 h-3 w-3 shrink-0" />
        O score usa a mesma escala calibrada do ranqueamento por vaga: 50 é o limiar em que o
        reranker passa a considerar o par relevante.
      </p>
    </Panel>
  );
}
