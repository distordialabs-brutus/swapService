"""A created container with prior startup failure is not a pristine candidate."""
from __future__ import annotations

import copy
import json

import pytest

from test_custody_external_launcher import (
    CONTAINER, IMAGE, approved_config, candidate, load_launcher,
)


@pytest.mark.parametrize("error", [
    "OCI runtime create failed: private-evidence", " ", "missing",
    None, False, True, 0, 0.0, 1, [], {}, ["private-evidence"],
])
@pytest.mark.parametrize("inspection", [1, 2])
def test_prior_start_failure_refuses_matching_approval(monkeypatch, capsys, error, inspection):
    launcher = load_launcher()
    value = candidate()
    changed = copy.deepcopy(value)
    if error == "missing":
        changed["State"].pop("Error")
    else:
        changed["State"]["Error"] = error
    # State is deliberately outside the approval projection. A matching pin
    # must not exempt error evidence on either read, including read-two drift.
    assert approved_config(changed) == approved_config(value)
    calls = []
    inspected = 0

    def engine(args, *, attach=False):
        nonlocal inspected
        calls.append((args, attach))
        if args[0] == "inspect":
            inspected += 1
            return json.dumps([changed if inspected == inspection else value])
        if args[0] == "diff":
            return ""
        assert args == ["start", "--attach", CONTAINER] and attach
        return 7

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: container prior startup failure is not excluded\n"
    assert [args[0] for args, _ in calls] == (
        ["inspect"] if inspection == 1 else ["inspect", "diff", "inspect"]
    )


@pytest.mark.parametrize("state", [None, [], "private-evidence", False, 0])
def test_nonobject_start_failure_evidence_refuses(monkeypatch, capsys, state):
    launcher = load_launcher()
    value = candidate()
    value["State"] = state
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("malformed startup state reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: container prior startup failure is not excluded\n"
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("exit_code", [0, 7])
def test_empty_start_error_preserves_exact_start_and_exit(monkeypatch, capsys, exit_code):
    launcher = load_launcher()
    value = candidate()
    assert value["State"]["Error"] == ""
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
