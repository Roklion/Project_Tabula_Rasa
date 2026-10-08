"""Required commercial load metadata; never obtain a baseline during a write."""

from tabula_rasa.application.baselines import RecordBaseline

from .errors import TransportError


def required_baseline(token: str | None) -> dict[str, str]:
    if token is None or not token.strip():
        raise TransportError("baseline_required")
    RecordBaseline.decode(token)
    return {"baseline": token}


def merge_baselines(target_id, source_ids, tokens):
    roots = {target_id, *source_ids}
    if tokens is None or roots - tokens.keys():
        raise TransportError("baseline_required")
    if tokens.keys() - roots:
        raise TransportError("baseline_invalid")
    return {identity: required_baseline(tokens[identity]) for identity in roots}
