const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Repo = { key: string; owner: string; repo: string; url: string; status: string; indexed_at?: string; counts?: Record<string, number> };
export type Job = { job_id: string; repo_key: string; status: "queued" | "running" | "paused" | "completed" | "failed"; stage: string; progress: number; detail: string };
export type Citation = { id: string; label: string; url: string; kind: "commit" | "pull_request" | "issue" | "file" };
export type Answer = { answer: string; citations: Citation[]; refused: boolean; reason?: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) } });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || `Request failed (${response.status})`);
  return response.json();
}
export const api = {
  repos: () => request<Repo[]>("/repos"),
  ingest: (url: string, depth: number, maxItems: number) => request<Job>("/repos/ingest", { method: "POST", body: JSON.stringify({ url, depth, max_items: maxItems }) }),
  status: (key: string) => request<Job>(`/repos/${key}/status`),
  ask: (repo_key: string, question: string, temperature: number) => request<Answer>("/query", { method: "POST", body: JSON.stringify({ repo_key, question, temperature }) })
};
