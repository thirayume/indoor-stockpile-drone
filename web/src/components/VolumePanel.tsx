import { useState } from "react";
import {
  errorMessage,
  fileUrl,
  runExampleReconstruction,
  runVolume,
  type ExampleResponse,
  type VolumeResponse,
} from "../api";

interface Props {
  dataset: string | null;
}

export default function VolumePanel({ dataset }: Props) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<VolumeResponse | null>(null);
  const [example, setExample] = useState<ExampleResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    if (!dataset) return;
    setRunning(true);
    setError(null);
    try {
      setResult(await runVolume(dataset));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRunning(false);
    }
  }

  async function runExample() {
    setRunning(true);
    setError(null);
    try {
      // Uses the selected dataset when there is one; the backend
      // defaults to 'banana' otherwise.
      setExample(await runExampleReconstruction(dataset ?? undefined));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <section>
      <h2>3. Reconstruction &amp; volume</h2>
      <button onClick={run} disabled={!dataset || running}>
        {running ? "Running… (this can take a while)" : "Run reconstruction & volume"}
      </button>{" "}
      <button onClick={runExample} disabled={running}>
        Run Example Reconstruction
      </button>
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {example && (
        <p>
          Example (<strong>{example.dataset_id}</strong>, {example.status}):{" "}
          <strong>{example.volume_m3.toFixed(2)} m³</strong> —{" "}
          <a href={fileUrl(example.ply_url)} download>
            Download merged.ply
          </a>{" "}
          (<code>{example.ply_path}</code>)
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
        </div>
      )}
    </section>
  );
}
