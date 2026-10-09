"""Registry-backed release identity, using synthetic OCI and Docker descriptors."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tabula_rasa.deployment import release

REPOSITORY = "ghcr.io/roklion/project_tabula_rasa/commercial"
ROOT = "sha256:" + "a" * 64
CHILD = "sha256:" + "b" * 64
ATTESTATION = "sha256:" + "c" * 64
IMAGE = REPOSITORY + "@" + ROOT
LABELS = {"org.opencontainers.image.revision": "d" * 40, "io.tabula.schema": "0005_bookkeeping_cutover"}


def descriptor(digest, kind="manifest"):
    return {"digest": digest, "mediaType": "application/vnd.oci.image." + kind + ".v1+json"}


def index():
    return {**descriptor(ROOT, "index"), "schemaVersion": 2, "manifests": [
        {**descriptor(CHILD), "platform": {"os": "linux", "architecture": "amd64"}},
        {**descriptor(ATTESTATION), "platform": {"os": "unknown", "architecture": "unknown"},
         "annotations": {"vnd.docker.reference.type": "attestation-manifest"}},
    ]}


def docker(monkeypatch, root, child=None, *, pull_code=0, platform="amd64"):
    def run(command, **kwargs):
        if "imagetools" in command:
            payload = root if command[4] == IMAGE else child
        elif "pull" in command:
            return SimpleNamespace(returncode=pull_code, stdout=b"")
        else:
            payload = [{"Architecture": platform, "Os": "linux", "Config": {"Labels": LABELS}}]
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload).encode())
    mocked = Mock(side_effect=run)
    monkeypatch.setattr(release.subprocess, "run", mocked)
    return mocked


@pytest.mark.parametrize("docker_types", [False, True])
def test_index_resolves_only_linux_amd64_and_inspects_its_pullable_manifest(monkeypatch, docker_types):
    root, child = index(), descriptor(CHILD)
    if docker_types:
        root["mediaType"] = "application/vnd.docker.distribution.manifest.list.v2+json"
        root["manifests"][0]["mediaType"] = child["mediaType"] = "application/vnd.docker.distribution.manifest.v2+json"
    run = docker(monkeypatch, root, child)
    result = release.image_metadata(IMAGE, REPOSITORY)
    assert result == {"release": "d" * 40, "schema": LABELS["io.tabula.schema"], "manifest_digest": CHILD}
    commands = [call.args[0] for call in run.call_args_list]
    assert commands[1][4] == REPOSITORY + "@" + CHILD
    assert commands[2] == ["docker", "pull", "--platform", "linux/amd64", REPOSITORY + "@" + CHILD]
    assert commands[3] == ["docker", "image", "inspect", REPOSITORY + "@" + CHILD]
    assert not any(ATTESTATION in part for command in commands for part in command)


def test_single_manifest_retains_its_digest(monkeypatch):
    run = docker(monkeypatch, descriptor(ROOT))
    assert release.image_metadata(IMAGE, REPOSITORY)["manifest_digest"] == ROOT
    assert run.call_count == 3


@pytest.mark.parametrize("problem", ["no_amd64", "ambiguous", "bad_digest", "attestation_type", "nested_index", "missing_manifests"])
def test_unsupported_or_malformed_index_fails_before_pull(monkeypatch, problem):
    root, child = index(), descriptor(CHILD)
    if problem == "no_amd64":
        root["manifests"][0]["platform"]["architecture"] = "arm64"
    elif problem == "ambiguous":
        root["manifests"].append(root["manifests"][0].copy())
    elif problem == "bad_digest":
        root["manifests"][0]["digest"] = "private diagnostic"
    elif problem == "attestation_type":
        root["manifests"][0]["mediaType"] = "application/unknown"
    elif problem == "nested_index":
        child = descriptor(CHILD, "index")
    else:
        del root["manifests"]
    run = docker(monkeypatch, root, child)
    with pytest.raises(release.ReleaseError) as failure:
        release.image_metadata(IMAGE, REPOSITORY)
    assert "private diagnostic" not in str(failure.value)
    assert not any("pull" in call.args[0] for call in run.call_args_list)


@pytest.mark.parametrize("payload", [b"not json", b"null", b"[]", b"{}",
                                    json.dumps(descriptor(CHILD)).encode()])
def test_registry_response_must_confirm_requested_digest(monkeypatch, payload):
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=payload))
    monkeypatch.setattr(release.subprocess, "run", run)
    with pytest.raises(release.ReleaseError, match="registry image metadata"):
        release.image_metadata(IMAGE, REPOSITORY)
    assert run.call_count == 1


def test_registry_failure_and_unpullable_child_are_rejected(monkeypatch):
    run = Mock(return_value=SimpleNamespace(returncode=1, stdout=json.dumps(descriptor(ROOT)).encode()))
    monkeypatch.setattr(release.subprocess, "run", run)
    with pytest.raises(release.ReleaseError, match="registry image metadata"):
        release.image_metadata(IMAGE, REPOSITORY)
    run = docker(monkeypatch, index(), descriptor(CHILD), pull_code=1)
    with pytest.raises(release.ReleaseError, match="cannot be pulled"):
        release.image_metadata(IMAGE, REPOSITORY)
    assert run.call_count == 3


def test_child_runtime_platform_must_match_descriptor(monkeypatch):
    docker(monkeypatch, index(), descriptor(CHILD), platform="arm64")
    with pytest.raises(release.ReleaseError, match="Invalid release image metadata"):
        release.image_metadata(IMAGE, REPOSITORY)


@pytest.mark.parametrize("digest", [ROOT, CHILD, ROOT[7:], CHILD[7:]])
def test_render_digest_is_normalized_only_after_validating_full_sha256(digest):
    release.deployed_image({"image": {"ref": IMAGE, "sha": digest}}, IMAGE,
                           {"manifest_digest": CHILD}, REPOSITORY)


@pytest.mark.parametrize("digest", [ATTESTATION, "sha256:" + "f" * 64, "sha256:" + "b" * 63,
                                   "b" * 65, CHILD + "\n", CHILD.upper(), None])
def test_unrelated_attestation_and_malformed_digests_never_pass(digest):
    with pytest.raises(release.ReleaseError, match="metadata mismatch"):
        release.deployed_image({"image": {"ref": IMAGE, "sha": digest}}, IMAGE,
                               {"manifest_digest": CHILD}, REPOSITORY)
