import { useState } from "react";
import { errorMessage, runOrbitSim, type FlightPattern, type OrbitResponse } from "../api";
import OrbitPlot from "./OrbitPlot";

interface Props {
  dataset: string | null;
}

export default function SimulationPanel({ dataset }: Props) {
  const [running, setRunning] = useState(false);
  const [pattern, setPattern] = useState<FlightPattern>("orbit");
  const [result, setResult] = useState<OrbitResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function runFlight() {
    if (!dataset) return;
    setRunning(true);
    setError(null);
    try {
      setResult(await runOrbitSim(dataset, pattern));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRunning(false);
    }
  }

  return (
    <section>
      <h2>2. Flight simulation</h2>
      <label style={{ marginRight: 12 }}>
        <input
          type="radio"
          checked={pattern === "orbit"}
          onChange={() => setPattern("orbit")}
        />{" "}
        orbit (circle the pile)
      </label>
      <label style={{ marginRight: 12 }}>
        <input
          type="radio"
          checked={pattern === "grid"}
          onChange={() => setPattern("grid")}
        />{" "}
        grid survey (lawnmower coverage)
      </label>
      <br />
      <button onClick={runFlight} disabled={!dataset || running} style={{ marginTop: 8 }}>
        {running ? "Flying…" : "Run flight simulation"}
      </button>
      {!dataset && <p>Select a dataset first.</p>}
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {result && (
        <div>
          <p>
            {result.pattern === "grid" ? "Grid survey" : "Orbit"} for{" "}
            <strong>{result.dataset_id}</strong>: capturing {result.num_triggers} photos —
            one per dataset image (<code>{result.mode}</code> mode).
          </p>
          <OrbitPlot
            dataset={result.dataset_id}
            triggers={result.triggers}
            closePath={result.pattern === "orbit"}
          />
        </div>
      )}
    </section>
  );
}
