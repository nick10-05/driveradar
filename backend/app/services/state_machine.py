"""Application status state machine (DESIGN §5 F4).

    interested → applied → (test →) interview → offer
                    │        │          │
                    └────────┴──────────┴──→ rejected
    any non-final state ──→ withdrawn

Interview notes:
- Every allowed move lives in ONE dict. "Can I go from A to B?" is a lookup, not a chain
  of ifs spread over handlers, and the whole policy fits on a screen and in one test.
- Anything not in the dict is refused (HTTP 409 at the API). Default-deny: a new status
  can't accidentally become reachable from everywhere.
- Final states (offer, rejected, withdrawn) have no way out. A mistake there is rare and
  better fixed deliberately than by allowing "rejected → offer" for everyone.
- applied → interview skips the test: many drives have no test round (DESIGN §5 F4).
- Pure: no DB. The service records each accepted move as an application_events row,
  which gives every application a timeline.
"""

STATUSES = frozenset(
    {"interested", "applied", "test", "interview", "offer", "rejected", "withdrawn"}
)

TRANSITIONS: dict[str, frozenset[str]] = {
    "interested": frozenset({"applied", "withdrawn"}),
    "applied": frozenset({"test", "interview", "rejected", "withdrawn"}),
    "test": frozenset({"interview", "rejected", "withdrawn"}),
    "interview": frozenset({"offer", "rejected", "withdrawn"}),
    "offer": frozenset(),
    "rejected": frozenset(),
    "withdrawn": frozenset(),
}

FINAL = frozenset(status for status, nexts in TRANSITIONS.items() if not nexts)

# Where tracking can begin: "I'm interested" or "I already applied".
INITIAL = frozenset({"interested", "applied"})


def can_move(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, frozenset())


def can_start(status: str) -> bool:
    return status in INITIAL
