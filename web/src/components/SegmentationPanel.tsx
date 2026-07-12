import { useEffect, useState } from "react";
import {
  errorMessage,
  fetchOverlayPhotos,
  fileUrl,
  getSegmentJob,
  photoOverlayUrl,
  startSegmentJob,
  type SegClass,
  type SegJob,
} from "../api";
import { formatMMSS, useElapsedSeconds } from "../progress";
import ReconstructionViewer from "./ReconstructionViewer";

const POLL_INTERVAL_MS = 1500;

const CLASS_LABELS: Record<string, string> = {
  ground: "ground",
  road: "road / paved",
  tree: "tree",
  roof: "roof / building",
  car: "vehicle",
  pile: "pile / stockpile",
  other: "other",
};

/** Default layer visibility: hide the context classes so objects stand out. */
function defaultVisibility(classes: SegClass[]): Record<string, boolean> {
  const vis: Record<string, boolean> = {};
  for (const c of classes) vis[c.key] = c.key !== "ground" && c.key !== "other";
  return vis;
}

/** Segment the reconstruction into classes, with overlays to verify them. */
export default function SegmentationPanel() {
  const [job, setJob] = useState<SegJob | null>(null);
  const [startedAt, setStartedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [photos, setPhotos] = useState<string[]>([]);
  const [photoIdx, setPhotoIdx] = useState(0);

  const running = job !== null && (job.status === "queued" || job.status === "running");
  const elapsed = useElapsedSeconds(startedAt, running);
  const result = job?.status === "succeeded" ? job.result : null;

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

  // When a result lands: reset the class toggles and load the photo list.
  useEffect(() => {
    if (!result) return;
    setVisible(defaultVisibility(result.classes));
    setPhotoIdx(0);
    fetchOverlayPhotos()
      .then(setPhotos)
      .catch(() => setPhotos([]));
  }, [result]);

  async function run() {
    setError(null);
    setStartedAt(new Date().toISOString());
    try {
      setJob(await startSegmentJob());
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const activeKeys = result
    ? result.classes.map((c) => c.key).filter((k) => visible[k])
    : [];
  const photo = photos[photoIdx];

  return (
    <section>
      <h2>4. Segment objects (trees, roofs, roads, vehicles, piles)</h2>
      <p style={{ fontSize: 13, color: "#666" }}>
        Classifies the latest reconstruction by shape and colour, counts the
        objects, and measures each one. The checkboxes below toggle each class
        in <em>all three</em> views — 3D, top-down, and the original photos —
        so you can verify the segmentation against reality. Run a
        reconstruction (step 3) first.
      </p>
      <button onClick={run} disabled={running}>
        {running ? "Segmenting…" : "Segment objects"}
      </button>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {job && running && (
        <p>
          <strong>{job.status}</strong>
          {job.progress && <> — {job.progress}</>} · ⏱ {formatMMSS(elapsed)}
          {" — still working"}
        </p>
      )}
      {job?.status === "failed" && (
        <p style={{ color: "crimson" }}>Segmentation failed: {job.error}</p>
      )}

      {result && (
        <div>
          {/* Class legend: one checkbox per detected class, shared by all views */}
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap", margin: "10px 0" }}>
            {result.classes.map((c) => (
              <label key={c.key} style={{ fontSize: 14, cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={visible[c.key] ?? false}
                  onChange={(e) => setVisible({ ...visible, [c.key]: e.target.checked })}
                />{" "}
                <span
                  style={{
                    display: "inline-block",
                    width: 12,
                    height: 12,
                    background: c.color,
                    borderRadius: 2,
                    margin: "0 4px -1px 2px",
                  }}
                />
                {c.object_count !== null && <strong>{c.object_count} </strong>}
                {CLASS_LABELS[c.key] ?? c.key}
                {c.total_volume_m3 !== null && c.total_volume_m3 > 0 && (
                  <span style={{ color: "#666" }}> — {c.total_volume_m3.toFixed(1)} m³</span>
                )}
              </label>
            ))}
          </div>

          <h3 style={{ marginBottom: 4 }}>3D view</h3>
          <ReconstructionViewer
            meshUrl={null}
            upVector={result.up_vector}
            layers={result.classes
              .filter((c) => c.cloud_url !== null)
              .map((c) => ({
                key: c.key,
                url: c.cloud_url as string,
                visible: visible[c.key] ?? false,
              }))}
          />

          {result.ortho_url && (
            <>
              <h3 style={{ marginBottom: 4 }}>Top-down overview (orthophoto)</h3>
              <p style={{ fontSize: 12, color: "#888", margin: "2px 0 6px" }}>
                All {photos.length || "the"} photos merged into one image via the
                3D model (no stitching needed — the reconstruction already
                aligned them), rendered straight down.
              </p>
              <div style={{ position: "relative", maxWidth: 900 }}>
                <img
                  src={fileUrl(result.ortho_url)}
                  alt="top-down orthophoto"
                  style={{ width: "100%", display: "block", borderRadius: 3 }}
                />
                {result.classes
                  .filter((c) => c.ortho_overlay_url !== null && visible[c.key])
                  .map((c) => (
                    <img
                      key={c.key}
                      src={fileUrl(c.ortho_overlay_url as string)}
                      alt={`${c.key} overlay`}
                      style={{
                        position: "absolute",
                        inset: 0,
                        width: "100%",
                        pointerEvents: "none",
                      }}
                    />
                  ))}
              </div>
            </>
          )}

          {photos.length > 0 && (
            <>
              <h3 style={{ marginBottom: 4 }}>Verify on the original photos</h3>
              <p style={{ fontSize: 12, color: "#888", margin: "2px 0 6px" }}>
                The selected classes are projected back into each photo through
                its camera pose. First view of a photo renders on the server
                (a few seconds), then it is cached.
              </p>
              <div style={{ marginBottom: 6, fontSize: 13 }}>
                <button onClick={() => setPhotoIdx((i) => i - 1)} disabled={photoIdx === 0}>
                  ‹ Prev
                </button>{" "}
                <select
                  value={photoIdx}
                  onChange={(e) => setPhotoIdx(Number(e.target.value))}
                  style={{ margin: "0 6px" }}
                >
                  {photos.map((name, i) => (
                    <option key={name} value={i}>
                      {name}
                    </option>
                  ))}
                </select>
                <button
                  onClick={() => setPhotoIdx((i) => i + 1)}
                  disabled={photoIdx >= photos.length - 1}
                >
                  Next ›
                </button>{" "}
                <span style={{ color: "#888" }}>
                  {photoIdx + 1} / {photos.length}
                </span>
              </div>
              {photo && (
                <img
                  key={`${photo}-${activeKeys.join(",")}`}
                  src={photoOverlayUrl(photo, activeKeys, 1200)}
                  alt={`segmentation overlay on ${photo}`}
                  style={{ maxWidth: 900, width: "100%", borderRadius: 3 }}
                />
              )}
            </>
          )}

          <p style={{ fontSize: 12, color: "#888" }}>
            Same colours in every view. Volumes are model-units³ unless the
            model is GPS-scaled (then true m³). Counting uses shape + colour
            heuristics — verify with the photo overlay before trusting counts.
          </p>
        </div>
      )}
    </section>
  );
}
