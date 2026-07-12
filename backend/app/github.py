import asyncio
import os
from pathlib import Path
from typing import Any

import httpx

from .storage import read_json, write_json


class RateLimitPause(Exception):
    def __init__(self, reset_at: str | None):
        self.reset_at = reset_at


class GitHubClient:
    def __init__(self, owner: str, repo: str, cache_dir: Path):
        self.owner = owner
        self.repo = repo
        self.cache_dir = cache_dir
        token = os.getenv("GITHUB_TOKEN")
        self.headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.AsyncClient(headers=self.headers, timeout=30, follow_redirects=True)
        self.semaphore = asyncio.Semaphore(8)

    async def close(self) -> None:
        await self.client.aclose()

    async def get(self, endpoint: str) -> Any:
        async with self.semaphore:
            response = await self.client.get(f"https://api.github.com{endpoint}")
        if response.status_code in (403, 429) and (
            response.headers.get("x-ratelimit-remaining") == "0" or response.status_code == 429
        ):
            reset = response.headers.get("x-ratelimit-reset") or response.headers.get("retry-after")
            raise RateLimitPause(reset)
        response.raise_for_status()
        return response.json()

    async def list_paginated(self, endpoint: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in range(1, 101):
            suffix = "&" if "?" in endpoint else "?"
            try:
                page_items = await self.get(f"{endpoint}{suffix}per_page=100&page={page}")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 422:
                    break
                raise
            if not page_items:
                break
            items.extend(page_items)
            if len(page_items) < 100:
                break
        return items

    async def cached_detail(self, kind: str, number: int, endpoint: str) -> dict[str, Any]:
        path = self.cache_dir / kind / f"{number}.json"
        cached = read_json(path)
        if cached:
            return cached
        value = await self.get(endpoint)
        write_json(path, value)
        return value

    async def collect_discussions(self, max_items: int = 100) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        raw = await self.list_paginated(f"/repos/{self.owner}/{self.repo}/issues?state=all")
        prs = [item for item in raw if "pull_request" in item][:max_items]
        issues = [item for item in raw if "pull_request" not in item][:max_items]

        async def hydrate(item: dict[str, Any], kind: str) -> dict[str, Any]:
            number = item["number"]
            print(f"[hydrate] starting {kind} #{number}", flush=True)
            endpoint = f"/repos/{self.owner}/{self.repo}/pulls/{number}" if kind == "prs" else f"/repos/{self.owner}/{self.repo}/issues/{number}"
            detail = await self.cached_detail(kind, number, endpoint)
            comments_path = self.cache_dir / kind / f"{number}.comments.json"
            comments = read_json(comments_path)
            if comments is None:
                comments = await self.list_paginated(f"/repos/{self.owner}/{self.repo}/issues/{number}/comments")
                write_json(comments_path, comments)
            detail["comments_data"] = comments
            if kind == "prs":
                commits_path = self.cache_dir / kind / f"{number}.commits.json"
                pull_commits = read_json(commits_path)
                if pull_commits is None:
                    pull_commits = await self.list_paginated(f"/repos/{self.owner}/{self.repo}/pulls/{number}/commits")
                    write_json(commits_path, pull_commits)
                detail["commits_data"] = pull_commits
            print(f"[hydrate] done {kind} #{number}", flush=True)
            return detail

        detailed_prs, detailed_issues = await asyncio.gather(
            asyncio.gather(*(hydrate(item, "prs") for item in prs)),
            asyncio.gather(*(hydrate(item, "issues") for item in issues)),
        )
        return list(detailed_prs), list(detailed_issues)
