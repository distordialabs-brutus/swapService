"""Docker-reported candidate seccomp override containment, not effective filtering."""
from __future__ import annotations

import copy
import json

import pytest

from test_custody_external_launcher import (
    CONTAINER, IMAGE, approved_config, candidate, load_launcher,
)


@pytest.mark.parametrize("options", [
    ["no-new-privileges", "seccomp=unconfined"],
    ["seccomp:unconfined", "no-new-privileges"],
    ["no-new-privileges", "seccomp=builtin"],
    ["seccomp:builtin", "no-new-privileges=true"],
    ["no-new-privileges=true", "seccomp=default"],
    ["seccomp:default", "no-new-privileges=true"],
    ["no-new-privileges", "seccomp=/private/profile.json"],
    ["no-new-privileges", 'seccomp={"defaultAction":"SCMP_ACT_ALLOW"}'],
    ["no-new-privileges", "seccomp="],
    ["no-new-privileges", "seccomp:"],
    ["no-new-privileges", "seccomp"],
    ["no-new-privileges", "seccomp==private"],
    ["no-new-privileges", "seccomp=default", "seccomp=unconfined"],
    ["no-new-privileges", "seccomp=unconfined", "seccomp=default"],
    ["seccomp:unconfined", "no-new-privileges", "seccomp=default"],
    ["seccomp=default", "no-new-privileges", "seccomp:unconfined"],
])
def test_seccomp_override_refuses_matching_approval(monkeypatch, capsys, options):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["SecurityOpt"] = options
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
    assert captured.err == "custody launcher refused: container seccomp override is not permitted\n"
    assert [args[0] for args, _ in calls] == ["inspect"]


@pytest.mark.parametrize("options", [
    "missing", None, False, True, 0, 0.0, {}, "seccomp=unconfined",
    [None], [False], [0], [[]], [{}],
    ["no-new-privileges", {"seccomp": "private-evidence"}],
    ["no-new-privileges", ["seccomp=unconfined"]],
])
def test_invalid_security_option_shape_refuses_safely(monkeypatch, capsys, options):
    launcher = load_launcher()
    value = candidate()
    if options == "missing":
        value["HostConfig"].pop("SecurityOpt", None)
    else:
        value["HostConfig"]["SecurityOpt"] = options
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        return 7

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    # Preserved owner-only NNP validation may refuse malformed evidence earlier.
    assert captured.err in {
        "custody launcher refused: container seccomp override is not permitted\n",
        "custody launcher refused: container no-new-privileges policy is required\n",
    }
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("options", [
    ["no-new-privileges", "seccomp=unconfined"],
    ["seccomp:unconfined", "no-new-privileges"],
    ["no-new-privileges", "seccomp=default"],
    ["no-new-privileges", "seccomp=/private/profile.json"],
    "missing", None, ["no-new-privileges", {}],
    ["no-new-privileges=true"],
])
def test_seccomp_evidence_drift_refuses_before_later_diff_or_start(monkeypatch, capsys, options):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["SecurityOpt"] = ["no-new-privileges"]
    changed = copy.deepcopy(value)
    if options == "missing":
        del changed["HostConfig"]["SecurityOpt"]
    else:
        changed["HostConfig"]["SecurityOpt"] = options
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
        return 7

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: container configuration does not match independent approval\n"
    assert [args[0] for args in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("options", [
    ["no-new-privileges"], ["no-new-privileges=true"],
    ["apparmor=docker-default", "no-new-privileges"],
    ["no-new-privileges", "writable-cgroups=false"],
])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_daemon_seccomp_policy_preserves_exact_start_and_exit(monkeypatch, capsys, options, exit_code):
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
        return exit_code

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == exit_code
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect", "diff", "start"]
