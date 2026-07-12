// Thin typed client for the FastAPI backend. All calls go through /api,
// which the Vite dev server proxies to the backend (see vite.config.ts).

export interface CameraTrigger {
  index: number;
  north_m: number;
  east_m: number;
  up_m: number;
  yaw_deg: number;
  image: string;
}

export type FlightPattern = "orbit" | "grid";

export interface OrbitResponse {
  dataset_id: string;
  mode: string;
  pattern: FlightPattern;
  num_triggers: number;
  triggers: CameraTrigger[];
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
  up_vector: number[] | null;
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

export function fetchDatasetImages(datasetId: string): Promise<string[]> {
  return request<{ images: string[] }>(
    `/datasets/${encodeURIComponent(datasetId)}/images`
  ).then((body) => body.images);
}

export interface DatasetInfo {
  dataset_id: string;
  image_count: number;
  has_gps: boolean;
  patterns: FlightPattern[];
}

export function fetchDatasetInfo(datasetId: string): Promise<DatasetInfo> {
  return request<DatasetInfo>(`/datasets/${encodeURIComponent(datasetId)}/info`);
}

/** URL of one dataset image; pass width for a server-side thumbnail. */
export function datasetImageUrl(datasetId: string, name: string, width?: number): string {
  const suffix = width ? `?width=${width}` : "";
  return `${API_BASE}/datasets/${encodeURIComponent(datasetId)}/images/${encodeURIComponent(name)}${suffix}`;
}

export function runOrbitSim(
  datasetId: string,
  pattern: FlightPattern = "orbit"
): Promise<OrbitResponse> {
  return post<OrbitResponse>("/sim/orbit", { dataset_id: datasetId, pattern });
}

/** Queue a reconstruction job; backend defaults to the example dataset.
 *  useExifGps enables GPS-based georeferencing when the photos carry GPS. */
export function startVolumeJob(datasetId?: string, useExifGps = false): Promise<VolumeJob> {
  const body: Record<string, unknown> = { use_exif_gps: useExifGps };
  if (datasetId) body.dataset_id = datasetId;
  return post<VolumeJob>("/volume/jobs", body);
}

export function getVolumeJob(jobId: string): Promise<VolumeJob> {
  return request<VolumeJob>(`/volume/jobs/${jobId}`);
}

export interface SegObject {
  label: string;
  volume_m3: number;
  num_points: number;
  north_m: number;
  east_m: number;
}

export interface SegClass {
  key: string;
  color: string; // CSS hex; same colour in 3D / ortho / photo overlays
  point_count: number;
  object_count: number | null; // null for surface classes (ground, road)
  total_volume_m3: number | null;
  cloud_url: string | null;
  ortho_overlay_url: string | null;
}

export interface SegResult {
  counts: Record<string, number>;
  objects: SegObject[];
  classes: SegClass[];
  cloud_url: string;
  ortho_url: string | null; // top-down point render
  ortho_photo_url: string | null; // true photo mosaic (all photos merged)
  up_vector: number[] | null;
}

export interface SegJob {
  job_id: string;
  status: JobStatus;
  progress: string | null;
  error: string | null;
  result: SegResult | null;
}

export function startSegmentJob(): Promise<SegJob> {
  return post<SegJob>("/segment/jobs", {});
}

export function getSegmentJob(jobId: string): Promise<SegJob> {
  return request<SegJob>(`/segment/jobs/${jobId}`);
}

/** Photos that have a camera pose — each can display a segmentation overlay. */
export function fetchOverlayPhotos(): Promise<string[]> {
  return request<{ images: string[] }>("/segment/photos").then((body) => body.images);
}

/** URL of one photo with the given classes' points projected onto it. */
export function photoOverlayUrl(name: string, classes: string[], width = 1200): string {
  const cls = encodeURIComponent(classes.join(","));
  return `${API_BASE}/segment/photo/${encodeURIComponent(name)}?classes=${cls}&width=${width}`;
}

/** Turn a backend-relative download URL (e.g. /volume/files/x.ply) into a link href. */
export function fileUrl(url: string): string {
  return `${API_BASE}${url}`;
}

export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
