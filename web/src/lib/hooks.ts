"use client";

import React from "react";

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
  setData: React.Dispatch<React.SetStateAction<T | null>>;
}

interface Resolved<T> {
  key: string;
  data: T | null;
  error: string | null;
}

/**
 * Fetch-on-mount with reload, cancellation and a normalised error string.
 *
 * `loading` is *derived* by comparing the key of the settled result against the
 * key of the current request, so no state is set synchronously inside an effect.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: React.DependencyList = []): AsyncState<T> {
  const [nonce, setNonce] = React.useState(0);
  const key = `${nonce}:${JSON.stringify(deps)}`;
  const [resolved, setResolved] = React.useState<Resolved<T> | null>(null);

  // The callback identity changes every render; keep it in a ref updated from an
  // effect so the fetch effect only re-runs when `key` actually changes.
  const fnRef = React.useRef(fn);
  React.useEffect(() => {
    fnRef.current = fn;
  });

  React.useEffect(() => {
    let cancelled = false;
    fnRef
      .current()
      .then((data) => {
        if (!cancelled) setResolved({ key, data, error: null });
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setResolved({ key, data: null, error: e instanceof Error ? e.message : String(e) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [key]);

  const settled = resolved?.key === key ? resolved : null;

  const setData: React.Dispatch<React.SetStateAction<T | null>> = React.useCallback(
    (update) => {
      setResolved((current) => {
        const previous = current?.data ?? null;
        const next = typeof update === "function" ? (update as (p: T | null) => T | null)(previous) : update;
        return { key: current?.key ?? key, data: next, error: current?.error ?? null };
      });
    },
    [key],
  );

  return {
    // Keep the previous payload visible while a refresh is in flight.
    data: settled?.data ?? resolved?.data ?? null,
    loading: settled === null,
    error: settled?.error ?? null,
    reload: React.useCallback(() => setNonce((n) => n + 1), []),
    setData,
  };
}

/** Poll on an interval, pausing while the tab is hidden. */
export function usePolling(callback: () => void, intervalMs: number, enabled = true) {
  const cbRef = React.useRef(callback);
  React.useEffect(() => {
    cbRef.current = callback;
  });

  React.useEffect(() => {
    if (!enabled) return;
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") cbRef.current();
    }, intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs, enabled]);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatRelative(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  const diff = Date.now() - date.getTime();
  if (Number.isNaN(diff)) return "—";
  const minutes = Math.round(diff / 60_000);
  if (minutes < 1) return "agora";
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `há ${hours} h`;
  const days = Math.round(hours / 24);
  return `há ${days} d`;
}
