import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DeskPilot",
  description: "Live prices, positions and exchange announcements for a paper trading desk",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}