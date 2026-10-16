"""Digest promotion and bounded Render lifecycle; never retry uncertain creates."""

import argparse
import json
import os
import re
import subprocess
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit


class ReleaseError(ValueError):
    """Fixed operator diagnostics only."""


MANIFEST_TYPES = {"application/vnd.oci.image.manifest.v1+json",
                  "application/vnd.docker.distribution.manifest.v2+json"}
INDEX_TYPES = {"application/vnd.oci.image.index.v1+json",
               "application/vnd.docker.distribution.manifest.list.v2+json"}


def immutable_digest(image, repository):
    if not isinstance(image, str) or not re.fullmatch(re.escape(repository) + r"@sha256:[0-9a-f]{64}", image):
        raise ReleaseError("Use an immutable digest in the configured repository.")
    return image.split("@", 1)[1]


def registry_manifest(image, repository):
    """Read the registry descriptor, never a local image/config ID or a tag."""
    digest = immutable_digest(image, repository)
    result = subprocess.run(["docker", "buildx", "imagetools", "inspect", image,
                             "--format", "{{json .Manifest}}"], capture_output=True, check=False)
    try:
        manifest = json.loads(result.stdout)
        if result.returncode or manifest["digest"] != digest:
            raise ValueError
        return manifest
    except (ValueError, KeyError, TypeError):
        raise ReleaseError("Invalid registry image metadata; inspect retained release digests.") from None


def deployed_image(deploy, image, metadata, repository):
    """Require both Render fields to identify the verified immutable artifact."""
    allowed = {immutable_digest(image, repository), metadata["manifest_digest"]}
    try:
        reported = deploy["image"]
        ref_digest = immutable_digest(reported["ref"], repository)
        sha = reported["sha"]
        if not isinstance(sha, str) or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", sha):
            raise ValueError
        digest = sha if sha.startswith("sha256:") else "sha256:" + sha
        if ref_digest not in allowed or digest not in allowed:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ReleaseError("Render image metadata mismatch or missing; stop and inspect provider state.") from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def api(path, token, *, body=None, github=False):
    base = "https://api.github.com" if github else "https://api.render.com/v1"
    request = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                               "Accept": "application/json", "User-Agent": "tabula-release"})
    try:
        with build_opener(NoRedirect).open(request, timeout=30) as response:
            return json.load(response)
    except Exception:
        raise ReleaseError("Provider request failed or its result is uncertain; inspect before retrying.") from None


def image_metadata(image, repository):
    digest = immutable_digest(image, repository)
    manifest = registry_manifest(image, repository)
    try:
        if manifest["mediaType"] in INDEX_TYPES:
            matching = [item for item in manifest["manifests"]
                        if item.get("platform", {}).get("os") == "linux"
                        and item.get("platform", {}).get("architecture") == "amd64"]
            if len(matching) != 1 or matching[0]["mediaType"] not in MANIFEST_TYPES:
                raise ValueError
            digest = matching[0]["digest"]
            manifest = registry_manifest(repository + "@" + digest, repository)
        if manifest["mediaType"] not in MANIFEST_TYPES:
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ReleaseError("Invalid linux/amd64 registry manifest.") from None
    runtime_image = repository + "@" + digest
    pull = subprocess.run(["docker", "pull", "--platform", "linux/amd64", runtime_image], capture_output=True, check=False)
    if pull.returncode:
        raise ReleaseError("Image cannot be pulled; preserve registry rollback digests.")
    result = subprocess.run(["docker", "image", "inspect", runtime_image], capture_output=True, check=False)
    try:
        metadata = json.loads(result.stdout)[0]
        labels = metadata["Config"]["Labels"]
        release = labels["org.opencontainers.image.revision"]
        schema = labels["io.tabula.schema"]
        if (result.returncode or metadata["Architecture"] != "amd64" or metadata["Os"] != "linux"
                or not re.fullmatch("[0-9a-f]{40}", release) or not re.fullmatch("[A-Za-z0-9_]{1,100}", schema)):
            raise ValueError
    except (ValueError, KeyError, IndexError, TypeError):
        raise ReleaseError("Invalid release image metadata.") from None
    return {"release": release, "schema": schema, "manifest_digest": digest}


def validated_main(release, environ):
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", release, "origin/main"],
                              capture_output=True, check=False)
    if ancestor.returncode:
        raise ReleaseError("Release must be reachable from main.")
    if environ.get("TABULA_RASA_ENVIRONMENT") == "development":
        latest = subprocess.run(["git", "rev-parse", "origin/main"], capture_output=True, check=False)
        if latest.returncode or latest.stdout.decode().strip() != release:
            raise ReleaseError("Superseded development release; deploy the latest validated main image.")
    repo = environ["GITHUB_REPOSITORY"]
    runs = api(f"/repos/{repo}/actions/workflows/ci.yml/runs?head_sha={release}&event=push&branch=main&per_page=20",
               environ["GH_TOKEN"], github=True)["workflow_runs"]
    if not runs or runs[0].get("conclusion") != "success" or runs[0].get("head_sha") != release:
        raise ReleaseError("Current main-revision Repository CI success is required.")


def wait_live(service, deploy, token, *, read=api, sleep=time.sleep):
    if not re.fullmatch("dep-[a-z0-9]+", deploy):
        raise ReleaseError("Invalid deployment identity; inspect provider state.")
    for _ in range(60):
        result = read(f"/services/{service}/deploys/{deploy}", token)
        if result.get("status") == "live":
            return result
        if result.get("status") in {"build_failed", "update_failed", "pre_deploy_failed", "canceled", "deactivated"}:
            raise ReleaseError("Render deployment failed; inspect provider state and retained prior deployment.")
        sleep(10)
    raise ReleaseError("Deployment timed out; inspect before any further deployment.")


def promote(image, environ, *, read=api, metadata=image_metadata, verify=validated_main, smoke_check=None):
    from .smoke import access_mode, named_smoke, smoke
    if environ.get("TABULA_RASA_ENVIRONMENT") not in {"development", "staging"}:
        raise ReleaseError("Only development/staging promotion is supported.")
    mode = access_mode(environ)
    if mode == 'named_user':
        check = smoke_check or named_smoke
        def check_release(revision):
            check(environ['TABULA_RASA_PUBLIC_ORIGIN'], revision)
    else:
        check = smoke_check or smoke
        def check_release(revision):
            check(environ['TABULA_RASA_PUBLIC_ORIGIN'], environ['TABULA_RASA_ALPHA_USERNAME'],
                  environ['TABULA_RASA_ALPHA_PASSWORD'], revision)
    repository = "ghcr.io/" + environ["GITHUB_REPOSITORY"].lower() + "/commercial"
    candidate = metadata(image, repository)
    verify(candidate["release"], environ)
    origin = environ["TABULA_RASA_PUBLIC_ORIGIN"]
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ReleaseError("An exact HTTPS origin is required.")
    service, token = environ["RENDER_SERVICE_ID"], environ["RENDER_API_KEY"]
    if not re.fullmatch("srv-[a-z0-9]+", service):
        raise ReleaseError("Invalid Render service identity.")
    deployments = read(f"/services/{service}/deploys?limit=100", token)
    active = [item["deploy"] for item in deployments]
    if any(item.get("status") in {"created", "queued", "build_in_progress", "update_in_progress", "pre_deploy_in_progress"} for item in active):
        raise ReleaseError("Another deployment is in progress; inspect before proceeding.")
    prior = next((item for item in active if item.get("status") == "live"), None)
    previous_image = None
    previous = None
    if prior:
        try:
            previous_image = prior["image"]["ref"]
            immutable_digest(previous_image, repository)
        except (ValueError, KeyError, TypeError):
            raise ReleaseError("Prior image needs a verified immutable reference; inspect provider state.") from None
        previous = metadata(previous_image, repository)
        deployed_image(prior, previous_image, previous, repository)
        if previous["schema"] != candidate["schema"]:
            raise ReleaseError("Prior image is schema-incompatible; use reviewed maintenance/bridge procedure.")
    deployed = read(f"/services/{service}/deploys", token, body={"imageUrl": image})
    # No rollback after an uncertain create/wait: it could race a still-running deploy.
    confirmed = wait_live(service, deployed["id"], token, read=read)
    deployed_image(confirmed, image, candidate, repository)
    try:
        check_release(candidate['release'])
    except Exception:
        if mode == 'named_user':
            # Matching ledger schema alone cannot prove old auth code/epoch
            # compatibility. Never restore an alpha-era bypass automatically.
            raise ReleaseError("Named smoke failed; restrict ingress and inspect. Use the reviewed named-mode rollback checklist.") from None
        if previous_image:
            rollback = read(f"/services/{service}/deploys", token, body={"imageUrl": previous_image})
            restored = wait_live(service, rollback["id"], token, read=read)
            deployed_image(restored, previous_image, previous, repository)
            check_release(previous['release'])
            raise ReleaseError("Smoke failed; prior compatible image restored and smoke verified.") from None
        raise ReleaseError("Initial smoke failed; no prior image exists. Restrict access and inspect.") from None
    return {"image": image, **candidate, "access_mode": mode, "status": "smoke_passed"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["verify", "promote"])
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    try:
        environ = dict(os.environ)
        from .smoke import access_mode
        access_mode(environ, require_alpha_credentials=False)
        if args.command == "verify":
            metadata = image_metadata(args.image, "ghcr.io/" + environ["GITHUB_REPOSITORY"].lower() + "/commercial")
            validated_main(metadata["release"], environ)
            print(json.dumps(metadata, sort_keys=True))
        else:
            print(json.dumps(promote(args.image, environ), sort_keys=True))
    except Exception as error:
        message = str(error) if isinstance(error, ReleaseError) else "Release step failed; inspect configuration and provider state."
        raise SystemExit(message) from None


if __name__ == "__main__":
    main()
