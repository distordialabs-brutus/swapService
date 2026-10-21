"""Reject reported prior execution; injected evidence is not a history attestation."""
from __future__ import annotations

import copy
import json

import pytest

from test_custody_external_launcher import (
    CONTAINER, IMAGE, approved_config, candidate, load_launcher,
)


@pytest.mark.parametrize("started_at", [
    "2026-10-20T12:34:56.123456789Z", "0001-01-01T00:00:00.000000000Z",
    "0001-01-01T00:00:00+00:00", "0000-01-01T00:00:00Z", "", "private-token",
    "0001-01-01T00:00:00Z\n", None, False, True, 0, 0.0, [], {},
    ["0001-01-01T00:00:00Z"], "missing",
])
@pytest.mark.parametrize("inspection", [1, 2])
def test_reported_prior_start_refuses_before_later_actions(
        monkeypatch, capsys, inspection, started_at):
    launcher = load_launcher()
    value = candidate()
    value["State"]["StartedAt"] = "0001-01-01T00:00:00Z"
    changed = copy.deepcopy(value)
    if started_at == "missing":
        del changed["State"]["StartedAt"]
    else:
        changed["State"]["StartedAt"] = started_at
    # State is intentionally outside the approval projection. Matching pins do
    # not make a created-status observation proof of no previous execution.
    assert approved_config(value) == approved_config(changed)
    calls = []
    inspections = 0

    def engine(args, *, attach=False):
        nonlocal inspections
        calls.append((args, attach))
        if args[0] == "inspect":
            inspections += 1
            return json.dumps([changed if inspections == inspection else value])
        if args[0] == "diff":
            return ""
        assert args == ["start", "--attach", CONTAINER] and attach
        return 7

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(changed)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: container prior execution is not excluded\n"
    expected = ["inspect"] if inspection == 1 else ["inspect", "diff", "inspect"]
    assert [args[0] for args, _ in calls] == expected


@pytest.mark.parametrize("exit_code", [0, 7])
def test_canonical_zero_start_preserves_exact_one_start_and_exit(monkeypatch, capsys, exit_code):
    launcher = load_launcher()
    value = candidate()
    assert value["State"]["StartedAt"] == "0001-01-01T00:00:00Z"
    calls = []

    def engine(args, *, attach=False):
        calls.append((args, attach))
        if args[0] == "inspect":
            assert args == ["inspect", "--type=container", CONTAINER] and not attach
            return json.dumps([value])
        if args[0] == "diff":
            assert args == ["diff", CONTAINER] and not attach
            return ""
        assert args == ["start", "--attach", CONTAINER] and attach
        return exit_code

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == exit_code
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect", "diff", "start"]
