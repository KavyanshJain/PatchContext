from functools import lru_cache
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()


@lru_cache
def data_root() -> Path:
    configured = os.getenv("DATA_DIR")
    return Path(configured).resolve() if configured else Path(__file__).parents[2] / "data"


def repo_key(owner: str, repo: str) -> str:
    return f"{owner.lower()}__{repo.lower()}"
