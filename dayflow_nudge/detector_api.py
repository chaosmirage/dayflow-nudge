"""The pluggable detection seam.

A detector turns one :class:`~dayflow_nudge.models.Observation` plus the
persisted anti-spam state into a typed
:class:`~dayflow_nudge.models.Verdict`. Variants register themselves at
import time under a stable id; the daemon instantiates exactly one at
boot and never switches mid-session. Nothing here loads detector code
from a path -- a variant exists only because its module was imported and
called :func:`register`, so no configuration or filesystem content can
inject one.
"""

from __future__ import annotations

import abc
from typing import Type

from dayflow_nudge.models import Observation, PersistedNudgeState, Verdict

__all__ = [
    "Detector",
    "Verdict",
    "create_detector",
    "register",
    "registered_variants",
    "unregister",
]


class Detector(abc.ABC):
    """The contract every detection variant implements.

    Instances are constructed with no arguments (the registry
    instantiates them for the daemon), and ``detect`` stays a pure
    classification: all input arrives through the arguments, all output
    is the returned verdict.
    """

    @abc.abstractmethod
    def detect(
        self, observation: Observation, state: PersistedNudgeState
    ) -> Verdict:
        """Classify one observation and report the verdict."""


_REGISTRY: dict[str, Type[Detector]] = {}


def register(variant_id: str, detector_class: Type[Detector]) -> Type[Detector]:
    """Make ``detector_class`` discoverable under ``variant_id``.

    Usable directly or as ``@register(variant_id)``. Every way of
    bending the contract is rejected up front -- a blank id, something
    that is not a class, a class outside the Detector contract, an
    unimplemented contract, or an id another variant already owns -- so
    one variant can never silently replace another.
    """
    if not isinstance(variant_id, str) or not variant_id.strip():
        raise ValueError("variant_id must be a non-empty string")
    if not isinstance(detector_class, type):
        raise ValueError("detector_class must be a class")
    if not issubclass(detector_class, Detector):
        raise ValueError(
            "detector_class must subclass dayflow_nudge.detector_api.Detector"
        )
    if getattr(detector_class, "__abstractmethods__", None):
        raise ValueError("detector_class must implement detect()")
    if variant_id in _REGISTRY:
        raise ValueError(f"variant already registered: {variant_id!r}")

    _REGISTRY[variant_id] = detector_class
    return detector_class


def unregister(variant_id: str) -> None:
    """Retire a registered variant id.

    Exists so test suites can keep the registry clean around their own
    stand-in variants; the daemon never calls it and never switches
    variants mid-session.
    """
    if variant_id not in _REGISTRY:
        raise ValueError(f"unknown variant: {variant_id!r}")
    del _REGISTRY[variant_id]


def registered_variants() -> tuple[str, ...]:
    """The ids of every registered variant, sorted for stable logs."""
    return tuple(sorted(_REGISTRY))


def create_detector(variant_id: str) -> Detector:
    """Instantiate the variant registered under ``variant_id``."""
    try:
        detector_class = _REGISTRY[variant_id]
    except KeyError:
        registered = ", ".join(registered_variants()) or "none"
        raise ValueError(
            f"unknown variant: {variant_id!r} (registered: {registered})"
        ) from None
    return detector_class()
