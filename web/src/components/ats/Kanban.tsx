"use client";

import React from "react";
import Link from "next/link";
import { GripVertical, Loader2 } from "lucide-react";
import type { Application, KanbanColumn, Stage } from "@/lib/types";
import { api } from "@/lib/api";
import { Badge, FitBadge, cn } from "@/components/ui/primitives";
import { ORDINAL } from "@/components/charts";

function ApplicationCard({
  application,
  dragging,
  onDragStart,
  onDragEnd,
}: {
  application: Application;
  dragging: boolean;
  onDragStart: () => void;
  onDragEnd: () => void;
}) {
  const candidate = application.candidate;
  return (
    <li
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      className={cn(
        "group cursor-grab rounded-xl border border-white/8 bg-[var(--surface-1)] p-3 transition-colors active:cursor-grabbing",
        "hover:border-white/16",
        dragging && "opacity-40",
      )}
    >
      <div className="flex items-start gap-2.5">
        <GripVertical className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--text-muted)] opacity-0 transition-opacity group-hover:opacity-100" />
        <div className="min-w-0 flex-1">
          <Link
            href={`/candidates/${application.candidate_id}`}
            className="block truncate text-xs font-medium text-[var(--text-primary)] hover:text-[var(--accent-soft)]"
          >
            {candidate?.display_name ?? `Candidato ${application.candidate_id}`}
          </Link>
          <p className="mt-0.5 truncate text-[10px] text-[var(--text-muted)]">
            {candidate?.headline ?? "—"}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {application.ai_score !== null ? (
              <Badge tone="accent">
                <span className="tabular">{application.ai_score.toFixed(0)}</span>
              </Badge>
            ) : null}
            {application.ai_fit ? <FitBadge fit={application.ai_fit} /> : null}
          </div>
          {application.ai_summary ? (
            <p className="mt-2 line-clamp-2 text-[10px] leading-relaxed text-[var(--text-muted)]">
              {application.ai_summary}
            </p>
          ) : null}
        </div>
      </div>
    </li>
  );
}

export function KanbanBoard({
  columns,
  onMove,
}: {
  columns: KanbanColumn[];
  onMove?: (applicationId: number, stage: Stage) => void;
}) {
  const [dragging, setDragging] = React.useState<number | null>(null);
  const [over, setOver] = React.useState<Stage | null>(null);
  const [busy, setBusy] = React.useState<number | null>(null);

  const drop = async (stage: Stage) => {
    const id = dragging;
    setOver(null);
    setDragging(null);
    if (!id) return;
    const current = columns.find((c) => c.applications.some((a) => a.id === id));
    if (current?.key === stage) return;
    setBusy(id);
    try {
      await api.moveApplication(id, stage);
      onMove?.(id, stage);
    } finally {
      setBusy(null);
    }
  };

  return (
    // items-start: an empty column should not stretch to the tallest one.
    <div className="-mx-1 flex items-start gap-3 overflow-x-auto px-1 pb-2">
      {columns.map((column, index) => (
        <section
          key={column.key}
          onDragOver={(e) => {
            e.preventDefault();
            setOver(column.key);
          }}
          onDragLeave={() => setOver((s) => (s === column.key ? null : s))}
          onDrop={(e) => {
            e.preventDefault();
            void drop(column.key);
          }}
          className={cn(
            "flex w-64 shrink-0 flex-col rounded-2xl border p-2.5 transition-colors",
            over === column.key
              ? "border-[var(--accent-soft)] bg-[color-mix(in_srgb,var(--accent)_8%,transparent)]"
              : "border-white/8 bg-white/[0.02]",
          )}
        >
          <header className="mb-2.5 flex items-center justify-between gap-2 px-1">
            <span className="flex items-center gap-2 text-xs font-medium text-[var(--text-secondary)]">
              <span
                aria-hidden
                className="h-2 w-2 rounded-[2px]"
                style={{ background: ORDINAL[Math.min(index, ORDINAL.length - 1)] }}
              />
              {column.label}
            </span>
            <span className="tabular rounded bg-white/8 px-1.5 py-0.5 text-[10px] text-[var(--text-muted)]">
              {column.applications.length}
            </span>
          </header>

          <ul className="flex min-h-[80px] flex-col gap-2">
            {column.applications.map((application) => (
              <div key={application.id} className="relative">
                {busy === application.id ? (
                  <span className="absolute right-2 top-2 z-10">
                    <Loader2 className="h-3 w-3 animate-spin text-[var(--accent-soft)]" />
                  </span>
                ) : null}
                <ApplicationCard
                  application={application}
                  dragging={dragging === application.id}
                  onDragStart={() => setDragging(application.id)}
                  onDragEnd={() => setDragging(null)}
                />
              </div>
            ))}
            {column.applications.length === 0 ? (
              <li className="rounded-xl border border-dashed border-white/8 px-3 py-6 text-center text-[10px] text-[var(--text-muted)]">
                Arraste candidatos para cá
              </li>
            ) : null}
          </ul>
        </section>
      ))}
    </div>
  );
}
