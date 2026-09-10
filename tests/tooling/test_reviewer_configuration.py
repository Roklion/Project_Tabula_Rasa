from __future__ import annotations

from pathlib import Path
import re

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_repository_file(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_gemini_configuration_is_parseable_and_safe() -> None:
    raw_config = read_repository_file(".gemini/config.yaml")
    config = yaml.safe_load(raw_config)

    assert isinstance(config, dict)
    memory_config = config.get("memory_config")
    code_review = config.get("code_review")
    assert isinstance(memory_config, dict)
    assert isinstance(code_review, dict)
    assert memory_config.get("disabled") is True
    assert code_review.get("disable") is False
    assert code_review.get("comment_severity_threshold") in {
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL",
    }
    max_review_comments = code_review.get("max_review_comments")
    assert type(max_review_comments) is int
    assert max_review_comments > 0

    pull_request_opened = code_review.get("pull_request_opened")
    assert isinstance(pull_request_opened, dict)
    assert pull_request_opened.get("code_review") is True
    assert pull_request_opened.get("include_drafts") is False

    uncommented_config = "\n".join(
        line.split("#", 1)[0] for line in raw_config.splitlines()
    )
    credential_pattern = r"(?i)(?:credential|token|password)"
    assert re.search(credential_pattern, uncommented_config) is None
    assert re.search(credential_pattern, "github_token: configured") is not None
