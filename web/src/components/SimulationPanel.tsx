import { useState } from "react";
import { errorMessage, runOrbitSim, type OrbitResponse } from "../api";
import OrbitPlot from "./OrbitPlot";

interface Props {
  dataset: string | null;
}

export default function SimulationPanel({ dataset }: Props) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<OrbitResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function runOrbit() {
    if (!dataset) return;
    setRunning(true);
    setError(null);
    try {
      setResult(await runOrbitSim(dataset));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <section>
      <h2>2. Orbit simulation</h2>
      <button onClick={runOrbit} disabled={!dataset || running}>
        {running ? "Flying orbit…" : "Run orbit simulation"}
      </button>
      {!dataset && <p>Select a dataset first.</p>}
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {result && (
        <div>
          <p>
            Orbit for <strong>{result.dataset_id}</strong>: {result.num_triggers}{" "}
            camera triggers (<code>{result.mode}</code> mode).
          </p>
          <OrbitPlot triggers={result.triggers} />
          <pre
            style={{
              maxHeight: 200,
              overflowY: "auto",
              background: "#f5f5f5",
              padding: 8,
              fontSize: 12,
            }}
          >
            {result.logs.join("\n")}
          </pre>
        </div>
      )}
    </section>
  );
}
