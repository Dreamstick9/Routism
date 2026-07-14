"use client";

import { useEffect, useState } from "react";
import { filterReservedWorkers, getPool } from "@/lib/api";

// Footer chip: live "N/5 providers connected" from the user-visible pool
// (engine-reserved models are excluded so they never consume a UI slot).
export default function PoolChip() {
  const [size, setSize] = useState<number | null>(null);
  const [capacity, setCapacity] = useState(5);

  useEffect(() => {
    let active = true;
    getPool()
      .then((p) => {
        if (!active) return;
        setSize(filterReservedWorkers(p).length);
        setCapacity(p.capacity ?? 5);
      })
      .catch(() => {
        if (active) setSize(null);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <span className="chip">
      <span
        className={`h-1.5 w-1.5 rounded-full ${
          size === null
            ? "bg-[var(--muted-soft)]"
            : size > 0
              ? "bg-[var(--good)]"
              : "bg-[var(--muted-soft)]"
        }`}
        aria-hidden
      />
      {size === null
        ? `—/${capacity} providers`
        : `${size}/${capacity} providers connected`}
    </span>
  );
}
