import type { Metadata } from "next";
import { IBM_Plex_Sans } from "next/font/google";
import Shell from "@/components/Shell";
import "./globals.css";

// If the font cannot be downloaded (offline build), delete these lines and the `className`
// below: the stylesheet falls back to the system font.
const plex = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-ui",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "DeskPilot", template: "%s | DeskPilot" },
  description: "Live prices, positions and exchange announcements for a paper trading desk",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={plex.variable}>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}