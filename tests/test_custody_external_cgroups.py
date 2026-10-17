"""Candidate security options must not explicitly enable writable cgroups."""
from __future__ import annotations

import copy
import json

import pytest

from test_custody_external_launcher import (
    CONTAINER, IMAGE, approved_config, candidate, load_launcher,
)


@pytest.mark.parametrize("option", [
    "writable-cgroups", "writable-cgroups=true", "writable-cgroups=1",
    "writable-cgroups=TRUE", "writable-cgroups:true",
    "writable-cgroups=false=private-evidence", "writable-cgroups:",
    "writable-cgroups:false", "writable-cgroups=0",
])
@pytest.mark.parametrize("reverse", [False, True])
def test_writable_cgroups_refuses_matching_approval(monkeypatch, capsys, option, reverse):
    launcher = load_launcher()
    value = candidate()
    options = ["no-new-privileges", "writable-cgroups=false", option]
    value["HostConfig"]["SecurityOpt"] = options[::-1] if reverse else options
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
    assert captured.err == "custody launcher refused: container writable cgroups are not disabled\n"
    assert [args[0] for args, _ in calls] == ["inspect"]


@pytest.mark.parametrize("options", [
    ["no-new-privileges"],
    ["no-new-privileges", "writable-cgroups=false"],
    ["writable-cgroups=false", "no-new-privileges"],
    ["no-new-privileges", "writable-cgroups=false", "writable-cgroups=false"],
    ["no-new-privileges", "apparmor=docker-default", "writable-cgroups=false"],
    ["no-new-privileges", "label=type:approved"],
])
def test_disabled_cgroups_preserve_exact_start_and_exit(monkeypatch, capsys, options):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["SecurityOpt"] = options
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
        return 7

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 7
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect", "diff", "start"]


@pytest.mark.parametrize("option", ["writable-cgroups", "writable-cgroups=true", "writable-cgroups:true"])
def test_writable_cgroups_drift_refuses_before_second_diff(monkeypatch, capsys, option):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["SecurityOpt"] = ["no-new-privileges", "writable-cgroups=false"]
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            seen = copy.deepcopy(value)
            if len(calls) == 3:
                seen["HostConfig"]["SecurityOpt"].append(option)
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        pytest.fail("changed security evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args in calls] == ["inspect", "diff", "inspect"]
