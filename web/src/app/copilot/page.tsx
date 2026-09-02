"use client";

import React from "react";
import Link from "next/link";
import {
  Activity,
  ArrowUp,
  BrainCircuit,
  Terminal,
  Trash2,
  User,
  Wrench,
} from "lucide-react";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import type { CopilotCard, CopilotResponse, CopilotTools, Job } from "@/lib/types";
import { PageHeader } from "@/components/layout/AppShell";
import { Badge, Button, Panel, SectionTitle, cn } from "@/components/ui/primitives";
import { CopilotCardView } from "@/components/copilot/Cards";
import { formatMs } from "@/components/charts";

interface Turn {
  id: string;
  role: "user" | "assistant";
  content: string;
  cards?: CopilotCard[];
  toolCalls?: CopilotResponse["tool_calls"];
  traceId?: string | null;
  model?: string;
  elapsedMs?: number;
  error?: boolean;
}

function ToolTrail({ turn }: { turn: Turn }) {
  if (!turn.toolCalls?.length) return null;
  return (
    <div className="mb-2.5 flex flex-wrap items-center gap-1.5">
      {turn.toolCalls.map((call, i) => (
        <Badge
          key={i}
          tone={call.ok ? "accent" : "critical"}
          icon={Wrench}
          title={JSON.stringify(call.arguments)}
        >
          {call.name}
        </Badge>
      ))}
      {turn.elapsedMs ? (
        <span className="tabular text-[10px] text-[var(--text-muted)]">{formatMs(turn.elapsedMs)}</span>
      ) : null}
      {turn.traceId ? (
        <Link
          href={`/observability?trace=${turn.traceId}`}
          className="inline-flex items-center gap-1 text-[10px] text-[var(--accent-soft)] hover:underline"
        >
          <Activity className="h-3 w-3" />
          ver trace
        </Link>
      ) : null}
    </div>
  );
}

function Message({ turn }: { turn: Turn }) {
  const isUser = turn.role === "user";
  return (
    <div className="animate-fade-up">
      <div className={cn("flex gap-3", isUser && "flex-row-reverse")}>
        <span
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
            isUser
              ? "bg-white/8 text-[var(--text-secondary)]"
              : "bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)] text-white",
          )}
        >
          {isUser ? <User className="h-3.5 w-3.5" /> : <BrainCircuit className="h-3.5 w-3.5" />}
        </span>
        <div className={cn("min-w-0 max-w-[min(46rem,88%)]", isUser && "text-right")}>
          <div
            className={cn(
              "inline-block rounded-2xl px-3.5 py-2.5 text-left text-sm leading-relaxed",
              isUser
                ? "bg-white/[0.07] text-[var(--text-primary)]"
                : turn.error
                  ? "border border-[color-mix(in_srgb,var(--status-critical)_35%,transparent)] bg-[color-mix(in_srgb,var(--status-critical)_10%,transparent)] text-[var(--text-secondary)]"
                  : "bg-white/[0.03] text-[var(--text-secondary)]",
            )}
          >
            {!isUser ? <ToolTrail turn={turn} /> : null}
            <p className="whitespace-pre-wrap">{turn.content}</p>
          </div>
        </div>
      </div>

      {turn.cards?.length ? (
        <div className="ml-10 mt-3 space-y-3">
          {turn.cards.map((card, i) => (
            <CopilotCardView key={i} card={card} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function CopilotPage() {
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [input, setInput] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [jobId, setJobId] = React.useState<string>("");
  const scrollRef = React.useRef<HTMLDivElement>(null);

  const tools = useAsync<CopilotTools>(() => api.copilotTools());
  const jobs = useAsync<Job[]>(() => api.jobs());

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns, busy]);

  const send = async (message: string) => {
    const text = message.trim();
    if (!text || busy) return;

    const userTurn: Turn = { id: `u-${Date.now()}`, role: "user", content: text };
    const history = turns.map((t) => ({ role: t.role, content: t.content }));
    setTurns((prev) => [...prev, userTurn]);
    setInput("");
    setBusy(true);

    const started = performance.now();
    try {
      const response = await api.chat(text, history, jobId ? Number(jobId) : null);
      setTurns((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          content: response.reply,
          cards: response.cards,
          toolCalls: response.tool_calls,
          traceId: response.trace_id,
          model: response.model,
          elapsedMs: performance.now() - started,
        },
      ]);
    } catch (e) {
      setTurns((prev) => [
        ...prev,
        {
          id: `e-${Date.now()}`,
          role: "assistant",
          content: e instanceof Error ? e.message : "Falha ao falar com o copiloto.",
          error: true,
        },
      ]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-[calc(100vh-6rem)] flex-col lg:h-[calc(100vh-4rem)]">
      <PageHeader
        title="Copiloto de recrutamento"
        description="Converse com o ATS. O copiloto consulta os dados reais por ferramentas — nunca inventa candidatos ou scores."
        actions={
          turns.length ? (
            <Button icon={Trash2} onClick={() => setTurns([])}>
              Limpar conversa
            </Button>
          ) : null
        }
      />

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[1fr_260px]">
        <Panel className="flex min-h-0 flex-col overflow-hidden">
          <div ref={scrollRef} className="flex-1 space-y-5 overflow-y-auto p-4 sm:p-5">
            {turns.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-5 py-10 text-center">
                <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)]">
                  <BrainCircuit className="h-6 w-6 text-white" />
                </span>
                <div>
                  <p className="text-sm font-medium text-[var(--text-secondary)]">
                    Pergunte qualquer coisa sobre suas vagas e candidatos
                  </p>
                  <p className="mx-auto mt-1 max-w-md text-xs leading-relaxed text-[var(--text-muted)]">
                    O copiloto ranqueia, explica, audita viés e move candidaturas no funil — tudo com os
                    dados reais do seu ATS.
                  </p>
                </div>
                <div className="flex max-w-xl flex-wrap justify-center gap-2">
                  {(tools.data?.suggestions ?? []).map((suggestion) => (
                    <button
                      key={suggestion}
                      onClick={() => send(suggestion)}
                      className="rounded-full border border-white/8 bg-white/[0.03] px-3 py-1.5 text-[11px] text-[var(--text-secondary)] transition-colors hover:border-white/16 hover:bg-white/[0.07]"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              turns.map((turn) => <Message key={turn.id} turn={turn} />)
            )}

            {busy ? (
              <div className="flex items-center gap-3">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-[var(--accent)] to-[var(--accent-2)]">
                  <BrainCircuit className="h-3.5 w-3.5 text-white" />
                </span>
                <span className="flex items-center gap-1.5 rounded-2xl bg-white/[0.03] px-3.5 py-2.5">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="pulse-dot h-1.5 w-1.5 rounded-full bg-[var(--accent-soft)]"
                      style={{ animationDelay: `${i * 200}ms` }}
                    />
                  ))}
                </span>
              </div>
            ) : null}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              void send(input);
            }}
            className="border-t border-white/8 p-3"
          >
            <div className="flex items-end gap-2">
              <select
                className="field shrink-0 px-2 py-2.5 text-xs"
                value={jobId}
                onChange={(e) => setJobId(e.target.value)}
                title="Vaga em contexto"
              >
                <option value="">Sem vaga em foco</option>
                {(jobs.data ?? []).map((job) => (
                  <option key={job.id} value={job.id}>
                    {job.title}
                  </option>
                ))}
              </select>
              <textarea
                rows={1}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send(input);
                  }
                }}
                placeholder="Ex: quem são os 5 melhores candidatos para a vaga de SRE?"
                className="field max-h-40 min-h-[42px] flex-1 resize-none px-3 py-2.5 text-sm"
              />
              <Button
                type="submit"
                variant="primary"
                icon={ArrowUp}
                loading={busy}
                disabled={!input.trim()}
                className="h-[42px] px-3"
              >
                <span className="sr-only">Enviar</span>
              </Button>
            </div>
          </form>
        </Panel>

        <Panel className="hidden overflow-y-auto p-4 lg:block">
          <SectionTitle
            title="Ferramentas disponíveis"
            subtitle="O que o copiloto pode executar no ATS"
            icon={Terminal}
          />
          <ul className="space-y-3">
            {(tools.data?.tools ?? []).map((tool) => (
              <li key={tool.name}>
                <p className="font-mono text-[11px] text-[var(--accent-soft)]">{tool.name}</p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--text-muted)]">
                  {tool.description}
                </p>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
