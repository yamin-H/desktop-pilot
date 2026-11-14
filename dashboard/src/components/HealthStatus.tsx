"use client";

import { useEffect, useState } from "react";
import { useMarket } from "./MarketProvider";
import type { Health } from "@/lib/types";

type Level = "ok" | "warn" | "bad" | "off";

function useHealth() {
  const [health, setHealth] = useState<Health | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    async function load() {
      try {
        const response = await fetch("/api/health", { cache: "no-store", signal: controller.signal });
        const body = (await response.json()) as Health; // a 503 still carries the details
        if (!stopped) {
          setHealth(body);
          setUnreachable(false);
        }
      } catch {
        if (!stopped) setUnreachable(true);
      }
      if (!stopped) timer = setTimeout(load, 5000);
    }

    load();
    return () => {
      stopped = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, []);

  return { health, unreachable };
}

function Row({ level, label, detail }: { level: Level; label: string; detail: string }) {
  return (
    <li>
      <span className={`dot ${level}`} aria-hidden="true" />
      <span>{label}</span>
      <span className="row-detail">{detail}</span>
    </li>
  );
}

export default function HealthStatus() {
  const { market, connected } = useMarket();
  const { health, unreachable } = useHealth();

  const fresh = market?.prices.some((p) => p.fresh) ?? false;
  const feed: [Level, string] = !connected
    ? ["bad", "disconnected"]
    : fresh
      ? ["ok", "streaming"]
      : ["warn", "no fresh prices"];

  const api: [Level, string] = unreachable
    ? ["bad", "unreachable"]
    : !health
      ? ["off", "checking"]
      : health.status === "ok"
        ? ["ok", "running"]
        : ["warn", "degraded"];

  const database: [Level, string] = !health
    ? ["off", "unknown"]
    : health.database === "ok"
      ? ["ok", "connected"]
      : health.database === "unreachable"
        ? ["bad", "unreachable"]
        : ["off", "unknown"];

  const redis: [Level, string] = !health
    ? ["off", "unknown"]
    : health.redis === "ok"
      ? ["ok", "connected"]
      : health.redis === "unreachable"
        ? ["bad", "unreachable"]
        : ["off", "not used"];

  return (
    <section className="system" aria-label="System status">
      <h2>System</h2>
      <ul>
        <Row level={feed[0]} label="Live prices" detail={feed[1]} />
        <Row level={api[0]} label="API" detail={api[1]} />
        <Row level={database[0]} label="Database" detail={database[1]} />
        <Row level={redis[0]} label="Redis" detail={redis[1]} />
      </ul>
      <p className="foot">
        {health ? `Prices come from ${health.market_source === "redis" ? "the Redis stream" : "the database"}. ` : ""}
        Paper trades only. Read-only.
      </p>
    </section>
  );
}