"use client";

import { motion } from "motion/react";
import { useId } from "react";

type Option<T extends string> = { value: T; label: string };

export default function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  const id = useId();
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.value === value ? (
            <motion.span
              layoutId={`seg-pill-${id}`}
              className="seg-pill"
              transition={{ type: "spring", stiffness: 520, damping: 42 }}
            />
          ) : null}
          <span className="seg-label">{option.label}</span>
        </button>
      ))}
    </div>
  );
}