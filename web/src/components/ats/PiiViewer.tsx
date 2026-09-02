"use client";

import React from "react";
import { Eye, EyeOff, LockKeyhole, ShieldCheck } from "lucide-react";
import type { Profile } from "@/lib/types";
import { Badge, Button, cn } from "@/components/ui/primitives";

const ENTITY_LABELS: Record<string, string> = {
  NOME_REDACT: "Nome",
  EMAIL_REDACT: "E-mail",
  TELEFONE_REDACT: "Telefone",
  CPF_REDACT: "CPF",
  RG_REDACT: "RG",
  IP_REDACT: "IP",
  LOCALIZACAO_REDACT: "Localização",
  ORGANIZACAO_REDACT: "Organização",
};

function entityOf(placeholder: string): string {
  const inner = placeholder.replace(/^\[|\]$/g, "");
  return inner.replace(/_\d+$/, "");
}

/** Renders redacted text with every placeholder highlighted as a chip. */
function RedactedText({ text, reveal, map }: { text: string; reveal: boolean; map: Record<string, string> }) {
  const parts = React.useMemo(() => text.split(/(\[[A-Z_]+_\d+\])/g), [text]);
  return (
    <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-[var(--text-secondary)]">
      {parts.map((part, i) =>
        /^\[[A-Z_]+_\d+\]$/.test(part) ? (
          <span
            key={i}
            title={reveal ? `Placeholder: ${part}` : `${ENTITY_LABELS[entityOf(part)] ?? entityOf(part)} anonimizado`}
            className={cn(
              "mx-0.5 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] not-italic",
              reveal
                ? "bg-[color-mix(in_srgb,var(--status-critical)_18%,transparent)] text-[var(--status-critical)]"
                : "bg-[color-mix(in_srgb,var(--accent)_20%,transparent)] text-[var(--accent-soft)]",
            )}
          >
            {reveal ? map[part] ?? part : part}
          </span>
        ) : (
          <React.Fragment key={i}>{part}</React.Fragment>
        ),
      )}
    </pre>
  );
}

export function PiiViewer({ profile }: { profile: Profile }) {
  const [reveal, setReveal] = React.useState(false);
  const map = profile.redaction_map ?? {};
  const entries = Object.entries(map);

  const byType = entries.reduce<Record<string, number>>((acc, [placeholder]) => {
    const key = entityOf(placeholder);
    acc[key] = (acc[key] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/8 bg-white/[0.02] p-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="good" icon={ShieldCheck}>
            {entries.length} entidades anonimizadas
          </Badge>
          {Object.entries(byType).map(([type, count]) => (
            <Badge key={type}>
              {ENTITY_LABELS[type] ?? type} ×{count}
            </Badge>
          ))}
        </div>
        <Button onClick={() => setReveal((v) => !v)} icon={reveal ? EyeOff : Eye}>
          {reveal ? "Ocultar dados originais" : "Revelar dados originais"}
        </Button>
      </div>

      <p className="flex items-start gap-2 rounded-xl border border-white/8 bg-white/[0.02] p-3 text-[11px] leading-relaxed text-[var(--text-muted)]">
        <LockKeyhole className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--accent-soft)]" />
        O texto da direita é <strong className="font-medium text-[var(--text-secondary)]">exatamente o que a
        LLM recebeu</strong>. Os dados originais ficam apenas no banco, para a tela do recrutador — nunca
        saem para uma API externa.
      </p>

      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-xl border border-white/8 bg-black/25">
          <div className="flex items-center gap-2 border-b border-white/8 px-3 py-2">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--status-critical)]" aria-hidden />
            <span className="text-[11px] font-medium text-[var(--text-secondary)]">
              Documento original (nunca enviado à IA)
            </span>
          </div>
          <div className="max-h-[420px] overflow-auto p-3">
            <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-[var(--text-muted)]">
              {profile.raw_text ?? "—"}
            </pre>
          </div>
        </div>

        <div className="rounded-xl border border-white/8 bg-black/25">
          <div className="flex items-center gap-2 border-b border-white/8 px-3 py-2">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--status-good)]" aria-hidden />
            <span className="text-[11px] font-medium text-[var(--text-secondary)]">
              Texto enviado à IA (anonimizado)
            </span>
          </div>
          <div className="max-h-[420px] overflow-auto p-3">
            <RedactedText text={profile.redacted_text} reveal={reveal} map={map} />
          </div>
        </div>
      </div>
    </div>
  );
}
