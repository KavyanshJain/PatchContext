import asyncio
import json
import pickle
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import networkx as nx

from .config import repo_key
from .github import GitHubClient, RateLimitPause
from .retrieval import build_index
from .storage import now, read_json, repo_dir, write_json

REFERENCE = re.compile(r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)?\s*#(\d+)", re.I)


def parse_url(value: str) -> tuple[str, str]:
    parsed = urlparse(value)
    if parsed.netloc.lower() != "github.com":
        raise ValueError("Provide a public github.com repository URL.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("Repository URL must include owner and repository.")
    return parts[0], parts[1].removesuffix(".git")


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.STDOUT)


def clone(url: str, destination: Path, depth: int | None) -> None:
    if (destination / ".git").exists():
        return
    command = ["git", "clone"]
    if depth:
        command.extend(["--depth", str(depth)])
    command.extend([url, str(destination)])
    subprocess.run(command, check=True, text=True, capture_output=True)


def commits(repo: Path, owner: str, name: str) -> list[dict[str, Any]]:
    format_string = "%x00%H%x1f%s%x1f%b%x1f%an%x1f%aI"
    output = git(repo, "log", f"--format={format_string}", "--name-only")
    records = []
    for block in output.split("\x00"):
        fields = block.strip().split("\x1f", 4)
        if len(fields) != 5:
            continue
        sha, subject, body, author, dated_files = fields
        date, *files = dated_files.splitlines()
        records.append({"sha": sha, "subject": subject, "body": body, "author": author, "date": date, "files": [line for line in files if line]})
    return records


def chunks_from(owner: str, name: str, commits_data: list[dict[str, Any]], prs: list[dict[str, Any]], issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_url = f"https://github.com/{owner}/{name}"
    chunks: list[dict[str, Any]] = []
    for commit in commits_data:
        chunks.append({"id": f"commit:{commit['sha']}", "kind": "commit", "label": commit["sha"][:10], "url": f"{source_url}/commit/{commit['sha']}", "text": f"Commit {commit['sha']}\n{commit['subject']}\n{commit['body']}\nFiles: {', '.join(commit['files'])}"})
    for kind, entries in (("pull_request", prs), ("issue", issues)):
        for item in entries:
            comments = "\n".join(comment.get("body") or "" for comment in item.get("comments_data", []))
            chunks.append({"id": f"{kind}:{item['number']}", "kind": kind, "label": f"{'PR' if kind == 'pull_request' else 'Issue'} #{item['number']}", "url": item["html_url"], "text": f"{kind} #{item['number']}: {item.get('title', '')}\n{item.get('body') or ''}\nDiscussion:\n{comments}"})
    return chunks


def graph_from(commits_data: list[dict[str, Any]], prs: list[dict[str, Any]], issues: list[dict[str, Any]]) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    for item in issues:
        graph.add_node(f"issue:{item['number']}", kind="issue", number=item["number"])
    for item in prs:
        pr_id = f"pull_request:{item['number']}"
        graph.add_node(pr_id, kind="pull_request", number=item["number"])
        for reference in REFERENCE.findall("\n".join([item.get("title") or "", item.get("body") or ""])):
            graph.add_edge(pr_id, f"issue:{reference}", type="references")
        for commit in item.get("commits_data", []):
            graph.add_edge(pr_id, f"commit:{commit['sha']}", type="contains")
    for commit in commits_data:
        commit_id = f"commit:{commit['sha']}"
        graph.add_node(commit_id, kind="commit", sha=commit["sha"])
        for file_name in commit["files"]:
            file_id = f"file:{file_name}"
            graph.add_node(file_id, kind="file", path=file_name)
            graph.add_edge(commit_id, file_id, type="changes")
        for reference in REFERENCE.findall(f"{commit['subject']}\n{commit['body']}"):
            graph.add_edge(commit_id, f"issue:{reference}", type="references")
    for issue in issues:
        issue_id = f"issue:{issue['number']}"
        text = "\n".join([issue.get("title") or "", issue.get("body") or ""])
        for reference in REFERENCE.findall(text):
            if reference != str(issue["number"]):
                graph.add_edge(issue_id, f"issue:{reference}", type="references")
    return graph


class JobManager:
    def __init__(self) -> None:
        self.tasks: dict[str, asyncio.Task] = {}

    async def submit(self, url: str, depth: int | None, max_items: int | None) -> dict[str, Any]:
        owner, name = parse_url(url)
        key = repo_key(owner, name)
        job_id = str(uuid.uuid4())
        state = {"job_id": job_id, "repo_key": key, "status": "queued", "stage": "queued", "progress": 0, "detail": "Waiting to start", "url": url, "depth": depth, "max_items": max_items}
        write_json(repo_dir(key) / "job.json", state)
        self.tasks[job_id] = asyncio.create_task(self.run(state, owner, name))
        return state

    def status(self, key: str) -> dict[str, Any] | None:
        return read_json(repo_dir(key) / "job.json")

    async def run(self, state: dict[str, Any], owner: str, name: str) -> None:
        base = repo_dir(state["repo_key"])
        def update(stage: str, progress: int, detail: str, status: str = "running") -> None:
            state.update(stage=stage, progress=progress, detail=detail, status=status)
            write_json(base / "job.json", state)
        try:
            update("cloning", 5, "Cloning commit history")
            await asyncio.to_thread(clone, state["url"], base / "repo", state["depth"])
            update("fetching", 25, "Fetching and caching pull requests and issues")
            client = GitHubClient(owner, name, base / "cache")
            try:
                while True:
                    try:
                        prs, issues = await client.collect_discussions(state.get("max_items", 100))
                        break
                    except RateLimitPause as pause:
                        update("rate_limited", 30, f"GitHub quota exhausted; resumes at {pause.reset_at}", "paused")
                        delay = max(1, int(pause.reset_at or "0") - int(datetime.now(timezone.utc).timestamp()) + 2)
                        await asyncio.sleep(delay)
                        update("fetching", 30, "Quota reset; continuing cached fetch")
            finally:
                await client.close()
            update("building_graph", 55, "Parsing commits and building graph")
            commit_data = await asyncio.to_thread(commits, base / "repo", owner, name)
            graph = graph_from(commit_data, prs, issues)
            with (base / "graph.pkl").open("wb") as handle:
                pickle.dump(graph, handle)
            chunks = chunks_from(owner, name, commit_data, prs, issues)
            write_json(base / "chunks.json", chunks)
            update("indexing", 75, f"Indexing {len(chunks)} source records")
            await asyncio.to_thread(build_index, base, chunks)
            write_json(base / "metadata.json", {"key": state["repo_key"], "owner": owner, "repo": name, "url": state["url"], "status": "completed", "indexed_at": now(), "counts": {"commits": len(commit_data), "pull_requests": len(prs), "issues": len(issues)}})
            update("completed", 100, "Ready to answer grounded questions", "completed")
        except Exception as exc:
            update("failed", state.get("progress", 0), str(exc), "failed")
