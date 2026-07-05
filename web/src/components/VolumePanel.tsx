import { useEffect, useState } from "react";
import {
  errorMessage,
  fileUrl,
  getVolumeJob,
  startVolumeJob,
  type VolumeJob,
} from "../api";
import ReconstructionViewer from "./ReconstructionViewer";

interface Props {
  dataset: string | null;
}

const POLL_INTERVAL_MS = 1500;

export default function VolumePanel({ dataset }: Props) {
  const [job, setJob] = useState<VolumeJob | null>(null);
  const [error, setError] = useState<string | null>(null);

  const running = job !== null && (job.status === "queued" || job.status === "running");

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
      setJob(await startVolumeJob(datasetId));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const result = job?.status === "succeeded" ? job.result : null;

  return (
    <section>
      <h2>3. Reconstruction &amp; volume</h2>
      <button onClick={() => dataset && start(dataset)} disabled={!dataset || running}>
        Run reconstruction &amp; volume
      </button>{" "}
      <button onClick={() => start(dataset ?? undefined)} disabled={running}>
        Run Example Reconstruction
      </button>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {job && running && (
        <p>
          Job <code>{job.job_id}</code> ({job.dataset_id}): <strong>{job.status}</strong>
          {job.progress && <> — {job.progress}</>}
        </p>
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
          <ReconstructionViewer cloudUrl="/volume/files/preview.ply" meshUrl={result.mesh_url} />
        </div>
      )}
    </section>
  );
}
