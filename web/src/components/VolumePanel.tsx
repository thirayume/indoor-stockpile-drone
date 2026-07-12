import { useEffect, useState } from "react";
import {
  errorMessage,
  fetchDatasetInfo,
  fileUrl,
  getVolumeJob,
  startVolumeJob,
  type VolumeJob,
} from "../api";
import { estimateReconstructionSeconds, formatMMSS, useElapsedSeconds } from "../progress";
import ReconstructionViewer from "./ReconstructionViewer";

interface Props {
  dataset: string | null;
}

const POLL_INTERVAL_MS = 1500;

export default function VolumePanel({ dataset }: Props) {
  const [job, setJob] = useState<VolumeJob | null>(null);
  const [useExifGps, setUseExifGps] = useState(false);
  const [imageCount, setImageCount] = useState(0);
  const [hasGps, setHasGps] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  const running = job !== null && (job.status === "queued" || job.status === "running");
  const elapsed = useElapsedSeconds(job?.started_at ?? null, running);

  // Image count drives the rough time estimate; has_gps gates the GPS toggle.
  useEffect(() => {
    if (!dataset) {
      setHasGps(null);
      return;
    }
    fetchDatasetInfo(dataset)
      .then((info) => {
        setImageCount(info.image_count);
        setHasGps(info.has_gps);
        // A dataset without GPS cannot use it — drop a stale tick.
        if (!info.has_gps) setUseExifGps(false);
      })
      .catch(() => {
        setImageCount(0);
        setHasGps(null);
      });
  }, [dataset]);

  // Poll the active job; each state update schedules the next poll, and no
  // timer is armed once the job reaches a terminal state.
  useEffect(() => {
    if (!job || !running) return;
    const timer = setTimeout(async () => {
      try {
        setJob(await getVolumeJob(job.job_id));
      } catch (err) {
        setError(errorMessage(err));
      }
    }, POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [job, running]);

  async function start(datasetId?: string) {
    setError(null);
    try {
      setJob(await startVolumeJob(datasetId, useExifGps));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const result = job?.status === "succeeded" ? job.result : null;

  return (
    <section>
      <h2>3. Reconstruction &amp; volume</h2>
      <label
        style={{
          display: "block",
          fontSize: 13,
          marginBottom: 8,
          opacity: hasGps === false ? 0.5 : 1,
        }}
      >
        <input
          type="checkbox"
          checked={useExifGps}
          onChange={(e) => setUseExifGps(e.target.checked)}
          disabled={running || hasGps === false}
        />{" "}
        Use GPS from EXIF — georeferenced, true-metre scale.{" "}
        {hasGps === false ? (
          <span>
            This dataset's photos carry no GPS — reconstruction runs fully
            GPS-denied (results in model units).
          </span>
        ) : (
          <span>
            Off (default): GPS in the photos is ignored and the reconstruction
            is GPS-denied — the choice is always yours, never automatic.
          </span>
        )}
      </label>
      <button onClick={() => dataset && start(dataset)} disabled={!dataset || running}>
        Run reconstruction &amp; volume
      </button>{" "}
      <button onClick={() => start(dataset ?? undefined)} disabled={running}>
        Run Example Reconstruction
      </button>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {job && running && (
        <div style={{ margin: "6px 0" }}>
          <p style={{ margin: "2px 0" }}>
            Job <code>{job.job_id}</code> ({job.dataset_id}): <strong>{job.status}</strong>
            {job.progress && <> — {job.progress}</>}
          </p>
          <p style={{ margin: "2px 0", fontSize: 13, color: "#555" }}>
            ⏱ elapsed <strong>{formatMMSS(elapsed)}</strong>
            {imageCount > 0 &&
              (() => {
                const est = estimateReconstructionSeconds(imageCount);
                const remaining = est - elapsed;
                return remaining > 5 ? (
                  <> · ~{formatMMSS(remaining)} remaining (rough, {imageCount} photos)</>
                ) : (
                  <> · finishing up (taking longer than estimated for {imageCount} photos)</>
                );
              })()}
            {" — still working, don't refresh"}
          </p>
        </div>
      )}
      {job?.status === "failed" && (
        <p style={{ color: "crimson" }}>
          Job <code>{job.job_id}</code> failed: {job.error}
        </p>
      )}
      {result && (
        <div>
          <p>
            Estimated volume: <strong>{result.volume_m3.toFixed(2)} m³</strong>{" "}
            ({result.num_points} points, <code>{result.method}</code> method)
          </p>
          <p>
            <a href={fileUrl(result.point_cloud_url)} download>
              Download point cloud
            </a>{" "}
            (<code>{result.point_cloud_path}</code>)
          </p>
          {result.mesh_url && (
            <p>
              <a href={fileUrl(result.mesh_url)} download>
                Download stockpile mesh
              </a>{" "}
              (<code>{result.mesh_path}</code>)
            </p>
          )}
          <ReconstructionViewer
            cloudUrl="/volume/files/preview.ply"
            meshUrl={result.mesh_url}
            upVector={result.up_vector}
          />
        </div>
      )}
    </section>
  );
}
