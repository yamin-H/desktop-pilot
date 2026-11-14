"use client";

import { MotionConfig, motion } from "motion/react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import HealthStatus from "./HealthStatus";
import { MarketProvider } from "./MarketProvider";

const NAV = [
  { href: "/", label: "Market" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/alerts", label: "Alerts" },
  { href: "/assistant", label: "Assistant" },
];

// Two prices that move apart and together: the whole product in one mark.
function Logo() {
  const stroke = { fill: "none", strokeWidth: 2.4, strokeLinecap: "round", strokeLinejoin: "round" } as const;
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
      <path d="M3 20 L10 14 L16 17 L25 6" stroke="var(--binance)" {...stroke} />
      <path d="M3 10 L10 15 L16 9 L25 13" stroke="var(--kraken)" {...stroke} />
    </svg>
  );
}

export default function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <MarketProvider>
      <MotionConfig reducedMotion="user">
        <div className="shell">
          <aside className="side">
            <Link href="/" className="brand">
              <Logo />
              <span>DeskPilot</span>
            </Link>
            <nav className="nav" aria-label="Main">
              {NAV.map((item) => {
                const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
                return (
                  <Link key={item.href} href={item.href} aria-current={active ? "page" : undefined}>
                    {active ? (
                      <motion.span
                        layoutId="nav-pill"
                        className="nav-pill"
                        transition={{ type: "spring", stiffness: 520, damping: 42 }}
                      />
                    ) : null}
                    <span className="nav-label">{item.label}</span>
                  </Link>
                );
              })}
            </nav>
            <HealthStatus />
          </aside>
          <main className="main">{children}</main>
        </div>
      </MotionConfig>
    </MarketProvider>
  );
}