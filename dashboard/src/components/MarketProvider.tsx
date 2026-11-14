"use client";

import {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode,
} from "react";
import { addSnapshot, type History } from "@/lib/history";
import type { Market } from "@/lib/types";

type MarketState = {
  market: Market | null;
  history: History;
  connected: boolean;
  getNow: () => number; // the server's clock, as far as we can tell, in milliseconds
};

const MarketContext = createContext<MarketState>({
  market: null, history: {}, connected: false, getNow: () => Date.now(),
});

// One live connection for the whole app, kept while you move between pages,
// so the chart keeps its history.
export function MarketProvider({ children }: { children: ReactNode }) {
  const [market, setMarket] = useState<Market | null>(null);
  const [history, setHistory] = useState<History>({});
  const [connected, setConnected] = useState(false);
  const offset = useRef<number | null>(null); // server clock minus this computer's clock

  const getNow = useCallback(() => Date.now() + (offset.current ?? 0), []);

  useEffect(() => {
    const source = new EventSource("/api/stream");
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false); // the browser reconnects by itself
    source.addEventListener("market", (event) => {
      try {
        const snapshot = JSON.parse((event as MessageEvent<string>).data) as Market;
        const measured = Date.parse(snapshot.time) - Date.now();
        if (!Number.isNaN(measured)) {
          // Smoothed, so network jitter never makes the chart's clock jump.
          offset.current = offset.current === null ? measured : offset.current + 0.1 * (measured - offset.current);
        }
        setMarket(snapshot);
        setHistory((current) => addSnapshot(current, snapshot));
        setConnected(true);
      } catch {
        // ignore one malformed message
      }
    });
    return () => source.close();
  }, []);

  const value = useMemo(() => ({ market, history, connected, getNow }), [market, history, connected, getNow]);
  return <MarketContext.Provider value={value}>{children}</MarketContext.Provider>;
}

export const useMarket = () => useContext(MarketContext);