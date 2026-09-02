"use client";

import React from "react";
import { CheckCircle2, MinusCircle, Repeat2, ShieldAlert, ShieldCheck } from "lucide-react";
import type { FairnessAudit, FairnessAxis } from "@/lib/types";
import { Badge, Panel, cn } from "@/components/ui/primitives";
import { formatMs } from "@/components/charts";

const AXIS_LABELS: Record<string, string> = {
  genero: "Gênero",
  nome: "Nome e sobrenome",
  idade: "Idade / tempo de formação",
  instituicao: "Instituição de ensino",
};

function DeltaBar({ pct, threshold }: { pct: number; threshold: number }) {
  // The scale runs to 3× the threshold so a passing result reads as visibly small.
  const scaleMax = Math.max(threshold * 3, pct * 1.2, 1);
  const width = Math.min((pct / scaleMax) * 100, 100);
  const thresholdX = (threshold / scaleMax) * 100;
  const passing = pct < threshold;

  return (
    <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-white/[0.05]">
      <div
        className="h-full rounded-full transition-[width] duration-500"
        style={{
          width: `${Math.max(width, 1)}%`,
          background: passing ? "var(--status-good)" : "var(--status-critical)",
        }}
      />
      <span
        aria-hidden
        className="absolute inset-y-0 w-px bg-[var(--text-muted)]"
        style={{ left: `${thresholdX}%` }}
        title={`Limite de tolerância: ${threshold}%`}
      />
    </div>
  );
}

function AxisRow({ axis, threshold }: { axis: FairnessAxis; threshold: number }) {
  if (!axis.applicable) {
    return (
      <li className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-medium text-[var(--text-secondary)]">
            {AXIS_LABELS[axis.axis] ?? axis.axis}
          </span>
          <Badge icon={MinusCircle}>Não aplicável</Badge>
        </div>
        <p className="mt-1.5 text-[11px] text-[var(--text-muted)]">{axis.reason}</p>
      </li>
    );
  }

  return (
    <li className="rounded-xl border border-white/8 bg-white/[0.02] p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-medium text-[var(--text-secondary)]">
          {AXIS_LABELS[axis.axis] ?? axis.axis}
        </span>
        <Badge
          tone={axis.passed ? "good" : "critical"}
          icon={axis.passed ? CheckCircle2 : ShieldAlert}
        >
          {axis.passed ? "Sem viés detectado" : "Viés detectado"}
        </Badge>
      </div>

      <p className="mb-2.5 text-[11px] leading-relaxed text-[var(--text-muted)]">{axis.description}</p>

      <DeltaBar pct={axis.score_pct_delta} threshold={threshold} />

      <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] sm:grid-cols-4">
        <div className="flex justify-between gap-2 sm:block">
          <dt className="text-[var(--text-muted)]">Score original</dt>
          <dd className="tabular text-[var(--text-secondary)]">{axis.original_score.toFixed(2)}</dd>
        </div>
        <div className="flex justify-between gap-2 sm:block">
          <dt className="text-[var(--text-muted)]">Contrafactual</dt>
          <dd className="tabular text-[var(--text-secondary)]">
            {axis.counterfactual_score.toFixed(2)}
          </dd>
        </div>
        <div className="flex justify-between gap-2 sm:block">
          <dt className="text-[var(--text-muted)]">Variação</dt>
          <dd
            className={cn(
              "tabular",
              axis.passed ? "text-[var(--status-good)]" : "text-[var(--status-critical)]",
            )}
          >
            {axis.score_pct_delta.toFixed(3)}%
          </dd>
        </div>
        <div className="flex justify-between gap-2 sm:block">
          <dt className="text-[var(--text-muted)]">Posição no ranking</dt>
          <dd className="tabular text-[var(--text-secondary)]">
            #{axis.original_rank} → #{axis.counterfactual_rank}
          </dd>
        </div>
      </dl>

      {axis.swaps?.length ? (
        <details className="mt-2.5">
          <summary className="cursor-pointer text-[11px] text-[var(--text-muted)] hover:text-[var(--text-secondary)]">
            <Repeat2 className="mr-1 inline h-3 w-3" />
            {axis.swap_count ?? axis.swaps.length} substituições aplicadas
          </summary>
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {axis.swaps.map((swap, i) => (
              <li
                key={i}
                className="rounded border border-white/8 bg-black/25 px-1.5 py-0.5 font-mono text-[10px] text-[var(--text-muted)]"
              >
                {swap.original} → {swap.replacement}
                {swap.count > 1 ? ` ×${swap.count}` : ""}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </li>
  );
}

export function FairnessReport({ audit }: { audit: FairnessAudit }) {
  return (
    <div className="space-y-4">
      <Panel
        className={cn(
          "flex flex-wrap items-center justify-between gap-4 border-l-2 p-4",
          audit.audit_passed
            ? "border-l-[var(--status-good)]"
            : "border-l-[var(--status-critical)]",
        )}
      >
        <div className="flex items-center gap-3">
          <span
            className={cn(
              "flex h-10 w-10 items-center justify-center rounded-xl",
              audit.audit_passed
                ? "bg-[color-mix(in_srgb,var(--status-good)_16%,transparent)] text-[var(--status-good)]"
                : "bg-[color-mix(in_srgb,var(--status-critical)_16%,transparent)] text-[var(--status-critical)]",
            )}
          >
            {audit.audit_passed ? (
              <ShieldCheck className="h-5 w-5" />
            ) : (
              <ShieldAlert className="h-5 w-5" />
            )}
          </span>
          <div>
            <p className="text-sm font-semibold text-[var(--text-primary)]">
              {audit.audit_passed
                ? "Auditoria aprovada em todos os eixos"
                : "Variação acima do limite em ao menos um eixo"}
            </p>
            <p className="mt-0.5 text-[11px] text-[var(--text-muted)]">
              Maior variação: {audit.max_score_pct_delta.toFixed(3)}% · limite de tolerância{" "}
              {audit.threshold_pct}% · pool de comparação com {audit.pool_size} candidatos
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge>score base {audit.original_score.toFixed(2)}</Badge>
          <Badge>posição #{audit.original_rank}</Badge>
          <Badge>{formatMs(audit.duration_ms)}</Badge>
          {audit.deep ? <Badge tone="accent">reextração por LLM</Badge> : null}
        </div>
      </Panel>

      <ul className="grid gap-3 lg:grid-cols-2">
        {audit.axes.map((axis) => (
          <AxisRow key={axis.axis} axis={axis} threshold={audit.threshold_pct} />
        ))}
      </ul>

      <p className="rounded-xl border border-white/8 bg-white/[0.02] p-3 text-[11px] leading-relaxed text-[var(--text-muted)]">
        <strong className="font-medium text-[var(--text-secondary)]">Como funciona:</strong> clonamos o
        currículo, trocamos um marcador demográfico por vez e submetemos as duas versões exatamente ao
        mesmo caminho de pontuação. Um pipeline justo naquele eixo não deveria mover o score de forma
        perceptível — por isso qualquer variação acima de {audit.threshold_pct}% reprova a auditoria.
      </p>
    </div>
  );
}
