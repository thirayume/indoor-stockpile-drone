import { useEffect, useState } from "react";

/** Seconds elapsed since an ISO timestamp, ticking every second while active. */
export function useElapsedSeconds(startedAtIso: string | null, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  if (!startedAtIso) return 0;
  return Math.max(0, Math.floor((now - new Date(startedAtIso).getTime()) / 1000));
}

/** "M:SS" for a duration in seconds. */
export function formatMMSS(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Very rough OpenSfM reconstruction time (s) from image count.
 *  Per-image work (features + depthmaps) is ~linear; matching is ~O(n²).
 *  Calibrated loosely to observed runs (banana ~16 imgs, toledo ~87). */
export function estimateReconstructionSeconds(numImages: number): number {
  if (numImages <= 0) return 0;
  return Math.round(15 * numImages + 0.1 * numImages * numImages);
}
