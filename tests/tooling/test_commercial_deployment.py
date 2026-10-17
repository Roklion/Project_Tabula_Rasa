from pathlib import Path
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from tabula_rasa.deployment import database, release
from tabula_rasa.infrastructure.postgres import hosted

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "ghcr.io/roklion/project_tabula_rasa/commercial"
IMAGE = REPOSITORY + "@sha256:" + "a" * 64
PRIOR = REPOSITORY + "@sha256:" + "b" * 64
MANIFEST = "sha256:" + "e" * 64
PRIOR_MANIFEST = "sha256:" + "f" * 64
ENV = {"TABULA_RASA_ENVIRONMENT": "staging", "GITHUB_REPOSITORY": "Roklion/Project_Tabula_Rasa",
       "TABULA_RASA_ACCESS_MODE": "restricted_alpha",
       "TABULA_RASA_PUBLIC_ORIGIN": "https://stage.example.test", "RENDER_SERVICE_ID": "srv-test",
       "RENDER_API_KEY": "synthetic-only", "TABULA_RASA_ALPHA_USERNAME": "stage", "TABULA_RASA_ALPHA_PASSWORD": "synthetic"}


def metadata(image, repository):
    assert repository == REPOSITORY
    return {"release": ("c" if image == IMAGE else "d") * 40, "schema": "0001_initial",
            "manifest_digest": MANIFEST if image == IMAGE else PRIOR_MANIFEST}


def provider(*, existing=True, platform_sha=False):
    def read(path, token, *, body=None):
        assert token == "synthetic-only"
        if path.endswith("?limit=100"):
            return [{"deploy": {"status": "live", "image": {"ref": PRIOR,
                     "sha": PRIOR_MANIFEST[7:] if platform_sha else "sha256:" + "b" * 64}}}] if existing else []
        if body:
            return {"id": "dep-new" if body["imageUrl"] == IMAGE else "dep-old"}
        new = path.endswith("dep-new")
        return {"status": "live", "image": {"ref": IMAGE if new else PRIOR,
                "sha": (MANIFEST if new else PRIOR_MANIFEST)[7:] if platform_sha else "sha256:" + ("a" if new else "b") * 64}}
    return Mock(side_effect=read)


@pytest.mark.parametrize("platform_sha", [False, True])
def test_smoke_success_records_exact_release_without_extra_deploys(platform_sha):
    read, smoke = provider(platform_sha=platform_sha), Mock()
    result = release.promote(IMAGE, ENV, read=read, metadata=metadata, verify=Mock(), smoke_check=smoke)
    assert result["image"] == IMAGE and result["status"] == "smoke_passed"
    assert sum(call.kwargs.get("body") is not None for call in read.call_args_list) == 1
    smoke.assert_called_once_with(ENV["TABULA_RASA_PUBLIC_ORIGIN"], "stage", "synthetic", "c" * 40)


@pytest.mark.parametrize("platform_sha", [False, True])
def test_failed_smoke_restores_prior_schema_compatible_digest_and_verifies_it(platform_sha):
    read = provider(platform_sha=platform_sha)
    smoke = Mock(side_effect=[ValueError("private diagnostic"), None])
    with pytest.raises(release.ReleaseError, match="restored and smoke verified"):
        release.promote(IMAGE, ENV, read=read, metadata=metadata, verify=Mock(), smoke_check=smoke)
    assert [call.kwargs["body"]["imageUrl"] for call in read.call_args_list if call.kwargs.get("body")] == [IMAGE, PRIOR]
    assert smoke.call_args_list[1].args[-1] == "d" * 40


def test_initial_smoke_failure_stops_without_inventing_rollback():
    read = provider(existing=False)
    with pytest.raises(release.ReleaseError, match="no prior image"):
        release.promote(IMAGE, ENV, read=read, metadata=metadata, verify=Mock(), smoke_check=Mock(side_effect=ValueError))
    assert sum(call.kwargs.get("body") is not None for call in read.call_args_list) == 1


def test_incompatible_prior_image_stops_before_deploy():
    read = provider()
    def incompatible(image, repository):
        return {**metadata(image, repository), "schema": "new" if image == IMAGE else "old"}
    with pytest.raises(release.ReleaseError, match="schema-incompatible"):
        release.promote(IMAGE, ENV, read=read, metadata=incompatible, verify=Mock(), smoke_check=Mock())
    assert not any(call.kwargs.get("body") for call in read.call_args_list)


def test_uncertain_deploy_wait_never_starts_competing_rollback():
    read = provider()
    original = read.side_effect
    def uncertain(path, token, **kwargs):
        if path.endswith("dep-new"):
            raise release.ReleaseError("uncertain")
        return original(path, token, **kwargs)
    read.side_effect = uncertain
    with pytest.raises(release.ReleaseError, match="uncertain"):
        release.promote(IMAGE, ENV, read=read, metadata=metadata, verify=Mock(), smoke_check=Mock())
    assert sum(call.kwargs.get("body") is not None for call in read.call_args_list) == 1


@pytest.mark.parametrize("phase", ["prior", "candidate", "rollback"])
@pytest.mark.parametrize("image_data", [None, {}, {"ref": IMAGE}, {"sha": MANIFEST},
                         {"ref": IMAGE, "sha": "sha256:" + "9" * 64},
                         {"ref": "evil.test/image@" + MANIFEST, "sha": MANIFEST},
                         {"ref": IMAGE, "sha": "private diagnostic"},
                         {"ref": IMAGE, "sha": None}, {"ref": IMAGE + "\n", "sha": MANIFEST},
                         {"ref": REPOSITORY + ":latest", "sha": MANIFEST}])
def test_invalid_render_metadata_stops_at_each_verification_boundary(phase, image_data):
    read = provider()
    original = read.side_effect
    def altered(path, token, **kwargs):
        response = original(path, token, **kwargs)
        if phase == "prior" and path.endswith("?limit=100"):
            response[0]["deploy"]["image"] = image_data
        elif path.endswith("dep-new" if phase == "candidate" else "dep-old") and phase != "prior":
            response["image"] = image_data
        return response
    read.side_effect = altered
    smoke = Mock(side_effect=ValueError("private diagnostic"))
    with pytest.raises(release.ReleaseError) as failure:
        release.promote(IMAGE, ENV, read=read, metadata=metadata, verify=Mock(), smoke_check=smoke)
    assert "private diagnostic" not in str(failure.value)
    assert sum(call.kwargs.get("body") is not None for call in read.call_args_list) == {
        "prior": 0, "candidate": 1, "rollback": 2}[phase]
    assert smoke.call_count == (1 if phase == "rollback" else 0)


def test_unpullable_prior_and_unverified_candidate_stop_before_deploy():
    read = provider()
    def unpullable(image, repository):
        if image == PRIOR:
            raise release.ReleaseError("Image cannot be pulled")
        return metadata(image, repository)
    with pytest.raises(release.ReleaseError, match="cannot be pulled"):
        release.promote(IMAGE, ENV, read=read, metadata=unpullable, verify=Mock())
    assert not any(call.kwargs.get("body") for call in read.call_args_list)
    read.reset_mock()
    with pytest.raises(release.ReleaseError, match="unverified"):
        release.promote(IMAGE, ENV, read=read, metadata=metadata,
                        verify=Mock(side_effect=release.ReleaseError("unverified")))
    read.assert_not_called()


def test_uncertain_create_never_retries_or_rolls_back():
    read = provider()
    original = read.side_effect
    def uncertain(path, token, **kwargs):
        if kwargs.get("body"):
            raise release.ReleaseError("uncertain")
        return original(path, token, **kwargs)
    read.side_effect = uncertain
    smoke = Mock()
    with pytest.raises(release.ReleaseError, match="uncertain"):
        release.promote(IMAGE, ENV, read=read, metadata=metadata, verify=Mock(), smoke_check=smoke)
    assert sum(call.kwargs.get("body") is not None for call in read.call_args_list) == 1
    smoke.assert_not_called()


def test_promotion_timeout_never_rolls_back_or_runs_smoke(monkeypatch):
    read, smoke = provider(), Mock()
    monkeypatch.setattr(release, "wait_live", Mock(side_effect=release.ReleaseError("Deployment timed out")))
    with pytest.raises(release.ReleaseError, match="timed out"):
        release.promote(IMAGE, ENV, read=read, metadata=metadata, verify=Mock(), smoke_check=smoke)
    assert sum(call.kwargs.get("body") is not None for call in read.call_args_list) == 1
    smoke.assert_not_called()


@pytest.mark.parametrize("status", ["build_failed", "update_failed", "pre_deploy_failed", "canceled"])
def test_terminal_deploy_failure_and_timeout_are_bounded(status):
    read, sleep = Mock(return_value={"status": status}), Mock()
    with pytest.raises(release.ReleaseError):
        release.wait_live("srv-test", "dep-test", "secret", read=read, sleep=sleep)
    assert read.call_count == 1 and not sleep.called
    read.return_value = {"status": "update_in_progress"}
    with pytest.raises(release.ReleaseError, match="timed out"):
        release.wait_live("srv-test", "dep-test", "secret", read=read, sleep=sleep)
    assert sleep.call_count == 60


@pytest.mark.parametrize("image", [REPOSITORY + ":latest", "evil.test/image@sha256:" + "a" * 64, IMAGE + "\n"])
def test_untrusted_image_references_rejected_before_docker(image, monkeypatch):
    run = Mock()
    monkeypatch.setattr(release.subprocess, "run", run)
    with pytest.raises(release.ReleaseError):
        release.image_metadata(image, REPOSITORY)
    run.assert_not_called()


def test_image_metadata_requires_runtime_platform_and_bounded_sha_schema(monkeypatch):
    labels = {"org.opencontainers.image.revision": "c" * 40, "io.tabula.schema": "0005_bookkeeping_cutover"}
    def run(command, **kwargs):
        if "imagetools" in command:
            return SimpleNamespace(returncode=0, stdout=json.dumps({"digest": IMAGE.split("@")[1],
                                   "mediaType": "application/vnd.oci.image.manifest.v1+json"}).encode())
        payload = [{"Architecture": "amd64", "Os": "linux", "Config": {"Labels": labels}}]
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload).encode())
    monkeypatch.setattr(release.subprocess, "run", run)
    assert release.image_metadata(IMAGE, REPOSITORY)["release"] == "c" * 40
    labels["org.opencontainers.image.revision"] = "untrusted release text"
    with pytest.raises(release.ReleaseError, match="metadata"):
        release.image_metadata(IMAGE, REPOSITORY)


def test_ci_verifier_rejects_failed_and_superseded_development_releases(monkeypatch):
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=("c" * 40).encode()))
    monkeypatch.setattr(release.subprocess, "run", run)
    provider = Mock(return_value={"workflow_runs": [{"conclusion": "success", "head_sha": "c" * 40}]})
    monkeypatch.setattr(release, "api", provider)
    environ = {**ENV, "GH_TOKEN": "synthetic"}
    release.validated_main("c" * 40, environ)
    provider.return_value = {"workflow_runs": [{"conclusion": "failure", "head_sha": "c" * 40}]}
    with pytest.raises(release.ReleaseError, match="CI success"):
        release.validated_main("c" * 40, environ)
    provider.reset_mock()
    with pytest.raises(release.ReleaseError, match="Superseded"):
        release.validated_main("d" * 40, {**environ, "TABULA_RASA_ENVIRONMENT": "development"})
    provider.assert_not_called()


def test_active_deploy_and_production_stop_without_provider_mutation():
    read = Mock(return_value=[{"deploy": {"status": "update_in_progress"}}])
    with pytest.raises(release.ReleaseError, match="in progress"):
        release.promote(IMAGE, ENV, read=read, metadata=metadata, verify=Mock(), smoke_check=Mock())
    assert not any(call.kwargs.get("body") for call in read.call_args_list)
    read.reset_mock()
    with pytest.raises(release.ReleaseError, match="Only development/staging"):
        release.promote(IMAGE, {**ENV, "TABULA_RASA_ENVIRONMENT": "production"}, read=read)
    read.assert_not_called()


def test_migration_orders_existing_cli_and_never_deploys_after_failure(monkeypatch):
    target = Mock()
    target.health.return_value = {"connected": True, "revision": database.head_revision()}
    monkeypatch.setattr(database, "bound_database", lambda _: target)
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(database.subprocess, "run", run)
    database.migrate({"synthetic": "configuration"})
    assert [call.args[0][-1] for call in run.call_args_list] == ["current", "upgrade", "health"]
    run.reset_mock()
    run.side_effect = [SimpleNamespace(returncode=0), SimpleNamespace(returncode=1)]
    with pytest.raises(ValueError, match="stopped"):
        database.migrate({})
    assert run.call_count == 2


def test_schema_change_and_wrong_target_stop_before_migration(monkeypatch):
    target = Mock()
    target.health.return_value = {"connected": True, "revision": "old"}
    monkeypatch.setattr(database, "bound_database", lambda _: target)
    run = Mock()
    monkeypatch.setattr(database.subprocess, "run", run)
    with pytest.raises(ValueError, match="Schema change"):
        database.migrate({})
    run.assert_not_called()
    target.dispose.assert_called_once()


def test_shared_runtime_migrator_binding_rejects_wrong_environment_target_and_tls(monkeypatch):
    target = Mock()
    monkeypatch.setattr(hosted, "Database", lambda _: target)
    monkeypatch.setattr(hosted, "database_identity", lambda _: "a" * 64)
    configured = {"TABULA_RASA_ENVIRONMENT": "staging", "TABULA_RASA_DEPLOY_DATABASE_SHA256": "a" * 64,
                  "TABULA_RASA_DATABASE_URL": "postgresql://runtime@ep-fixture.neon.tech/synthetic?sslmode=require"}
    assert hosted.open_alpha_database(configured) is target
    for changes in ({"TABULA_RASA_ENVIRONMENT": "production"},
                    {"TABULA_RASA_DEPLOY_DATABASE_SHA256": "b" * 64},
                    {"TABULA_RASA_DATABASE_URL": "postgresql://runtime@ep-fixture.neon.tech/synthetic"},
                    {"TABULA_RASA_DATABASE_URL": "postgresql://runtime@ep-fixture-pooler.neon.tech/synthetic?sslmode=require"}):
        with pytest.raises(ValueError):
            hosted.open_alpha_database({**configured, **changes})
    target.dispose.assert_called_once()


def test_workflow_credential_separation_serialization_and_main_only_image_build():
    def load(name):
        return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)
    config = load("commercial-promote.yml")
    job = config["jobs"]["deploy"]
    assert any(step.get("uses") == "docker/setup-buildx-action@v3" for step in job["steps"])
    assert job["concurrency"]["cancel-in-progress"] == "false"
    assert job["environment"] == "${{ inputs.environment }}"
    migration = next(step for step in job["steps"] if "bound migration" in step.get("name", ""))
    assert migration["env"] == {"TABULA_RASA_DATABASE_URL": "${{ secrets.TABULA_RASA_MIGRATION_DATABASE_URL }}"}
    assert "--bootstrap" not in migration["run"] and "database migrate" in migration["run"]
    assert "TABULA_RASA_DATABASE_URL" not in job["env"]
    build = load("commercial-image.yml")["jobs"]["build"]
    assert "conclusion == 'success'" in build["if"] and "event == 'push'" in build["if"]
    assert "github.ref == 'refs/heads/main'" in load("commercial-staging.yml")["jobs"]["staging"]["if"]
