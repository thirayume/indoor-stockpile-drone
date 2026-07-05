import { useEffect, useState } from "react";
import type { CameraTrigger } from "../api";

interface Props {
  triggers: CameraTrigger[];
  /** Close the path back to the first point (true for orbits, false for grid surveys). */
  closePath?: boolean;
}

const SIZE = 340;
const PAD = 34;
const STEP_MS = 400;

/** Top-down view of the flight: path, camera poses, one-shot shutter replay. */
export default function OrbitPlot({ triggers, closePath = true }: Props) {
  const [active, setActive] = useState(0);
  const [playing, setPlaying] = useState(true);

  // Restart the replay whenever a new flight arrives.
  useEffect(() => {
    setActive(0);
    setPlaying(true);
  }, [triggers]);

  // Step through the shutter sequence once, then stop on the last frame.
  useEffect(() => {
    if (!playing || triggers.length === 0) return;
    const timer = setInterval(() => {
      setActive((a) => {
        if (a + 1 >= triggers.length) {
          setPlaying(false);
          return a;
        }
        return a + 1;
      });
    }, STEP_MS);
    return () => clearInterval(timer);
  }, [playing, triggers]);

  if (triggers.length === 0) return null;

  const maxRadius = Math.max(...triggers.map((t) => Math.hypot(t.north_m, t.east_m)), 1);
  const scale = (SIZE / 2 - PAD) / maxRadius;
  // Screen mapping: x = east, y = -north (north points up).
  const sx = (t: CameraTrigger) => SIZE / 2 + t.east_m * scale;
  const sy = (t: CameraTrigger) => SIZE / 2 - t.north_m * scale;
  const current = triggers[active];
  const pathPoints = triggers.map((t) => `${sx(t)},${sy(t)}`).join(" ");

  return (
    <figure style={{ margin: "12px 0" }}>
      <svg width={SIZE} height={SIZE} style={{ background: "#fafafa", border: "1px solid #ddd" }}>
        {/* stockpile at the centre */}
        <circle cx={SIZE / 2} cy={SIZE / 2} r={14} fill="#c8a165" />
        <text x={SIZE / 2} y={SIZE / 2 + 4} textAnchor="middle" fontSize={9} fill="#5a4632">
          pile
        </text>
        {/* flight path */}
        {closePath ? (
          <polygon points={pathPoints} fill="none" stroke="#9bc" strokeDasharray="4 3" />
        ) : (
          <polyline points={pathPoints} fill="none" stroke="#9bc" strokeDasharray="4 3" />
        )}
        {triggers.map((t) => {
          // yaw 0° = north, growing clockwise
          const hx = sx(t) + Math.sin((t.yaw_deg * Math.PI) / 180) * 15;
          const hy = sy(t) - Math.cos((t.yaw_deg * Math.PI) / 180) * 15;
          const done = t.index <= active;
          const isActive = t.index === active && playing;
          return (
            <g key={t.index}>
              <line x1={sx(t)} y1={sy(t)} x2={hx} y2={hy} stroke={isActive ? "#e33" : "#aaa"} />
              <circle
                cx={sx(t)}
                cy={sy(t)}
                r={isActive ? 7 : 4}
                fill={isActive ? "#e33" : done ? "#36c" : "#bbb"}
              >
                <title>{`#${t.index}  N ${t.north_m.toFixed(2)} m  E ${t.east_m.toFixed(2)} m  alt ${t.up_m.toFixed(1)} m  yaw ${t.yaw_deg.toFixed(0)}°`}</title>
              </circle>
            </g>
          );
        })}
        <text x={8} y={16} fontSize={11} fill="#666">
          top view — north is up
        </text>
      </svg>
      <figcaption style={{ fontSize: 12, color: "#666" }}>
        {playing ? (
          <>
            📷 shutter #{current.index}: N {current.north_m.toFixed(2)} m, E{" "}
            {current.east_m.toFixed(2)} m, alt {current.up_m.toFixed(1)} m — the line shows where
            the camera points. Hover any dot for its pose.
          </>
        ) : (
          <>
            ✅ flight complete — {triggers.length} photos captured.{" "}
            <button
              onClick={() => {
                setActive(0);
                setPlaying(true);
              }}
            >
              ⟳ Replay
            </button>
          </>
        )}
      </figcaption>
    </figure>
  );
}
