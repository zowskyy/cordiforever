"""HARNESS_DELTA_CONTRACT registry (S2, v1).

`benchmark/repo_task_eval.py` hashes itself: it is listed in its own `HARNESS_SOURCES`, and
`harness_hash()` feeds both `experiment.harness_sha256` and every row `fingerprint`. Any evaluator
edit therefore changes the harness hash -- including the one line that adds a condition. Identical
harness hashes between preserved rows and future rows are IMPOSSIBLE, and this module does not
pretend otherwise.

What it does instead: a harness-hash difference is accepted ONLY as an explicit compatibility
certificate covering one exact (old, new) pair. Generic harness inequality is never ignored, and a
pair that is not registered fails closed even if its delta would have been acceptable.

A certificate asserts, and the S2 test-suite proves, that the delta is confined to:
  D-a  condition-additive   -- new keys added to CONDITIONS; no existing entry altered;
  D-b  observation-only     -- new recording of already-computed values into new row keys; no row key
                              removed or repurposed; no control flow changed for any existing condition;
  D-c  prompt-invariant     -- nothing the model sees changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class HarnessDeltaError(RuntimeError):
    """A harness-hash relationship that no registered certificate covers."""


@dataclass(frozen=True)
class Certificate:
    identifier: str
    old_harness_sha256: str
    new_harness_sha256: str
    properties: tuple[str, ...]
    description: str


#: Registered certificates, keyed by (old, new). Populated only when a delta has been implemented,
#: proven by the S2 test-suite, and reviewed. An empty registry means every mismatch fails closed,
#: which is the correct default.
CERTIFICATES: dict[tuple[str, str], Certificate] = {}


REQUIRED_PROPERTIES = ("condition_additive", "observation_only", "prompt_invariant")


def register(certificate: Certificate) -> None:
    """Register a certificate. Refuses a duplicate pair and an incomplete property set."""
    missing = [p for p in REQUIRED_PROPERTIES if p not in certificate.properties]
    if missing:
        raise HarnessDeltaError(f"{certificate.identifier}: missing proven propert(ies) {missing}")
    if certificate.old_harness_sha256 == certificate.new_harness_sha256:
        raise HarnessDeltaError(f"{certificate.identifier}: old and new hashes are identical; "
                                "a certificate covers a DIFFERENCE")
    key = (certificate.old_harness_sha256, certificate.new_harness_sha256)
    if key in CERTIFICATES:
        raise HarnessDeltaError(f"a certificate is already registered for {key}")
    CERTIFICATES[key] = certificate


def check_harness_relationship(old_sha256: str, new_sha256: str,
                               registry: Mapping[tuple[str, str], Certificate] | None = None
                               ) -> Certificate | None:
    """Return None when the hashes are equal; the covering certificate when a difference is certified.

    Raises HarnessDeltaError for any uncertified difference. There is no wildcard and no
    'close enough' path.
    """
    if not isinstance(old_sha256, str) or not isinstance(new_sha256, str) \
            or not old_sha256 or not new_sha256:
        raise HarnessDeltaError("harness hashes must be non-empty strings")
    if old_sha256 == new_sha256:
        return None
    table = CERTIFICATES if registry is None else registry
    certificate = table.get((old_sha256, new_sha256))
    if certificate is None:
        raise HarnessDeltaError(
            f"harness hash differs ({old_sha256[:12]}… -> {new_sha256[:12]}…) and no "
            f"HARNESS_DELTA_CONTRACT certificate covers this exact pair")
    missing = [p for p in REQUIRED_PROPERTIES if p not in certificate.properties]
    if missing:
        raise HarnessDeltaError(f"{certificate.identifier}: certificate does not prove {missing}")
    return certificate
