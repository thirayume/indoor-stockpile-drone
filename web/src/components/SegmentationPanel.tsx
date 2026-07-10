import { useEffect, useState } from "react";
import { errorMessage, getSegmentJob, startSegmentJob, type SegJob } from "../api";
import ReconstructionViewer from "./ReconstructionViewer";

const POLL_INTERVAL_MS = 1500;

const LEGEND: { key: string; color: string; label: string }[] = [
  { key: "tree", color: "#33b840", label: "tree (green / rough)" },
  { key: "roof", color: "#f28024", label: "roof / building (flat)" },
];

function sumVolume(objects: { label: string; volume_m3: number }[], label: string): number {
  return objects.filter((o) => o.label === label).reduce((a, o) => a + o.volume_m3, 0);
}

/** Segment the current reconstruction into trees/roofs, with counts + volume. */
export default function SegmentationPanel() {
  const [job, setJob] = useState<SegJob | null>(null);
  const [error, setError] = useState<string | null>(null);

  const running = job !== null && (job.status === "queued" || job.status === "running");

  useEffect(() => {
    if (!job || !running) return;
    const timer = setTimeout(async () => {
      try {
        setJob(await getSegmentJob(job.job_id));
      } catch (err) {
        setError(errorMessage(err));
      }
    }, POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [job, running]);

  async function run() {
    setError(null);
    try {
      setJob(await startSegmentJob());
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const result = job?.status === "succeeded" ? job.result : null;

  return (
    <section>
      <h2>4. Segment objects (trees &amp; roofs)</h2>
      <p style={{ fontSize: 13, color: "#666" }}>
        Classifies the latest reconstruction into trees and roofs by shape and
        colour, counts them, and measures each one. Run a reconstruction (step 3)
        first.
      </p>
      <button onClick={run} disabled={running}>
        {running ? "Segmenting…" : "Segment objects"}
      </button>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {job && running && (
        <p>
          <strong>{job.status}</strong>
          {job.progress && <> — {job.progress}</>}
        </p>
      )}
      {job?.status === "failed" && (
        <p style={{ color: "crimson" }}>Segmentation failed: {job.error}</p>
      )}

      {result && (
        <div>
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap", margin: "8px 0" }}>
            {LEGEND.map(({ key, color, label }) => (
              <div key={key} style={{ fontSize: 14 }}>
                <span
                  style={{
                    display: "inline-block",
                    width: 12,
                    height: 12,
                    background: color,
                    borderRadius: 2,
                    marginRight: 6,
                  }}
                />
                <strong>{result.counts[key] ?? 0}</strong> {label}
                {" — "}
                {sumVolume(result.objects, key).toFixed(1)} m³ total
              </div>
            ))}
          </div>
          <ReconstructionViewer
            cloudUrl={result.cloud_url}
            meshUrl={null}
            upVector={result.up_vector}
            cloudLabel={
              <>
                segmented cloud (<code>segmented.ply</code>) — grey ground, green trees, orange roofs
              </>
            }
          />
          <p style={{ fontSize: 12, color: "#888" }}>
            Colours above match the 3D view: ground grey, trees green, roofs
            orange. Volumes are model-units³ unless the model is GPS-scaled.
          </p>
        </div>
      )}
    </section>
  );
}
