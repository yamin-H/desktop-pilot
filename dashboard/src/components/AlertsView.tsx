"use client";

import { useState } from "react";
import Segmented from "./Segmented";
import { safeHref, utcText } from "@/lib/format";
import { usePolling } from "@/lib/hooks";
import type { AnnouncementRow } from "@/lib/types";

type Filter = "all" | "important";

export default function AlertsView() {
  const [filter, setFilter] = useState<Filter>("all");
  const path = `/api/announcements?limit=40${filter === "important" ? "&important_only=true" : ""}`;
  const { data, error } = usePolling<{ announcements: AnnouncementRow[] }>(path, 30_000);

  return (
    <>
      <div className="page-head">
        <h1>Alerts</h1>
        <Segmented
          label="Which announcements"
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: "All" },
            { value: "important", label: "Important" },
          ]}
        />
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2>Exchange announcements</h2>
          <p>Maintenance is always important. Listings and delistings are important when they mention BTC or ETH.</p>
        </div>
        {error ? <p className="error" style={{ padding: "0 20px 16px" }}>{error}</p> : null}
        {!data ? (
          <p className="note" style={{ padding: "0 20px 16px" }}>Loading…</p>
        ) : data.announcements.length === 0 ? (
          <div className="empty">
            <h2>{filter === "important" ? "No important announcements" : "Nothing recorded yet"}</h2>
            <p>
              Start the clerk with <code>uv run python scripts/run_clerk.py</code>. Its first check only
              records what is already there; alerts begin with announcements that appear afterwards.
            </p>
          </div>
        ) : (
          <ul className="alerts">
            {data.announcements.map((a) => (
              <li key={a.url} className={`alert ${a.important ? "important" : ""}`}>
                <div className="alert-head">
                  <span className={`chip cat-${a.category}`}>{a.category}</span>
                  {a.assets.map((asset) => (
                    <span key={asset} className="chip">{asset}</span>
                  ))}
                </div>
                <a className="alert-title" href={safeHref(a.url)} target="_blank" rel="noopener noreferrer">
                  {a.title}
                </a>
                <div className="small muted">
                  {a.source}
                  {a.time ? `, ${utcText(a.time)}` : ""}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}