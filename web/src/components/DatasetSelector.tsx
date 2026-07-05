import { useEffect, useState } from "react";
import { datasetImageUrl, errorMessage, fetchDatasetImages, fetchDatasets } from "../api";

interface Props {
  selected: string | null;
  onSelect: (dataset: string) => void;
}

export default function DatasetSelector({ selected, onSelect }: Props) {
  const [datasets, setDatasets] = useState<string[]>([]);
  const [images, setImages] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDatasets()
      .then(setDatasets)
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selected) {
      setImages([]);
      return;
    }
    fetchDatasetImages(selected)
      .then(setImages)
      .catch(() => setImages([]));
  }, [selected]);

  return (
    <section>
      <h2>1. Dataset</h2>
      {loading && <p>Loading datasets…</p>}
      {error && <p style={{ color: "crimson" }}>Failed to load datasets: {error}</p>}
      {!loading && !error && datasets.length === 0 && (
        <p>
          No datasets found under <code>data/odm/</code> — see the README for
          how to clone one (e.g. <code>odm_data_aukerman</code>).
        </p>
      )}
      <select
        value={selected ?? ""}
        onChange={(e) => onSelect(e.target.value)}
        disabled={loading || datasets.length === 0}
      >
        <option value="" disabled>
          Select a dataset…
        </option>
        {datasets.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
      {selected && images.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <p style={{ fontSize: 13, color: "#444" }}>
            {images.length} input photos — these are what the drone "captured" and what the
            reconstruction is computed from (click to open full size):
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, maxHeight: 230, overflowY: "auto" }}>
            {images.map((name) => (
              <a key={name} href={datasetImageUrl(selected, name)} target="_blank" rel="noreferrer">
                <img
                  src={datasetImageUrl(selected, name, 200)}
                  alt={name}
                  title={name}
                  loading="lazy"
                  style={{ height: 96, borderRadius: 3, display: "block" }}
                />
              </a>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
