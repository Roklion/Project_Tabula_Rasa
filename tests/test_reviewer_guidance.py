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


def test_gemini_commands_have_distinct_exact_scopes() -> None:
    styleguide = read_repository_file(".gemini/styleguide.md")
    normalized_styleguide = " ".join(styleguide.split())

    normal_command = "Exactly `/gemini review` selects **normal complementary review**."
    fallback_command = (
        "Exactly `/gemini review everything` selects **full fallback review**."
    )
    assert normal_command in styleguide
    assert fallback_command in styleguide
    assert "complete comment case-insensitively" in styleguide
    assert (
        "A comment containing extra text is not the exact fallback command."
        in normalized_styleguide
    )
    assert "Do not modify code, push changes, approve, merge" in styleguide
    assert "state its commit SHA" in styleguide
    assert "`No additional feedback.`" in styleguide
    assert "Do not use a thumbs-up reaction" in styleguide


def test_canonical_review_guide_covers_roles_and_dispositions() -> None:
    guide = read_repository_file("docs/development/PULL_REQUEST_REVIEW.md")
    normalized_guide = " ".join(guide.split())

    for heading in (
        "### Codex: primary repository and remediation reviewer",
        "### Gemini: independent complementary reviewer",
        "### Human maintainer: requirements and merge authority",
        "## Finding disposition",
        "## Controlled validation pull request",
    ):
        assert heading in guide

    assert "Deferred valid finding" in guide
    assert "Linked issue containing risk and rationale" in guide
    assert "Reviewers do not review drafts." in guide
    assert "automatically begins Codex's initial primary review" in guide
    assert "no comment is required" in guide
    assert "`@codex review` to request a fresh Codex review" in guide
    assert (
        "Do not assume that a push automatically re-triggers Codex."
        in normalized_guide
    )
    assert (
        "Do not assume that a push automatically re-triggers Gemini."
        in normalized_guide
    )
    assert "Gemini does not use a thumbs-up reaction" in normalized_guide
    assert "only an actual controlled pull request can validate" in guide
