"use client";

import React from "react";
import Link from "next/link";
import {
  CheckCircle2,
  History,
  Play,
  ScaleIcon,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { api } from "@/lib/api";
import { formatDateTime, useAsync } from "@/lib/hooks";
import type { AuditLog, Candidate, FairnessAudit, Job } from "@/lib/types";
import { PageHeader } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Panel,
  SectionTitle,
  Skeleton,
} from "@/components/ui/primitives";
import { FairnessReport } from "@/components/ats/FairnessReport";
import { StatTile, formatMs } from "@/components/charts";

export default function FairnessPage() {
  const jobs = useAsync<Job[]>(() => api.jobs());
  const candidates = useAsync<Candidate[]>(() => api.candidates());
  const logs = useAsync<AuditLog[]>(() => api.auditLogs(30));

  const [jobId, setJobId] = React.useState("");
  const [candidateId, setCandidateId] = React.useState("");
  const [deep, setDeep] = React.useState(false);
  const [audit, setAudit] = React.useState<FairnessAudit | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const run = async () => {
    const job = jobs.data?.find((j) => j.id === Number(jobId));
    const candidate = candidates.data?.find((c) => c.id === Number(candidateId));
    if (!job || !candidate) return;
    setBusy(true);
    setError(null);
    try {
      setAudit(await api.auditBias(candidate.profile_id, job.profile_id, deep));
      logs.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao rodar a auditoria.");
    } finally {
      setBusy(false);
    }
  };

  const history = logs.data ?? [];
  const passed = history.filter((l) => l.bias_audit_passed).length;
  const passRate = history.length ? Math.round((passed / history.length) * 100) : 0;
  const worstDelta = history.reduce(
    (max, log) => Math.max(max, log.bias_audit_results?.max_score_pct_delta ?? 0),
    0,
  );

  return (
    <>
      <PageHeader
        title="Equidade algorítmica"
        description="Auditoria contrafactual: o mesmo currículo, um marcador demográfico trocado por vez, o mesmo caminho de pontuação. Se o score se move, o pipeline tem viés naquele eixo."
      />

      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        <StatTile
          label="Auditorias executadas"
          value={history.length}
          icon={History}
          hint="histórico completo registrado no banco"
        />
        <StatTile
          label="Taxa de aprovação"
          value={`${passRate}%`}
          tone={passRate === 100 ? "good" : passRate >= 80 ? "warning" : "critical"}
          hint={`${passed} de ${history.length} auditorias sem viés detectado`}
          icon={ShieldCheck}
        />
        <StatTile
          label="Maior variação observada"
          value={`${worstDelta.toFixed(3)}%`}
          tone={worstDelta < 1 ? "good" : "critical"}
          hint="limite de tolerância: 1%"
          icon={ShieldAlert}
        />
      </div>

      <Panel className="mb-5 p-5">
        <SectionTitle
          title="Rodar nova auditoria"
          subtitle="Escolha um par candidato/vaga. Os quatro eixos são testados de uma vez."
          icon={ScaleIcon}
        />
        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <label className="block">
            <span className="mb-1 block text-[11px] text-[var(--text-muted)]">Vaga</span>
            <select
              className="field w-full px-3 py-2 text-sm"
              value={jobId}
              onChange={(e) => setJobId(e.target.value)}
            >
              <option value="">Selecione…</option>
              {(jobs.data ?? []).map((j) => (
                <option key={j.id} value={j.id}>
                  {j.title}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] text-[var(--text-muted)]">Candidato</span>
            <select
              className="field w-full px-3 py-2 text-sm"
              value={candidateId}
              onChange={(e) => setCandidateId(e.target.value)}
            >
              <option value="">Selecione…</option>
              {(candidates.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.display_name}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-end">
            <Button
              variant="primary"
              icon={Play}
              onClick={run}
              loading={busy}
              disabled={!jobId || !candidateId}
              className="h-[38px] w-full sm:w-auto"
            >
              Auditar
            </Button>
          </div>
        </div>
        <label className="mt-3 flex items-center gap-2 text-xs text-[var(--text-secondary)]">
          <input
            type="checkbox"
            checked={deep}
            onChange={(e) => setDeep(e.target.checked)}
            className="h-3.5 w-3.5 accent-[var(--accent)]"
          />
          Auditoria profunda — reexecuta também a extração por LLM na variante (mais lenta, coloca o
          próprio modelo sob teste)
        </label>
        {error ? <p className="mt-3 text-xs text-[var(--status-critical)]">{error}</p> : null}
      </Panel>

      {busy ? <Skeleton className="mb-5 h-72" /> : null}
      {audit ? (
        <div className="mb-5">
          <FairnessReport audit={audit} />
        </div>
      ) : null}

      <Panel className="p-5">
        <SectionTitle title="Histórico de auditorias" icon={History} />
        {logs.loading ? (
          <Skeleton className="h-40" />
        ) : logs.error ? (
          <ErrorState error={logs.error} onRetry={logs.reload} />
        ) : history.length === 0 ? (
          <EmptyState
            icon={ScaleIcon}
            title="Nenhuma auditoria executada"
            description="Rode a primeira auditoria acima para começar o registro."
          />
        ) : (
          <ul className="divide-y divide-white/6">
            {history.map((log) => (
              <li key={log.id} className="flex flex-wrap items-center gap-3 py-2.5">
                <Badge
                  tone={log.bias_audit_passed ? "good" : "critical"}
                  icon={log.bias_audit_passed ? CheckCircle2 : ShieldAlert}
                >
                  {log.bias_audit_passed ? "Aprovada" : "Reprovada"}
                </Badge>
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-[var(--text-secondary)]">
                    Candidato #{log.bias_audit_results?.candidate_id ?? "—"} × vaga #{log.query_id}
                  </p>
                  <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">
                    Variação máxima {(log.bias_audit_results?.max_score_pct_delta ?? 0).toFixed(3)}% ·{" "}
                    {(log.bias_audit_results?.axes ?? []).filter((a) => a.applicable).length} eixos testados ·{" "}
                    {formatMs(log.execution_time_ms)}
                  </p>
                </div>
                <span className="text-[11px] text-[var(--text-muted)]">
                  {formatDateTime(log.created_at)}
                </span>
                {log.trace_id ? (
                  <Link
                    href={`/observability?trace=${log.trace_id}`}
                    className="text-[11px] text-[var(--accent-soft)] hover:underline"
                  >
                    trace
                  </Link>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </>
  );
}
