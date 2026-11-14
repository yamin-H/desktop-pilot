import type { Metadata } from "next";
import PortfolioView from "@/components/PortfolioView";

export const metadata: Metadata = { title: "Portfolio" };

export default function Page() {
  return <PortfolioView />;
}