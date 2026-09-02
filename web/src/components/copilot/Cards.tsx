"use client";

import React from "react";
import Link from "next/link";
import { Briefcase, KanbanSquare, ScaleIcon, Sparkles, Users } from "lucide-react";
import type { CopilotCard } from "@/lib/types";
import { Badge, FitBadge, Panel, SectionTitle, SkillChips } from "@/components/ui/primitives";
import { FunnelChart, ScoreRing } from "@/components/charts";
import { ExplanationPanel } from "@/components/ats/CandidateCard";
import { FairnessReport } from "@/components/ats/FairnessReport";

/**
 * Every copilot tool returns a structured card alongside its text digest, so the
 * conversation produces real interface instead of a wall of prose.
 */
export function CopilotCardView({ card }: { card: CopilotCard }) {
  if (card.type === "ranking") {
    return (
      <Panel className="p-4">
        <SectionTitle
          title={`Ranking — ${card.job.title}`}
          subtitle={`${card.results.length} candidatos ordenados por busca híbrida + reranking`}
          icon={Sparkles}
          action={
            <Link
              href={`/jobs/${card.job.id}`}
              className="text-[11px] text-[var(--accent-soft)] hover:underline"
            >
              Abrir vaga
            </Link>
          }
        />
        <ol className="divide-y divide-white/6">
          {card.results.map((entry) => (
            <li key={entry.candidate.id} className="flex items-center gap-3 py-2.5">
              <span className="tabular w-5 shrink-0 text-center text-xs text-[var(--text-muted)]">
                {entry.rank}
              </span>
              <div className="min-w-0 flex-1">
                <Link
                  href={`/candidates/${entry.candidate.id}`}
                  className="block truncate text-xs font-medium text-[var(--text-primary)] hover:text-[var(--accent-soft)]"
                >
                  {entry.candidate.display_name}
                </Link>
                <p className="mt-0.5 truncate text-[11px] text-[var(--text-muted)]">
                  {entry.candidate.headline ?? "—"}
                </p>
                <div className="mt-1.5">
                  <SkillChips skills={entry.signals?.matched_skills ?? []} tone="good" max={5} />
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <FitBadge fit={entry.fit} />
                <ScoreRing value={entry.score_normalized} size={40} />
              </div>
            </li>
          ))}
        </ol>
      </Panel>
    );
  }

  if (card.type === "candidates") {
    return (
      <Panel className="p-4">
        <SectionTitle title={`Busca: “${card.query}”`} icon={Users} />
        <ul className="divide-y divide-white/6">
          {card.candidates.map((candidate) => (
            <li key={candidate.id} className="flex items-center gap-3 py-2.5">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/8 text-[10px] font-semibold">
                {candidate.initials}
              </span>
              <div className="min-w-0 flex-1">
                <Link
                  href={`/candidates/${candidate.id}`}
                  className="block truncate text-xs font-medium hover:text-[var(--accent-soft)]"
                >
                  {candidate.display_name}
                </Link>
                <p className="truncate text-[11px] text-[var(--text-muted)]">{candidate.headline ?? "—"}</p>
              </div>
              <Badge tone="accent">
                <span className="tabular">{candidate.score.toFixed(0)}</span>
              </Badge>
            </li>
          ))}
        </ul>
      </Panel>
    );
  }

  if (card.type === "jobs") {
    return (
      <Panel className="p-4">
        <SectionTitle title="Vagas no ATS" icon={Briefcase} />
        <ul className="divide-y divide-white/6">
          {card.jobs.map((job) => (
            <li key={job.id} className="flex items-center justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <Link
                  href={`/jobs/${job.id}`}
                  className="block truncate text-xs font-medium hover:text-[var(--accent-soft)]"
                >
                  {job.title}
                </Link>
                <p className="truncate text-[11px] text-[var(--text-muted)]">
                  {[job.seniority, job.location, job.work_model].filter(Boolean).join(" · ")}
                </p>
              </div>
              <Badge>{job.applications_count ?? 0} candidatura(s)</Badge>
            </li>
          ))}
        </ul>
      </Panel>
    );
  }

  if (card.type === "candidate") {
    const candidate = card.candidate;
    return (
      <Panel className="p-4">
        <SectionTitle title={candidate.display_name} subtitle={candidate.headline ?? undefined} icon={Users} />
        <div className="mb-3 flex flex-wrap gap-1.5">
          {candidate.seniority ? <Badge tone="accent">{candidate.seniority}</Badge> : null}
          <Badge>{candidate.experience_years ?? 0} anos</Badge>
        </div>
        <SkillChips skills={candidate.skills} max={14} />
        <Link
          href={`/candidates/${candidate.id}`}
          className="btn btn-ghost mt-3 w-full py-2"
        >
          Abrir perfil completo
        </Link>
      </Panel>
    );
  }

  if (card.type === "explanation") {
    return (
      <Panel className="p-4">
        <SectionTitle
          title={`${card.candidate.display_name} × ${card.job.title}`}
          subtitle={card.explanation.summary}
          icon={Sparkles}
        />
        <ExplanationPanel explanation={card.explanation} />
      </Panel>
    );
  }

  if (card.type === "overview") {
    const overview = card.overview;
    return (
      <Panel className="p-4">
        <SectionTitle title="Resumo do pipeline" icon={KanbanSquare} />
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ["Vagas abertas", overview.jobs_open],
            ["Candidatos", overview.candidates_total],
            ["Candidaturas", overview.applications_total],
            ["Score médio", overview.avg_ai_score],
          ].map(([label, value]) => (
            <div key={String(label)}>
              <p className="text-[10px] uppercase tracking-wide text-[var(--text-muted)]">{label}</p>
              <p className="tabular mt-0.5 text-lg font-semibold">{value}</p>
            </div>
          ))}
        </div>
        <FunnelChart
          stages={overview.by_stage
            .filter((s) => s.stage !== "rejected")
            .map((s) => ({ key: s.stage, label: s.label, count: s.count }))}
        />
      </Panel>
    );
  }

  if (card.type === "application") {
    const application = card.application;
    return (
      <Panel className="flex flex-wrap items-center justify-between gap-3 p-4">
        <div>
          <p className="text-xs font-medium text-[var(--text-primary)]">
            {application.candidate?.display_name ?? `Candidatura ${application.id}`}
          </p>
          <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">
            Nova etapa: {application.stage_label}
          </p>
        </div>
        <Badge tone="accent">{application.stage_label}</Badge>
      </Panel>
    );
  }

  if (card.type === "fairness") {
    return (
      <div>
        <div className="mb-2 flex items-center gap-2 text-xs text-[var(--text-secondary)]">
          <ScaleIcon className="h-3.5 w-3.5" />
          {card.candidate.display_name} × {card.job.title}
        </div>
        <FairnessReport audit={card.audit} />
      </div>
    );
  }

  return null;
}
