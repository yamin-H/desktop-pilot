"use client";

import { useState, type FormEvent } from "react";
import type { ChatResult } from "@/lib/types";

export default function ChatPanel() {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<ChatResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function ask(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const body = await response.json();
      if (response.ok) setResult(body as ChatResult);
      else setError(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
    } catch {
      setError("cannot reach the server");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2>Ask the assistant</h2>
      <form onSubmit={ask}>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={500}
          rows={2}
          placeholder="What are our positions? What did we make on 2026-11-10?"
        />
        <button type="submit" disabled={busy || question.trim().length < 3}>
          {busy ? "Thinking…" : "Ask"}
        </button>
      </form>
      {error ? <p className="error">{error}</p> : null}
      {result ? (
        <div>
          <div className="answer">{result.answer}</div>
          <p className="muted small">
            Tools used: {result.tools.length ? result.tools.map((t) => `${t.name}${t.ok ? "" : " (error)"}`).join(", ") : "none"}.
            The assistant only reads data: it cannot trade or change records.
          </p>
        </div>
      ) : null}
    </section>
  );
}