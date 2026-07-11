import { useEffect, useState } from "react";
import {
  datasetImageUrl,
  errorMessage,
  fetchDatasetInfo,
  runOrbitSim,
  type FlightPattern,
  type OrbitResponse,
} from "../api";
import Lightbox from "./Lightbox";
import OrbitPlot from "./OrbitPlot";

interface Props {
  dataset: string | null;
}

const ALL_PATTERNS: FlightPattern[] = ["orbit", "grid"];
const GALLERY_PAGE_SIZE = 20;

export default function SimulationPanel({ dataset }: Props) {
  const [running, setRunning] = useState(false);
  const [pattern, setPattern] = useState<FlightPattern>("orbit");
  const [allowed, setAllowed] = useState<FlightPattern[]>(ALL_PATTERNS);
  const [result, setResult] = useState<OrbitResponse | null>(null);
  const [complete, setComplete] = useState(false);
  const [lightbox, setLightbox] = useState<number | null>(null);
  const [page, setPage] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // Restrict the flight pattern to what suits the dataset: aerial surveys
  // (GPS) -> grid, close-up object scans -> orbit.
  useEffect(() => {
    if (!dataset) {
      setAllowed(ALL_PATTERNS);
      return;
    }
    fetchDatasetInfo(dataset)
      .then((info) => {
        const patterns = info.patterns.length ? info.patterns : ALL_PATTERNS;
        setAllowed(patterns);
        setPattern((p) => (patterns.includes(p) ? p : patterns[0]));
      })
      .catch(() => setAllowed(ALL_PATTERNS));
  }, [dataset]);

  async function runFlight() {
    if (!dataset) return;
    setRunning(true);
    setError(null);
    setComplete(false);
    setLightbox(null);
    setPage(0);
    try {
      setResult(await runOrbitSim(dataset, pattern));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setRunning(false);
    }
  }

  const images = result ? result.triggers.map((t) => t.image) : [];

  return (
    <section>
      <h2>2. Flight simulation</h2>
      <label style={{ marginRight: 12, opacity: allowed.includes("orbit") ? 1 : 0.4 }}>
        <input
          type="radio"
          checked={pattern === "orbit"}
          disabled={!allowed.includes("orbit")}
          onChange={() => setPattern("orbit")}
        />{" "}
        orbit (circle the pile)
      </label>
      <label style={{ marginRight: 12, opacity: allowed.includes("grid") ? 1 : 0.4 }}>
        <input
          type="radio"
          checked={pattern === "grid"}
          disabled={!allowed.includes("grid")}
          onChange={() => setPattern("grid")}
        />{" "}
        grid survey (lawnmower coverage)
      </label>
      {dataset && allowed.length === 1 && (
        <span style={{ fontSize: 12, color: "#888" }}>
          {" "}
          — {allowed[0] === "grid" ? "aerial survey (grid)" : "object scan (orbit)"} for this dataset
        </span>
      )}
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
            triggers={result.triggers}
            closePath={result.pattern === "orbit"}
            onComplete={() => setComplete(true)}
          />

          {complete &&
            (() => {
              const pageCount = Math.ceil(images.length / GALLERY_PAGE_SIZE);
              const start = page * GALLERY_PAGE_SIZE;
              const pageImages = images.slice(start, start + GALLERY_PAGE_SIZE);
              return (
                <div>
                  <p style={{ fontSize: 13, color: "#444" }}>
                    📸 {images.length} photos captured — showing {start + 1}–
                    {start + pageImages.length}. Click any to view full size:
                  </p>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {pageImages.map((name, idx) => (
                      <img
                        key={name}
                        src={datasetImageUrl(result.dataset_id, name, 200)}
                        alt={name}
                        title={name}
                        loading="lazy"
                        onClick={() => setLightbox(start + idx)}
                        style={{ height: 92, borderRadius: 3, cursor: "pointer", display: "block" }}
                      />
                    ))}
                  </div>
                  {pageCount > 1 && (
                    <div style={{ marginTop: 8, fontSize: 13 }}>
                      <button onClick={() => setPage((p) => p - 1)} disabled={page === 0}>
                        ‹ Prev
                      </button>{" "}
                      <span style={{ margin: "0 8px" }}>
                        Page {page + 1} of {pageCount}
                      </span>
                      <button
                        onClick={() => setPage((p) => p + 1)}
                        disabled={page >= pageCount - 1}
                      >
                        Next ›
                      </button>
                    </div>
                  )}
                  <Lightbox
                    images={images}
                    index={lightbox}
                    srcFor={(name) => datasetImageUrl(result.dataset_id, name, 1600)}
                    onIndexChange={setLightbox}
                    onClose={() => setLightbox(null)}
                  />
                </div>
              );
            })()}
        </div>
      )}
    </section>
  );
}
