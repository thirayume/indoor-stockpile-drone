import { useState } from "react";
import DatasetSelector from "./components/DatasetSelector";
import SegmentationPanel from "./components/SegmentationPanel";
import SimulationPanel from "./components/SimulationPanel";
import VolumePanel from "./components/VolumePanel";

export default function App() {
  const [dataset, setDataset] = useState<string | null>(null);

  return (
    <main
      style={{
        maxWidth: 720,
        margin: "0 auto",
        padding: 24,
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <h1>Indoor Stockpile Drone</h1>
      <p>
        Simulated GPS-denied drone flights, photogrammetry and stockpile volume
        estimation.
      </p>
      <DatasetSelector selected={dataset} onSelect={setDataset} />
      <SimulationPanel dataset={dataset} />
      <VolumePanel dataset={dataset} />
      <SegmentationPanel />
    </main>
  );
}
