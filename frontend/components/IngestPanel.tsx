"use client";
import { FormEvent, useState } from "react";
import { api, Job } from "../lib/api";

export function IngestPanel({ onSubmitted }: { onSubmitted: (job: Job) => void }) {
  const [url, setUrl] = useState("");
  const [depth, setDepth] = useState(500);
  const [maxItems, setMaxItems] = useState(100);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(""); setSubmitting(true);
    try { onSubmitted(await api.ingest(url, depth, maxItems)); } catch (err) { setError(err instanceof Error ? err.message : "Unable to start ingestion."); } finally { setSubmitting(false); }
  }
  return <form className="ingest-form" onSubmit={submit}>
    <label>PUBLIC GITHUB REPOSITORY</label>
    <div className="url-row"><span className="git-mark">⌘</span><input value={url} onChange={e => setUrl(e.target.value)} aria-label="GitHub repository URL" placeholder="https://github.com/owner/repo" /><button disabled={submitting || !url.trim()}>{submitting ? "Starting…" : "Ingest repository"}</button></div>
    <div className="option-row"><span>History depth</span><input type="range" min="50" max="5000" step="50" value={depth} onChange={e => setDepth(Number(e.target.value))} /><code>{depth} commits</code><span className="muted">Omit <code>depth</code> via the API (not the UI) for full history.</span></div>
    <div className="option-row"><span>Issues & PRs</span><input type="range" min="10" max="1000" step="10" value={maxItems} onChange={e => setMaxItems(Number(e.target.value))} /><code>{maxItems} items</code><span className="muted">Cap on GitHub discussions fetched.</span></div>
    {error && <p className="error">{error}</p>}
  </form>;
}
