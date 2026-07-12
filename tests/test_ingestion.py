import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))
from app.ingestion import graph_from, parse_url


def test_parse_github_url():
    assert parse_url("https://github.com/karpathy/micrograd") == ("karpathy", "micrograd")


def test_graph_connects_commit_to_file_and_issue():
    sha = "a" * 40
    graph = graph_from([{"sha": sha, "subject": "fixes #7", "body": "", "files": ["engine.py"]}], [], [{"number": 7, "title": "Bug", "body": ""}])
    assert graph.has_edge(f"commit:{sha}", "file:engine.py")
    assert graph.has_edge(f"commit:{sha}", "issue:7")
