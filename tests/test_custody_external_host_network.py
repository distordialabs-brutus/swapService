"""Candidate host-network namespace containment, not endpoint/egress attestation."""
from __future__ import annotations

import copy
import json

import pytest

from test_custody_external_launcher import (
    CONTAINER, IMAGE, approved_config, candidate, load_launcher,
)


@pytest.mark.parametrize("networks", [{}, {"host": {"Aliases": None}}])
def test_host_network_refuses_matching_approval(monkeypatch, capsys, networks):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["NetworkMode"] = "host"
    value["NetworkSettings"] = {"Networks": networks}
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
    assert captured.err == "custody launcher refused: container host networking is not permitted\n"
    assert [args[0] for args, _ in calls] == ["inspect"]


@pytest.mark.parametrize("change_endpoints", [False, True])
def test_host_network_drift_refuses_before_later_diff_or_start(monkeypatch, capsys, change_endpoints):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["NetworkMode"] = "bridge"
    changed = copy.deepcopy(value)
    changed["HostConfig"]["NetworkMode"] = "host"
    if change_endpoints:
        changed["NetworkSettings"] = {"Networks": {"host": {"Aliases": None}}}
    calls = []
    inspections = 0

    def engine(args, *, attach=False):
        nonlocal inspections
        calls.append((args, attach))
        if args[0] == "inspect":
            inspections += 1
            return json.dumps([changed if inspections == 2 else value])
        if args[0] == "diff":
            return ""
        return 7

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: container configuration does not match independent approval\n"
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("mode", ["bridge", "default", "none", "approved-network", "hostile"])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_nonhost_network_preserves_exact_start_and_exit(monkeypatch, capsys, mode, exit_code):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["NetworkMode"] = mode
    value["NetworkSettings"] = {"Networks": {} if mode == "none" else {mode: {"Aliases": None}}}
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
