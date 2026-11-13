"use client";

import AnnouncementsPanel from "@/components/AnnouncementsPanel";
import ChatPanel from "@/components/ChatPanel";
import MarketPanel from "@/components/MarketPanel";
import PnlPanel from "@/components/PnlPanel";
import { usePolling } from "@/lib/hooks";

export default function Home() {
  const { data: config } = usePolling<{ chat_enabled: boolean }>("/api/config", 60_000);

  return (
    <main>
      <header>
        <h1>DeskPilot</h1>
        <p className="muted">Paper trading desk · read-only · all trades shown are made up</p>
      </header>
      <MarketPanel />
      <PnlPanel />
      <AnnouncementsPanel />
      {config?.chat_enabled ? <ChatPanel /> : null}
    </main>
  );
}