"""Application status state machine: pure, so every edge is a plain test (DESIGN §5 F4)."""

import pytest

from app.services.state_machine import (
    FINAL,
    INITIAL,
    ORDER,
    STATUSES,
    TRANSITIONS,
    can_move,
    can_start,
    next_statuses,
)

ALLOWED = {
    ("interested", "applied"),
    ("interested", "withdrawn"),
    ("applied", "test"),
    ("applied", "interview"),  # many drives have no test round
    ("applied", "rejected"),
    ("applied", "withdrawn"),
    ("test", "interview"),
    ("test", "rejected"),
    ("test", "withdrawn"),
    ("interview", "offer"),
    ("interview", "rejected"),
    ("interview", "withdrawn"),
}


@pytest.mark.parametrize("move", sorted(ALLOWED))
def test_allowed_moves(move: tuple[str, str]) -> None:
    assert can_move(*move)


@pytest.mark.parametrize(
    "move",
    sorted((a, b) for a in STATUSES for b in STATUSES if a != b and (a, b) not in ALLOWED),
)
def test_every_other_move_is_refused(move: tuple[str, str]) -> None:
    assert not can_move(*move)


@pytest.mark.parametrize("status", sorted(FINAL))
def test_final_states_have_no_way_out(status: str) -> None:
    assert TRANSITIONS[status] == frozenset()


def test_final_states_are_offer_rejected_withdrawn() -> None:
    assert frozenset({"offer", "rejected", "withdrawn"}) == FINAL


def test_every_non_final_state_can_be_withdrawn() -> None:
    assert all(can_move(status, "withdrawn") for status in STATUSES - FINAL)


def test_staying_in_the_same_state_is_not_a_move() -> None:
    assert not can_move("applied", "applied")


def test_unknown_statuses_are_refused() -> None:
    assert not can_move("applied", "hired")
    assert not can_move("ghosted", "applied")


def test_tracking_starts_at_interested_or_applied() -> None:
    assert frozenset({"interested", "applied"}) == INITIAL
    assert can_start("applied")
    assert not can_start("offer")  # can't start at the end


def test_every_state_is_reachable_from_a_start() -> None:
    reached = set(INITIAL)
    frontier = list(INITIAL)
    while frontier:
        for nxt in TRANSITIONS[frontier.pop()]:
            if nxt not in reached:
                reached.add(nxt)
                frontier.append(nxt)
    assert reached == STATUSES


# ---------------------------------------------------------------- next_statuses (Day 7)


def test_order_lists_every_status_once() -> None:
    assert sorted(ORDER) == sorted(STATUSES)
    assert len(ORDER) == len(STATUSES)


def test_next_statuses_before_tracking_are_the_starts() -> None:
    assert next_statuses(None) == ["interested", "applied"]


@pytest.mark.parametrize("current", sorted(STATUSES))
def test_next_statuses_match_the_transitions_dict(current: str) -> None:
    nexts = next_statuses(current)
    assert set(nexts) == TRANSITIONS[current]  # same policy, no second copy
    assert nexts == sorted(nexts, key=ORDER.index)  # stable display order
    assert all(can_move(current, new) for new in nexts)


def test_final_states_offer_nothing() -> None:
    assert all(next_statuses(status) == [] for status in FINAL)


def test_applied_offers_the_happy_path_first() -> None:
    assert next_statuses("applied") == ["test", "interview", "rejected", "withdrawn"]
