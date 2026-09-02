"use client";

import React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Award,
  ChevronRight,
  FileText,
  GraduationCap,
  Globe,
  Layers,
  Mail,
  MapPin,
  Phone,
  ScaleIcon,
  Sparkles,
  Trophy,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatDateTime, useAsync } from "@/lib/hooks";
import type { Candidate, FairnessAudit } from "@/lib/types";
import { PageHeader } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  FitBadge,
  Panel,
  SectionTitle,
  SkillChips,
  Skeleton,
  Tabs,
} from "@/components/ui/primitives";
import { PiiViewer } from "@/components/ats/PiiViewer";
import { FairnessReport } from "@/components/ats/FairnessReport";
import { ScoreRing } from "@/components/charts";

type TabKey = "perfil" | "candidaturas" | "pii" | "equidade";

const MATCH_TYPE_LABELS: Record<string, string> = {
  exact: "correspondência exata",
  fuzzy: "similaridade textual",
  embedding: "similaridade semântica",
  unmapped: "não mapeada",
};

function SkillTaxonomy({ candidate }: { candidate: Candidate }) {
  const normalized = candidate.profile?.extracted_profile?.skills_normalized ?? [];
  if (normalized.length === 0) {
    return <p className="text-xs text-[var(--text-muted)]">Nenhuma competência normalizada.</p>;
  }
  const byType = normalized.reduce<Record<string, typeof normalized>>((acc, skill) => {
    (acc[skill.match_type] ??= []).push(skill);
    return acc;
  }, {});

  return (
    <div className="space-y-3">
      {(["exact", "fuzzy", "embedding", "unmapped"] as const).map((type) =>
        byType[type]?.length ? (
          <div key={type}>
            <p className="mb-1.5 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
              {MATCH_TYPE_LABELS[type]} · {byType[type].length}
            </p>
            <ul className="flex flex-wrap gap-1.5">
              {byType[type].map((skill, i) => (
                <li key={`${skill.original_term}-${i}`}>
                  <Badge
                    tone={type === "unmapped" ? "warning" : type === "exact" ? "good" : "neutral"}
                    title={
                      skill.preferred_label
                        ? `"${skill.original_term}" → ${skill.preferred_label} (${skill.score.toFixed(0)})`
                        : `"${skill.original_term}" não encontrada na taxonomia ESCO`
                    }
                  >
                    {skill.preferred_label ?? skill.original_term}
                  </Badge>
                </li>
              ))}
            </ul>
          </div>
        ) : null,
      )}
    </div>
  );
}

function FairnessTab({ candidate }: { candidate: Candidate }) {
  // Default to the candidate's first application; the select overrides it.
  const [chosenJobId, setChosenJobId] = React.useState<string>("");
  const jobId = chosenJobId || String(candidate.applications?.[0]?.job_id ?? "");
  const setJobId = setChosenJobId;
  const [audit, setAudit] = React.useState<FairnessAudit | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const jobs = useAsync(() => api.jobs());

  const run = async () => {
    const job = jobs.data?.find((j) => j.id === Number(jobId));
    if (!job) return;
    setBusy(true);
    setError(null);
    try {
      setAudit(await api.auditBias(candidate.profile_id, job.profile_id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao rodar a auditoria.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <Panel className="p-4">
        <SectionTitle
          title="Auditoria contrafactual de viés"
          subtitle="Clonamos o currículo, trocamos um marcador demográfico por vez e medimos quanto o score se move."
          icon={ScaleIcon}
        />
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-[240px] flex-1">
            <span className="mb-1 block text-[11px] text-[var(--text-muted)]">Auditar contra a vaga</span>
            <select
              className="field w-full px-3 py-2 text-sm"
              value={jobId}
              onChange={(e) => setJobId(e.target.value)}
            >
              <option value="">Selecione uma vaga…</option>
              {(jobs.data ?? []).map((j) => (
                <option key={j.id} value={j.id}>
                  {j.title}
                </option>
              ))}
            </select>
          </label>
          <Button variant="primary" icon={ScaleIcon} onClick={run} loading={busy} disabled={!jobId}>
            Rodar auditoria
          </Button>
        </div>
        {error ? <p className="mt-3 text-xs text-[var(--status-critical)]">{error}</p> : null}
      </Panel>

      {busy ? <Skeleton className="h-64" /> : audit ? <FairnessReport audit={audit} /> : null}
    </div>
  );
}

export default function CandidateDetailPage() {
  const params = useParams<{ id: string }>();
  const candidateId = Number(params.id);
  const [tab, setTab] = React.useState<TabKey>("perfil");
  const candidate = useAsync<Candidate>(() => api.candidate(candidateId), [candidateId]);

  if (candidate.error) {
    return (
      <Panel>
        <ErrorState error={candidate.error} onRetry={candidate.reload} />
      </Panel>
    );
  }

  const data = candidate.data;
  const extracted = data?.profile?.extracted_profile;

  return (
    <>
      <PageHeader
        breadcrumb={
          <nav className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)]">
            <Link
              href="/candidates"
              className="inline-flex items-center gap-1 hover:text-[var(--text-secondary)]"
            >
              <ArrowLeft className="h-3 w-3" />
              Talentos
            </Link>
            <ChevronRight className="h-3 w-3" />
            <span className="text-[var(--text-secondary)]">{data?.display_name ?? "…"}</span>
          </nav>
        }
        title={data?.display_name ?? "Carregando…"}
        description={data?.headline ?? undefined}
        actions={
          data?.profile ? (
            <a
              href={api.profilePdfUrl(data.profile_id)}
              target="_blank"
              rel="noreferrer"
              className="btn btn-ghost px-3.5 py-2"
            >
              <FileText className="h-4 w-4" />
              Ver currículo
            </a>
          ) : null
        }
      />

      {!data ? (
        <Skeleton className="h-72" />
      ) : (
        <>
          <div className="mb-5 grid gap-4 lg:grid-cols-4">
            <Panel className="p-4 lg:col-span-3">
              <div className="flex flex-wrap items-center gap-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-[color-mix(in_srgb,var(--accent)_45%,transparent)] to-[color-mix(in_srgb,var(--accent-2)_45%,transparent)] text-base font-semibold text-white">
                  {data.initials}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap gap-1.5">
                    {data.seniority ? <Badge tone="accent">{data.seniority}</Badge> : null}
                    <Badge>{data.experience_years ?? 0} anos de experiência</Badge>
                    {data.source ? <Badge>{data.source}</Badge> : null}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--text-muted)]">
                    {data.email ? (
                      <span className="inline-flex items-center gap-1">
                        <Mail className="h-3 w-3" />
                        {data.email}
                      </span>
                    ) : null}
                    {data.phone ? (
                      <span className="inline-flex items-center gap-1">
                        <Phone className="h-3 w-3" />
                        {data.phone}
                      </span>
                    ) : null}
                    {data.location ? (
                      <span className="inline-flex items-center gap-1">
                        <MapPin className="h-3 w-3" />
                        {data.location}
                      </span>
                    ) : null}
                  </div>
                </div>
              </div>
            </Panel>

            <Panel className="flex flex-col items-center justify-center gap-2 p-4">
              {data.applications?.length ? (
                <>
                  <ScoreRing value={data.applications[0].ai_score ?? 0} size={68} />
                  <p className="text-center text-[11px] text-[var(--text-muted)]">
                    melhor score em<br />
                    <span className="text-[var(--text-secondary)]">
                      {data.applications[0].job?.title ?? "uma vaga"}
                    </span>
                  </p>
                </>
              ) : (
                <p className="text-center text-[11px] text-[var(--text-muted)]">
                  Ainda sem candidatura ranqueada
                </p>
              )}
            </Panel>
          </div>

          <div className="mb-4">
            <Tabs
              active={tab}
              onChange={setTab}
              tabs={[
                { key: "perfil", label: "Perfil extraído", icon: Sparkles },
                { key: "candidaturas", label: "Candidaturas", icon: Layers, count: data.applications?.length },
                { key: "pii", label: "PII e documento", icon: FileText },
                { key: "equidade", label: "Equidade", icon: ScaleIcon },
              ]}
            />
          </div>

          {tab === "perfil" ? (
            <div className="grid gap-4 lg:grid-cols-3">
              <Panel className="p-5 lg:col-span-2">
                <SectionTitle title="Trajetória consolidada pela IA" icon={Sparkles} />
                <p className="whitespace-pre-line text-xs leading-relaxed text-[var(--text-secondary)]">
                  {extracted?.narrative_experience ?? "—"}
                </p>

                {extracted?.highlights?.length ? (
                  <div className="mt-5">
                    <SectionTitle title="Destaques" icon={Trophy} />
                    <ul className="space-y-2">
                      {extracted.highlights.map((h, i) => (
                        <li key={i} className="flex gap-2 text-xs leading-relaxed text-[var(--text-secondary)]">
                          <span
                            aria-hidden
                            className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-[var(--accent-soft)]"
                          />
                          {h}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </Panel>

              <div className="space-y-4">
                <Panel className="p-5">
                  <SectionTitle
                    title="Competências na taxonomia ESCO"
                    subtitle="Como cada termo do currículo foi mapeado"
                    icon={Layers}
                  />
                  <SkillTaxonomy candidate={data} />
                </Panel>

                {extracted?.education?.length ? (
                  <Panel className="p-5">
                    <SectionTitle title="Formação" icon={GraduationCap} />
                    <ul className="space-y-2">
                      {extracted.education.map((e, i) => (
                        <li key={i} className="text-xs">
                          <p className="text-[var(--text-secondary)]">
                            {e.degree} em {e.field}
                          </p>
                          <p className="text-[11px] text-[var(--text-muted)]">{e.year ?? "—"}</p>
                        </li>
                      ))}
                    </ul>
                  </Panel>
                ) : null}

                {data.certifications.length ? (
                  <Panel className="p-5">
                    <SectionTitle title="Certificações" icon={Award} />
                    <SkillChips skills={data.certifications} max={20} />
                  </Panel>
                ) : null}

                {data.languages.length ? (
                  <Panel className="p-5">
                    <SectionTitle title="Idiomas" icon={Globe} />
                    <SkillChips skills={data.languages} max={10} />
                  </Panel>
                ) : null}
              </div>
            </div>
          ) : null}

          {tab === "candidaturas" ? (
            data.applications?.length ? (
              <div className="space-y-3">
                {data.applications.map((application) => (
                  <Panel key={application.id} hover className="p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <Link
                          href={`/jobs/${application.job_id}`}
                          className="text-sm font-medium text-[var(--text-primary)] hover:text-[var(--accent-soft)]"
                        >
                          {application.job?.title ?? `Vaga ${application.job_id}`}
                        </Link>
                        <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">
                          Etapa: {application.stage_label} · atualizado em{" "}
                          {formatDateTime(application.updated_at)}
                        </p>
                      </div>
                      <div className="flex items-center gap-3">
                        <FitBadge fit={application.ai_fit} />
                        {application.ai_score !== null ? (
                          <ScoreRing value={application.ai_score} size={48} />
                        ) : null}
                      </div>
                    </div>
                    {application.ai_summary ? (
                      <p className="mt-3 text-xs leading-relaxed text-[var(--text-secondary)]">
                        {application.ai_summary}
                      </p>
                    ) : null}
                    {application.ai_matched_skills.length ? (
                      <div className="mt-3">
                        <SkillChips skills={application.ai_matched_skills} tone="good" max={8} />
                      </div>
                    ) : null}
                  </Panel>
                ))}
              </div>
            ) : (
              <Panel>
                <EmptyState
                  title="Sem candidaturas"
                  description="Ranqueie uma vaga para que este candidato entre automaticamente no funil."
                />
              </Panel>
            )
          ) : null}

          {tab === "pii" ? (
            data.profile ? (
              <Panel className="p-5">
                <SectionTitle
                  title="O que a IA realmente leu"
                  subtitle="Comparação lado a lado entre o currículo original e o texto anonimizado."
                  icon={FileText}
                />
                <PiiViewer profile={data.profile} />
              </Panel>
            ) : (
              <Skeleton className="h-72" />
            )
          ) : null}

          {tab === "equidade" ? <FairnessTab candidate={data} /> : null}
        </>
      )}
    </>
  );
}
