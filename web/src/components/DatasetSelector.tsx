import { useEffect, useState } from "react";
import { errorMessage, fetchDatasets } from "../api";

interface Props {
  selected: string | null;
  onSelect: (dataset: string) => void;
}

export default function DatasetSelector({ selected, onSelect }: Props) {
  const [datasets, setDatasets] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDatasets()
      .then(setDatasets)
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

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
    </section>
  );
}
