"""Shared transfer lifecycle vocabulary; terminal never means successful."""

import re


def classify(state):
    tokens = set(re.split(r"[,\s]+", str(state or "").casefold()))
    if "replaced" in tokens:
        return "replaced"
    if "cancelled" in tokens or "canceled" in tokens:
        return "cancelled"
    if "succeeded" in tokens:
        return "succeeded"
    if any(
        w in str(state).casefold()
        for w in (
            "errored",
            "error",
            "reject",
            "denied",
            "timedout",
            "timed out",
            "aborted",
            "offline",
            "failed",
        )
    ):
        return "failed"
    if any(
        w in str(state).casefold()
        for w in ("unconfirmed", "missing", "reconcil", "submitting", "pending")
    ):
        return "uncertain"
    if any(w in str(state).casefold() for w in ("transferring", "inprogress", "in progress")):
        return "active"
    return "queued"


def succeeded(state):
    return classify(state) == "succeeded"


def failed(state):
    return classify(state) == "failed"


def terminal(state):
    return classify(state) in ("succeeded", "failed", "cancelled", "replaced")
