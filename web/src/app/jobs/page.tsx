"use client";

import React from "react";
import Link from "next/link";
import {
  Briefcase,
  Building2,
  MapPin,
  Plus,
  Sparkles,
  Users,
  Wallet,
} from "lucide-react";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import type { Job } from "@/lib/types";
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
  Tabs,
} from "@/components/ui/primitives";
import { ORDINAL } from "@/components/charts";

function formatSalary(job: Job): string | null {
  if (!job.salary_min && !job.salary_max) return null;
  const fmt = (v: number) => `R$ ${(v / 1000).toFixed(0)}k`;
  if (job.salary_min && job.salary_max) return `${fmt(job.salary_min)} – ${fmt(job.salary_max)}`;
  return fmt(job.salary_min ?? job.salary_max ?? 0);
}

function MiniFunnel({ job }: { job: Job }) {
  const funnel = job.funnel;
  if (!funnel) return null;
  const entries = Object.entries(funnel).filter(([key]) => key !== "rejected");
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  if (total === 0) {
    return <p className="text-[11px] text-[var(--text-muted)]">Nenhuma candidatura no funil.</p>;
  }
  return (
    <div>
      {/* 2px surface gaps keep adjacent segments legible without borders. */}
      <div className="flex h-2 w-full gap-[2px] overflow-hidden rounded-full">
        {entries.map(([key, count], i) =>
          count > 0 ? (
            <span
              key={key}
              className="h-full rounded-full"
              style={{
                flex: count,
                background: ORDINAL[Math.min(i, ORDINAL.length - 1)],
              }}
              title={`${key}: ${count}`}
            />
          ) : null,
        )}
      </div>
      <p className="mt-1.5 text-[11px] text-[var(--text-muted)]">
        {total} no funil · {funnel.hired ?? 0} contratado(s) · {funnel.rejected ?? 0} reprovado(s)
      </p>
    </div>
  );
}

function JobCard({ job }: { job: Job }) {
  const salary = formatSalary(job);
  return (
    <Panel hover className="animate-fade-up flex flex-col p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            href={`/jobs/${job.id}`}
            className="block truncate text-sm font-semibold text-[var(--text-primary)] transition-colors hover:text-[var(--accent-soft)]"
          >
            {job.title}
          </Link>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[var(--text-muted)]">
            {job.department ? (
              <span className="inline-flex items-center gap-1">
                <Building2 className="h-3 w-3" />
                {job.department}
              </span>
            ) : null}
            {job.location ? (
              <span className="inline-flex items-center gap-1">
                <MapPin className="h-3 w-3" />
                {job.location}
              </span>
            ) : null}
            {salary ? (
              <span className="inline-flex items-center gap-1">
                <Wallet className="h-3 w-3" />
                {salary}
              </span>
            ) : null}
          </p>
        </div>
        <Badge tone={job.status === "open" ? "good" : job.status === "paused" ? "warning" : "neutral"}>
          {job.status === "open" ? "Aberta" : job.status === "paused" ? "Pausada" : "Fechada"}
        </Badge>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {job.seniority ? <Badge tone="accent">{job.seniority}</Badge> : null}
        {job.work_model ? <Badge>{job.work_model}</Badge> : null}
        {job.employment_type ? <Badge>{job.employment_type}</Badge> : null}
        <Badge>
          <Users className="mr-1 inline h-3 w-3" />
          {job.headcount} vaga(s)
        </Badge>
      </div>

      <div className="mt-3">
        <p className="mb-1 text-[10px] uppercase tracking-wide text-[var(--text-muted)]">
          Competências obrigatórias
        </p>
        <SkillChips skills={job.must_have_skills} max={6} emptyLabel="Não informadas" />
      </div>

      <div className="mt-auto pt-4">
        <MiniFunnel job={job} />
      </div>

      <Link href={`/jobs/${job.id}`} className="btn btn-ghost mt-3 w-full py-2">
        <Sparkles className="h-4 w-4" />
        Ranquear candidatos
      </Link>
    </Panel>
  );
}

function NewJobModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const [text, setText] = React.useState("");
  const [title, setTitle] = React.useState("");
  const [department, setDepartment] = React.useState("");
  const [location, setLocation] = React.useState("");
  const [workModel, setWorkModel] = React.useState("Remoto");
  const [file, setFile] = React.useState<File | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      if (file) form.append("file", file);
      else form.append("text_content", text);
      form.append(
        "meta",
        JSON.stringify({
          title: title || undefined,
          department: department || undefined,
          location: location || undefined,
          work_model: workModel || undefined,
        }),
      );
      await api.createJob(form);
      onCreated();
      onClose();
      setText("");
      setTitle("");
      setFile(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao publicar a vaga.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Publicar vaga"
      subtitle="A descrição passa pelo mesmo pipeline dos currículos: anonimização, extração estruturada e indexação vetorial."
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-[11px] text-[var(--text-muted)]">Título (opcional)</span>
            <input
              className="field w-full px-3 py-2 text-sm"
              placeholder="Deixe vazio para a IA inferir"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] text-[var(--text-muted)]">Área</span>
            <input
              className="field w-full px-3 py-2 text-sm"
              placeholder="Engenharia de Produto"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] text-[var(--text-muted)]">Local</span>
            <input
              className="field w-full px-3 py-2 text-sm"
              placeholder="São Paulo, SP"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] text-[var(--text-muted)]">Modelo</span>
            <select
              className="field w-full px-3 py-2 text-sm"
              value={workModel}
              onChange={(e) => setWorkModel(e.target.value)}
            >
              <option>Remoto</option>
              <option>Híbrido</option>
              <option>Presencial</option>
            </select>
          </label>
        </div>

        <label className="block">
          <span className="mb-1 block text-[11px] text-[var(--text-muted)]">Descrição da vaga</span>
          <textarea
            className="field min-h-[180px] w-full px-3 py-2 font-mono text-xs"
            placeholder="Cole a descrição completa da vaga aqui…"
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

        {error ? <p className="text-xs text-[var(--status-critical)]">{error}</p> : null}

        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancelar</Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            disabled={!file && text.trim().length < 40}
          >
            Publicar vaga
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export default function JobsPage() {
  const [filter, setFilter] = React.useState<"all" | "open" | "paused" | "closed">("all");
  const [modal, setModal] = React.useState(false);
  const jobs = useAsync<Job[]>(() => api.jobs());

  const filtered = (jobs.data ?? []).filter((j) => filter === "all" || j.status === filter);
  const counts = (jobs.data ?? []).reduce<Record<string, number>>((acc, j) => {
    acc[j.status] = (acc[j.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <>
      <PageHeader
        title="Vagas"
        description="Cada vaga é indexada como vetor, permitindo ranquear todo o banco de talentos contra ela em segundos."
        actions={
          <Button variant="primary" icon={Plus} onClick={() => setModal(true)}>
            Publicar vaga
          </Button>
        }
      />

      <div className="mb-5">
        <Tabs
          active={filter}
          onChange={setFilter}
          tabs={[
            { key: "all", label: "Todas", count: jobs.data?.length },
            { key: "open", label: "Abertas", count: counts.open ?? 0 },
            { key: "paused", label: "Pausadas", count: counts.paused ?? 0 },
            { key: "closed", label: "Fechadas", count: counts.closed ?? 0 },
          ]}
        />
      </div>

      {jobs.loading && !jobs.data ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-64" />
          ))}
        </div>
      ) : jobs.error ? (
        <Panel>
          <ErrorState error={jobs.error} onRetry={jobs.reload} />
        </Panel>
      ) : filtered.length === 0 ? (
        <Panel>
          <EmptyState
            icon={Briefcase}
            title="Nenhuma vaga por aqui"
            description="Publique a primeira vaga para começar a ranquear candidatos."
            action={
              <Button variant="primary" icon={Plus} onClick={() => setModal(true)}>
                Publicar vaga
              </Button>
            }
          />
        </Panel>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((job) => (
            <JobCard key={job.id} job={job} />
          ))}
        </div>
      )}

      <NewJobModal open={modal} onClose={() => setModal(false)} onCreated={jobs.reload} />
    </>
  );
}
