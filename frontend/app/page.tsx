"use client";
import { useEffect, useState } from "react";
import { Chat } from "../components/Chat";
import { IngestPanel } from "../components/IngestPanel";
import { api, Job, Repo } from "../lib/api";

const STAGES = ["cloning", "fetching", "building_graph", "indexing", "completed"];

// Map transient states to the nearest real pipeline stage for progress display.
const STAGE_ALIAS: Record<string, string> = {
  rate_limited: "fetching",
  paused: "fetching",
  queued: "cloning",
  failed: "cloning",
};

function stageIndex(stage: string): number {
  return STAGES.indexOf(STAGE_ALIAS[stage] ?? stage);
}

export default function Home() {
  const [repos, setRepos] = useState<Repo[]>([]);
  const [active, setActive] = useState<Repo | null>(null);
  const [job, setJob] = useState<Job | null>(null);

  const refresh = () =>
    api
      .repos()
      .then((items) => {
        setRepos(items);
        setActive((current) => current || items[0] || null);
      })
      .catch(() => undefined);

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (!job || ["completed", "failed"].includes(job.status)) {
      if (job?.status === "completed") refresh();
      return;
    }
    const timer = setInterval(
      () => api.status(job.repo_key).then(setJob).catch(() => undefined),
      1500
    );
    return () => clearInterval(timer);
  }, [job]);

  return (
    <main className="app">
      <aside>
        <div className="brand">
          <span className="logo">P</span>
          <span>PatchContext</span>
        </div>
        <nav>
          <button className="nav-active">Repository history</button>
          <span className="nav-label">INDEXED REPOSITORIES</span>
          {repos.length === 0 && (
            <p className="sidebar-empty">No repository indexed yet.</p>
          )}
          {repos.map((repo) => (
            <button
              key={repo.key}
              className={active?.key === repo.key ? "repo active" : "repo"}
              onClick={() => setActive(repo)}
            >
              <span>{repo.owner}/{repo.repo}</span>
              <small>{repo.status}</small>
            </button>
          ))}
        </nav>
        <footer>
          GraphRAG / local embeddings
          <br />
          Grounded by source links
        </footer>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <span>REPOSITORY INTELLIGENCE</span>
        </header>

        <section className="ingest-zone">
          <h2>Give your commit history a memory.</h2>
          <p>
            Index a public GitHub repository. PatchContext connects the
            discussion, change, and file trail before it answers.
          </p>
          <IngestPanel onSubmitted={setJob} />

          {job && (
            <div className={`job ${job.status}`}>
              <div>
                <span>{job.stage.replaceAll("_", " ")}</span>
                <strong>{job.progress}%</strong>
              </div>
              <div className="progress">
                <i style={{ width: `${job.progress}%` }} />
              </div>
              <p>{job.detail}</p>
              <ol>
                {STAGES.map((stage) => (
                  <li
                    key={stage}
                    className={stageIndex(stage) <= stageIndex(job.stage) ? "done" : ""}
                  >
                    {stage.replaceAll("_", " ")}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </section>

        {active && active.status === "completed" ? (
          <Chat repo={active} />
        ) : (
          <section className="awaiting">
            <span>◎</span>
            <h3>Choose an indexed repository to begin.</h3>
            <p>
              Once indexing completes, its conversations and commits become
              explorable evidence.
            </p>
          </section>
        )}
      </div>
    </main>
  );
}
