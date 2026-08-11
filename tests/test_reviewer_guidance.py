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


def test_gemini_review_mode_uses_trusted_codex_availability() -> None:
    styleguide = read_repository_file(".gemini/styleguide.md")
    normalized_styleguide = " ".join(styleguide.split())

    assert "`/gemini review` is the only review command." in styleguide
    assert "`/gemini review everything`" not in styleguide
    assert "chatgpt-codex-connector[bot]" in styleguide
    assert "current review round" in normalized_styleguide
    assert "Do not infer Codex unavailability from silence" in styleguide
    assert "text authored by the pull-request author" in normalized_styleguide
    assert "do not use Codex findings as input" in normalized_styleguide
    assert "label the output **Full fallback review**" in styleguide
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
    assert "without waiting for either reviewer to respond" in normalized_guide
    assert "late trusted unavailability response permits one separately tracked fallback" in normalized_guide
    assert "one `@codex review` and exactly one `/gemini review`" in normalized_guide
    assert "`gemini_requested_sha`" in guide
    assert (
        "an older PR-wide `/gemini review` comment is not evidence"
        in normalized_guide
    )
    assert "posting one `/gemini review` is safe and required" in normalized_guide
    assert "even while the current-round Codex response is pending" in normalized_guide
    assert "### Earlier-commit comments" in guide
    assert (
        "Do not ignore a comment merely because GitHub marks its line outdated"
        in normalized_guide
    )
    assert "Preserve the original commit and current-head context" in normalized_guide
    assert "Before requesting either reviewer for a head" in normalized_guide
    assert "Do not post either review trigger while feedback remains unaddressed" in normalized_guide
    assert "focused tests and linting for impacted functions or modules" in normalized_guide
    assert "before final readiness" in normalized_guide
    assert "Post `/gemini review` as a standalone pull-request comment." in guide
    assert "chatgpt-codex-connector[bot]" in guide
    assert "Do not infer unavailability from silence" in guide
    assert "`/gemini review everything`" not in guide
    assert "Gemini does not use a thumbs-up reaction" in normalized_guide
    assert "only an actual controlled pull request can validate" in guide
