"""Finite Docker-reported candidate supplementary-group restriction."""
from __future__ import annotations

import copy
import json

import pytest

from test_custody_external_launcher import (
    CONTAINER, IMAGE, approved_config, candidate, load_launcher,
)


@pytest.mark.parametrize("groups", [
    ["0"], ["root"], ["1000"], ["private-group"], ["0", "1000"],
    "0", "", 0, 0.0, False, True, {}, {"private-group": 0},
    [0], [None], [False], [[]], [{}], "missing",
])
def test_added_or_invalid_groups_refuse_matching_approval(monkeypatch, capsys, groups):
    launcher = load_launcher()
    value = candidate()
    if groups == "missing":
        del value["HostConfig"]["GroupAdd"]
    else:
        value["HostConfig"]["GroupAdd"] = groups
    calls = []

    def engine(args, *, attach=False):
        calls.append((args, attach))
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        assert args == ["start", "--attach", CONTAINER] and attach
        return 7

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: container supplementary group additions are not disabled\n"
    assert [args[0] for args, _ in calls] == ["inspect"]


@pytest.mark.parametrize("groups", [["0"], ["private-group"], False, "missing", []])
def test_group_evidence_drift_refuses_before_later_diff_or_start(monkeypatch, capsys, groups):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["GroupAdd"] = None
    changed = copy.deepcopy(value)
    if groups == "missing":
        del changed["HostConfig"]["GroupAdd"]
    else:
        changed["HostConfig"]["GroupAdd"] = groups
    calls = []
    inspections = 0

    def engine(args, *, attach=False):
        nonlocal inspections
        calls.append(args)
        if args[0] == "inspect":
            inspections += 1
            return json.dumps([changed if inspections == 2 else value])
        if args[0] == "diff":
            return ""
        pytest.fail("changed group evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: container configuration does not match independent approval\n"
    assert [args[0] for args in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("groups", [None, []])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_no_group_additions_preserve_exact_start_and_exit(monkeypatch, capsys, groups, exit_code):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["GroupAdd"] = groups
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
