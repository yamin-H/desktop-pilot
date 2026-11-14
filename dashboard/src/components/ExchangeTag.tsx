import { exchangeInfo } from "@/lib/exchanges";

export default function ExchangeTag({ id }: { id: string }) {
  const info = exchangeInfo(id);
  return (
    <span className="tag">
      <span className="swatch" style={{ background: info.color }} />
      {info.name}
    </span>
  );
}