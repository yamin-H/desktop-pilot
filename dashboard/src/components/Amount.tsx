"use client";

import NumberFlow from "@number-flow/react";
import { amountParts } from "@/lib/amount";
import { withThousands } from "@/lib/format";

// Digits roll when the value changes. If a double could not hold the text exactly,
// the exact text is shown instead (no rolling, no rounding).
export default function Amount({
  text,
  signed = false,
  minDecimals = 2,
}: {
  text: string | null | undefined;
  signed?: boolean;
  minDecimals?: number;
}) {
  if (text === null || text === undefined) return <>—</>;
  const parts = amountParts(text);
  if (!parts) return <>{withThousands(text)}</>;
  const decimals = Math.max(minDecimals, parts.fractionDigits); // extra zeros never change the value
  return (
    <NumberFlow
      value={parts.value}
      locales="en-US"
      format={{
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
        ...(signed ? { signDisplay: "exceptZero" as const } : {}),
      }}
    />
  );
}