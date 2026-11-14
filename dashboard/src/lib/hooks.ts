"use client";

import { useEffect, useState } from "react";

export function usePolling<T>(path: string, everyMs: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    async function load() {
      try {
        const response = await fetch(path, { cache: "no-store", signal: controller.signal });
        const body = await response.json();
        if (stopped) return;
        if (response.ok) {
          setData(body as T);
          setError(null);
        } else {
          setError(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
        }
      } catch {
        if (!stopped) setError("Can't reach the server.");
      }
      if (!stopped) timer = setTimeout(load, everyMs);
    }

    load();
    return () => {
      stopped = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [path, everyMs]);

  return { data, error };
}