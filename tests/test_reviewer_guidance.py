from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_repository_file(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_gemini_configuration_keeps_review_advisory_and_enabled() -> None:
    config = read_repository_file(".gemini/config.yaml")
    uncommented_config = "\n".join(
        line.split("#", 1)[0] for line in config.splitlines()
    ).casefold()

    assert "disable: false" in config
    assert "comment_severity_threshold: MEDIUM" in config
    assert "include_drafts: false" in config
    assert "memory_config:\n  disabled: true" in config
    assert "credential" not in uncommented_config
    assert "token" not in uncommented_config
    assert "password" not in uncommented_config


def test_gemini_review_keeps_a_stable_complementary_role() -> None:
    styleguide = read_repository_file(".gemini/styleguide.md")
    normalized_styleguide = " ".join(styleguide.split())

    assert "`/gemini review` is the review command." in styleguide
    assert "`/gemini review everything`" not in styleguide
    assert "independent, complementary adversarial reviewer" in normalized_styleguide
    assert "Codex remains the broad primary reviewer" in normalized_styleguide
    assert "primary review coverage remains unresolved" in normalized_styleguide
    assert "full fallback" not in normalized_styleguide
    assert "Review metadata" not in styleguide
    assert "Reviewed head" not in styleguide
    assert "do not modify code, push changes, approve, or merge" in normalized_styleguide
    assert "counterexamples and overlooked edge cases" in styleguide
    assert "failure and retry behavior" in styleguide
    assert "stale state or unsafe state transitions before writes" in styleguide
    assert "idempotency and duplicate writes, uploads, or other operations" in styleguide
    assert "profile isolation and trust boundaries" in styleguide
    assert "backup, recovery, and destructive-operation safety" in styleguide


def test_repository_review_guidance_has_clear_ownership() -> None:
    agents = read_repository_file("AGENTS.md")
    styleguide = read_repository_file(".gemini/styleguide.md")
    development = read_repository_file("docs/DEVELOPMENT.md")
    normalized_development = " ".join(development.split())

    assert "## Codex reviewer role" in agents
    assert "Follow the human workflow in `docs/DEVELOPMENT.md`" in agents
    assert "`@codex review`" in agents
    assert "complementary adversarial reviewer" in styleguide
    assert "specialized adversarial review focus" in normalized_development
    assert "full fallback" not in styleguide.casefold()
    assert "Review metadata" not in styleguide
    assert "do not modify code, push changes, approve, or merge" in styleguide
    assert "## Pull requests and review" in development
    assert "AGENTS.md" in development
    assert ".gemini/styleguide.md" in development
    assert "PULL_REQUEST_REVIEW.md" not in development
