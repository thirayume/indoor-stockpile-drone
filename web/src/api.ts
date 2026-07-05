// Thin typed client for the FastAPI backend. All calls go through /api,
// which the Vite dev server proxies to the backend (see vite.config.ts).

export interface OrbitResponse {
  dataset_id: string;
  mode: string;
  num_triggers: number;
  logs: string[];
}

export interface VolumeResponse {
  volume_m3: number;
  num_points: number;
  method: string;
  point_cloud_path: string;
  point_cloud_url: string;
  mesh_path: string | null;
  mesh_url: string | null;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export interface VolumeJob {
  job_id: string;
  kind: string;
  dataset_id: string;
  status: JobStatus;
  progress: string | null;
  error: string | null;
  result: VolumeResponse | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

const API_BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    // FastAPI puts human-readable error messages in {"detail": ...}
    const detail: string | null = await res
      .json()
      .then((body) => (typeof body?.detail === "string" ? body.detail : null))
      .catch(() => null);
    throw new Error(detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function fetchDatasets(): Promise<string[]> {
  return request<{ datasets: string[] }>("/datasets").then((body) => body.datasets);
}

export function runOrbitSim(datasetId: string): Promise<OrbitResponse> {
  return post<OrbitResponse>("/sim/orbit", { dataset_id: datasetId });
}

/** Queue a reconstruction job; backend defaults to the example dataset. */
export function startVolumeJob(datasetId?: string): Promise<VolumeJob> {
  return post<VolumeJob>("/volume/jobs", datasetId ? { dataset_id: datasetId } : {});
}

export function getVolumeJob(jobId: string): Promise<VolumeJob> {
  return request<VolumeJob>(`/volume/jobs/${jobId}`);
}

/** Turn a backend-relative download URL (e.g. /volume/files/x.ply) into a link href. */
export function fileUrl(url: string): string {
  return `${API_BASE}${url}`;
}

export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
