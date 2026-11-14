"use client";

import React, { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { usePolling } from "@/lib/hooks";
import type { ChatResult } from "@/lib/types";

type Turn = { id: number; question: string; answer?: string; tools?: ChatResult["tools"]; error?: string };

const EXAMPLES = [
  "What are our current positions?",
  "What realized profit did we make on 2026-11-10?",
  "Check binance_2026-11-10_with_errors.csv for 2026-11-10 on Binance.",
  "What do our runbooks say about a missing_in_ledger break?",
];

// Helper to format inline bold, code, and italics
function renderInline(text: string): React.ReactNode[] {
  const tokens: React.ReactNode[] = [];
  const regex = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      tokens.push(text.slice(lastIndex, match.index));
    }
    const token = match[0];
    if (token.startsWith("**") && token.endsWith("**")) {
      tokens.push(<strong key={match.index} style={{ fontWeight: 600 }}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`") && token.endsWith("`")) {
      tokens.push(
        <code
          key={match.index}
          style={{
            background: "rgba(128,128,128,0.12)",
            padding: "2px 6px",
            borderRadius: 4,
            fontSize: "0.88em",
            fontFamily: "monospace",
          }}
        >
          {token.slice(1, -1)}
        </code>
      );
    } else if (token.startsWith("*") && token.endsWith("*")) {
      tokens.push(<em key={match.index}>{token.slice(1, -1)}</em>);
    }
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    tokens.push(text.slice(lastIndex));
  }
  return tokens.length > 0 ? tokens : [text];
}

// Formats full assistant responses: Tables, lists, headings, and paragraphs
function FormattedAnswer({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i++;
      continue;
    }

    // Markdown Table (lines starting and ending with |)
    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("|") && lines[i].trim().endsWith("|")) {
        tableLines.push(lines[i].trim());
        i++;
      }

      if (tableLines.length >= 2) {
        const headerCells = tableLines[0].split("|").slice(1, -1).map((c) => c.trim());
        const isSeparator = /^\|[\s\-:|]+\|$/.test(tableLines[1]);
        const bodyLines = isSeparator ? tableLines.slice(2) : tableLines.slice(1);
        const rows = bodyLines.map((l) => l.split("|").slice(1, -1).map((c) => c.trim()));

        blocks.push(
          <div
            key={`table-${blocks.length}`}
            style={{
              overflowX: "auto",
              margin: "12px 0",
              borderRadius: "8px",
              border: "1px solid var(--line)",
              background: "var(--paper, #fff)",
            }}
          >
            <table className="table" style={{ width: "100%", margin: 0, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ background: "rgba(128,128,128,0.06)" }}>
                  {headerCells.map((header, idx) => (
                    <th key={idx} style={{ padding: "8px 14px", fontWeight: 600 }}>
                      {renderInline(header)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, rIdx) => (
                  <tr key={rIdx}>
                    {row.map((cell, cIdx) => (
                      <td key={cIdx} style={{ padding: "8px 14px" }}>
                        {renderInline(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
        continue;
      }
    }

    // Bullet Lists (* or -)
    if (/^[\*\-•]\s+/.test(trimmed)) {
      const listItems: string[] = [];
      while (i < lines.length && /^[\*\-•]\s+/.test(lines[i].trim())) {
        listItems.push(lines[i].trim().replace(/^[\*\-•]\s+/, ""));
        i++;
      }
      blocks.push(
        <ul
          key={`list-${blocks.length}`}
          style={{
            margin: "8px 0 12px 20px",
            padding: 0,
            display: "grid",
            gap: "6px",
            lineHeight: 1.5,
          }}
        >
          {listItems.map((item, idx) => (
            <li key={idx}>{renderInline(item)}</li>
          ))}
        </ul>
      );
      continue;
    }

    // Numbered Lists (1. 2. etc.)
    if (/^\d+\.\s+/.test(trimmed)) {
      const listItems: string[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        listItems.push(lines[i].trim().replace(/^\d+\.\s+/, ""));
        i++;
      }
      blocks.push(
        <ol
          key={`ol-${blocks.length}`}
          style={{
            margin: "8px 0 12px 20px",
            padding: 0,
            display: "grid",
            gap: "6px",
            lineHeight: 1.5,
          }}
        >
          {listItems.map((item, idx) => (
            <li key={idx}>{renderInline(item)}</li>
          ))}
        </ol>
      );
      continue;
    }

    // Standalone bold line as heading (e.g. **Current positions**)
    if (/^\*\*[^*]+\*\*$/.test(trimmed)) {
      const heading = trimmed.slice(2, -2);
      blocks.push(
        <h4 key={`h-${blocks.length}`} style={{ margin: "10px 0 4px", fontSize: "15px", fontWeight: 600 }}>
          {heading}
        </h4>
      );
      i++;
      continue;
    }

    // Regular paragraphs
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].trim().startsWith("|") &&
      !/^[\*\-•]\s+/.test(lines[i].trim()) &&
      !/^\d+\.\s+/.test(lines[i].trim()) &&
      !/^\*\*[^*]+\*\*$/.test(lines[i].trim())
    ) {
      paraLines.push(lines[i].trim());
      i++;
    }

    if (paraLines.length > 0) {
      blocks.push(
        <p key={`p-${blocks.length}`} style={{ margin: "6px 0", lineHeight: 1.55 }}>
          {renderInline(paraLines.join(" "))}
        </p>
      );
    }
  }

  return <div style={{ display: "grid", gap: "4px" }}>{blocks}</div>;
}

export default function AssistantView() {
  const { data: config } = usePolling<{ chat_enabled: boolean }>("/api/config", 60_000);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const counter = useRef(0);
  const end = useRef<HTMLDivElement>(null);

  // Smooth auto-scroll that triggers whenever a question is submitted or response arrives
  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    setTimeout(() => {
      end.current?.scrollIntoView({ behavior, block: "end" });
    }, 60);
  };

  useEffect(() => {
    scrollToBottom();
  }, [turns]);

  async function ask(question: string) {
    const trimmed = question.trim();
    if (trimmed.length < 3 || busy) return;
    const id = ++counter.current;
    setTurns((current) => [...current, { id, question: trimmed }]);
    setText("");
    setBusy(true);
    scrollToBottom();

    const update = (change: Partial<Turn>) => {
      setTurns((current) => current.map((turn) => (turn.id === id ? { ...turn, ...change } : turn)));
      scrollToBottom();
    };

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });
      const body = await response.json();
      if (response.ok) update({ answer: (body as ChatResult).answer, tools: (body as ChatResult).tools });
      else update({ error: typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}` });
    } catch {
      update({ error: "Can't reach the server." });
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void ask(text);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void ask(text);
    }
  }

  if (config && !config.chat_enabled) {
    return (
      <>
        <div className="page-head"><h1>Assistant</h1></div>
        <section className="panel empty">
          <h2>The assistant is switched off</h2>
          <p>
            Set <code>API_ENABLE_CHAT=true</code>, <code>LLM_API_KEY</code> and <code>LLM_MODEL</code> in{" "}
            <code>.env</code>, then restart <code>make api</code>. Chat is off by default because every
            question costs money.
          </p>
        </section>
      </>
    );
  }

  return (
    <>
      <div className="page-head"><h1>Assistant</h1></div>

      {turns.length === 0 ? (
        <div className="stack">
          <p className="note">
            Ask about trades, positions, profit, prices, exchange statements or our runbooks. Every number
            in an answer comes from a tool, never from the model. Each question is answered on its own: the
            assistant does not remember earlier ones.
          </p>
          <div className="suggestions">
            {EXAMPLES.map((example) => (
              <button key={example} type="button" className="suggest" disabled={busy || !config} onClick={() => void ask(example)}>
                {example}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="convo" aria-live="polite">
          {turns.map((turn) => (
            <div className="turn" key={turn.id}>
              <div className="q">{turn.question}</div>
              {turn.error ? (
                <div className="a err">{turn.error}</div>
              ) : turn.answer !== undefined ? (
                <>
                  <div className="a" style={{ whiteSpace: "normal" }}>
                    <FormattedAnswer text={turn.answer} />
                  </div>
                  <div className="tools">
                    {turn.tools && turn.tools.length > 0 ? (
                      <>
                        Used
                        {turn.tools.map((tool, index) => (
                          <span key={index} className="chip">{tool.name}{tool.ok ? "" : " (error)"}</span>
                        ))}
                      </>
                    ) : (
                      "Answered without tools"
                    )}
                  </div>
                </>
              ) : (
                <div className="a muted">Working on it…</div>
              )}
            </div>
          ))}
          <div ref={end} style={{ height: "1px", scrollMarginBottom: "140px" }} />
        </div>
      )}

      <div className="composer">
        <form onSubmit={submit}>
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={onKeyDown}
            maxLength={500}
            rows={1}
            aria-label="Your question"
            placeholder="Ask a question"
            disabled={!config}
          />
          <button className="btn" type="submit" disabled={busy || !config || text.trim().length < 3}>
            {busy ? "Working…" : "Ask"}
          </button>
        </form>
        <p className="note">The assistant only reads data. It cannot trade or change records.</p>
      </div>
    </>
  );
}