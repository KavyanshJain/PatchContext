import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import data_root


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path, fallback: Any = None) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def repo_dir(key: str) -> Path:
    path = data_root() / key
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_repos() -> list[dict[str, Any]]:
    root = data_root()
    if not root.exists():
        return []
    repos = []
    for path in root.iterdir():
        metadata = read_json(path / "metadata.json") if path.is_dir() else None
        if metadata:
            repos.append(metadata)
    return sorted(repos, key=lambda item: item.get("indexed_at") or "", reverse=True)
