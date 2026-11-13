"use client";

import { safeHref } from "@/lib/format";
import { usePolling } from "@/lib/hooks";
import type { AnnouncementRow } from "@/lib/types";

export default function AnnouncementsPanel() {
  const { data, error } = usePolling<{ announcements: AnnouncementRow[] }>("/api/announcements?limit=15", 30_000);

  return (
    <section>
      <h2>Exchange announcements</h2>
      {error ? <p className="error">{error}</p> : null}
      {!data ? (
        <p className="muted">Loading…</p>
      ) : data.announcements.length === 0 ? (
        <p className="muted">Nothing recorded yet. Is the clerk running?</p>
      ) : (
        <ul className="list">
          {data.announcements.map((a) => (
            <li key={a.url} className={a.important ? "important" : ""}>
              <span className={`badge cat-${a.category}`}>{a.category}</span>{" "}
              <a href={safeHref(a.url)} target="_blank" rel="noopener noreferrer">{a.title}</a>{" "}
              <span className="muted small">
                {a.source}{a.assets.length ? ` · ${a.assets.join(", ")}` : ""}{a.time ? ` · ${a.time.slice(0, 16).replace("T", " ")} UTC` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}