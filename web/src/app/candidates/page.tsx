"use client";

import React from "react";
import Link from "next/link";
import { Award, Globe, Plus, Search, Upload, Users } from "lucide-react";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import type { Candidate, Job } from "@/lib/types";
import { PageHeader } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Modal,
  Panel,
  SkillChips,
  Skeleton,
} from "@/components/ui/primitives";

function CandidateCard({ candidate }: { candidate: Candidate }) {
  return (
    <Panel hover className="animate-fade-up flex flex-col p-4">
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-[color-mix(in_srgb,var(--accent)_45%,transparent)] to-[color-mix(in_srgb,var(--accent-2)_45%,transparent)] text-xs font-semibold text-white">
          {candidate.initials}
        </div>
        <div className="min-w-0 flex-1">
          <Link
            href={`/candidates/${candidate.id}`}
            className="block truncate text-sm font-semibold text-[var(--text-primary)] transition-colors hover:text-[var(--accent-soft)]"
          >
            {candidate.display_name}
          </Link>
          <p className="mt-0.5 line-clamp-2 text-[11px] leading-relaxed text-[var(--text-muted)]">
            {candidate.headline ?? "—"}
          </p>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {candidate.seniority ? <Badge tone="accent">{candidate.seniority}</Badge> : null}
        <Badge>{candidate.experience_years ?? 0} anos</Badge>
        {candidate.source ? <Badge>{candidate.source}</Badge> : null}
      </div>

      <div className="mt-3">
        <SkillChips skills={candidate.skills} max={7} />
      </div>

      {candidate.certifications.length || candidate.languages.length ? (
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--text-muted)]">
          {candidate.certifications.length ? (
            <span className="inline-flex items-center gap-1">
              <Award className="h-3 w-3" />
              {candidate.certifications.length} certificação(ões)
            </span>
          ) : null}
          {candidate.languages.length ? (
            <span className="inline-flex items-center gap-1">
              <Globe className="h-3 w-3" />
              {candidate.languages.join(", ")}
            </span>
          ) : null}
        </div>
      ) : null}

      <Link href={`/candidates/${candidate.id}`} className="btn btn-ghost mt-auto w-full py-2 pt-2">
        Ver perfil
      </Link>
    </Panel>
  );
}

function NewCandidateModal({
  open,
  onClose,
  onCreated,
  jobs,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
  jobs: Job[];
}) {
  const [text, setText] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);
  const [source, setSource] = React.useState("LinkedIn");
  const [jobId, setJobId] = React.useState<string>("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [stage, setStage] = React.useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setStage("Anonimizando PII e extraindo o perfil com IA…");
    try {
      const form = new FormData();
      if (file) form.append("file", file);
      else form.append("text_content", text);
      form.append(
        "meta",
        JSON.stringify({ source, job_id: jobId ? Number(jobId) : undefined }),
      );
      await api.createCandidate(form);
      onCreated();
      onClose();
      setText("");
      setFile(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao cadastrar o candidato.");
    } finally {
      setBusy(false);
      setStage(null);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Adicionar ao banco de talentos"
      subtitle="O currículo é anonimizado antes de qualquer chamada a um modelo externo. Nome, e-mail, telefone e CPF ficam apenas no banco."
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-[11px] text-[var(--text-muted)]">Origem</span>
            <select
              className="field w-full px-3 py-2 text-sm"
              value={source}
              onChange={(e) => setSource(e.target.value)}
            >
              <option>LinkedIn</option>
              <option>Indicação</option>
              <option>Site de carreiras</option>
              <option>Banco de talentos</option>
              <option>Upload manual</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] text-[var(--text-muted)]">
              Candidatar a uma vaga (opcional)
            </span>
            <select
              className="field w-full px-3 py-2 text-sm"
              value={jobId}
              onChange={(e) => setJobId(e.target.value)}
            >
              <option value="">Somente banco de talentos</option>
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.title}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="block">
          <span className="mb-1 block text-[11px] text-[var(--text-muted)]">Currículo em texto</span>
          <textarea
            className="field min-h-[200px] w-full px-3 py-2 font-mono text-xs"
            placeholder="Cole o currículo completo aqui…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={!!file}
          />
        </label>

        <label className="block">
          <span className="mb-1 block text-[11px] text-[var(--text-muted)]">…ou envie um PDF</span>
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="field w-full px-3 py-2 text-xs file:mr-3 file:rounded file:border-0 file:bg-white/8 file:px-2 file:py-1 file:text-xs file:text-[var(--text-secondary)]"
          />
        </label>

        {stage ? <p className="text-xs text-[var(--accent-soft)]">{stage}</p> : null}
        {error ? <p className="text-xs text-[var(--status-critical)]">{error}</p> : null}

        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            icon={Upload}
            onClick={submit}
            loading={busy}
            disabled={!file && text.trim().length < 40}
          >
            Processar currículo
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export default function CandidatesPage() {
  const [query, setQuery] = React.useState("");
  const [modal, setModal] = React.useState(false);
  const candidates = useAsync<Candidate[]>(() => api.candidates());
  const jobs = useAsync<Job[]>(() => api.jobs("open"));

  const term = query.trim().toLowerCase();
  const filtered = (candidates.data ?? []).filter((c) => {
    if (!term) return true;
    return (
      c.display_name.toLowerCase().includes(term) ||
      (c.headline ?? "").toLowerCase().includes(term) ||
      c.skills.some((s) => s.toLowerCase().includes(term))
    );
  });

  return (
    <>
      <PageHeader
        title="Banco de talentos"
        description="Todo currículo é anonimizado, estruturado por IA e indexado em três representações vetoriais."
        actions={
          <Button variant="primary" icon={Plus} onClick={() => setModal(true)}>
            Adicionar candidato
          </Button>
        }
      />

      <div className="mb-5 flex items-center gap-2">
        <div className="relative flex-1 sm:max-w-md">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            className="field w-full py-2 pl-9 pr-3 text-sm"
            placeholder="Buscar por nome, cargo ou competência…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <span className="tabular text-[11px] text-[var(--text-muted)]">
          {filtered.length} de {candidates.data?.length ?? 0}
        </span>
      </div>

      {candidates.loading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-56" />
          ))}
        </div>
      ) : candidates.error ? (
        <Panel>
          <ErrorState error={candidates.error} onRetry={candidates.reload} />
        </Panel>
      ) : filtered.length === 0 ? (
        <Panel>
          <EmptyState
            icon={Users}
            title={term ? "Nenhum candidato corresponde à busca" : "Banco de talentos vazio"}
            description={
              term
                ? "Tente outro termo ou limpe o filtro."
                : "Adicione currículos para que o motor de busca tenha o que ranquear."
            }
            action={
              term ? (
                <Button onClick={() => setQuery("")}>Limpar busca</Button>
              ) : (
                <Button variant="primary" icon={Plus} onClick={() => setModal(true)}>
                  Adicionar candidato
                </Button>
              )
            }
          />
        </Panel>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((candidate) => (
            <CandidateCard key={candidate.id} candidate={candidate} />
          ))}
        </div>
      )}

      <NewCandidateModal
        open={modal}
        onClose={() => setModal(false)}
        onCreated={candidates.reload}
        jobs={jobs.data ?? []}
      />
    </>
  );
}
