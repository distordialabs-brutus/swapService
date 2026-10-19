"""Only the selected Docker-reported AppArmor profile is supported offline."""
from __future__ import annotations

import copy
import json

import pytest

from test_custody_external_launcher import (
    CONTAINER, IMAGE, approved_config, candidate, load_launcher,
)


@pytest.mark.parametrize("profile", [
    "unconfined", "", "custom-private-profile", "docker-default ", "Docker-default",
    None, False, True, 0, 0.0, [], {}, ["docker-default"],
])
@pytest.mark.parametrize("inspection", [1, 2])
def test_unsupported_apparmor_refuses_matching_approval(monkeypatch, capsys, profile, inspection):
    launcher = load_launcher()
    value = candidate()
    value["AppArmorProfile"] = profile
    calls = []
    inspected = 0

    def engine(args, *, attach=False):
        nonlocal inspected
        calls.append((args, attach))
        if args[0] == "inspect":
            inspected += 1
            seen = value if inspected == inspection else candidate()
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        assert args == ["start", "--attach", CONTAINER] and attach
        return 7

    monkeypatch.setattr(launcher, "_engine", engine)
    approval = approved_config(value if inspection == 1 else candidate())
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approval]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    reason = ("container supported AppArmor profile is required" if inspection == 1
              else "container configuration does not match independent approval")
    assert captured.err == f"custody launcher refused: {reason}\n"
    assert [args[0] for args, _ in calls] == (
        ["inspect"] if inspection == 1 else ["inspect", "diff", "inspect"]
    )


@pytest.mark.parametrize("inspection", [1, 2])
def test_missing_apparmor_refuses_without_evidence_disclosure(monkeypatch, capsys, inspection):
    launcher = load_launcher()
    value = candidate()
    changed = copy.deepcopy(value)
    del changed["AppArmorProfile"]
    calls = []
    inspected = 0

    def engine(args, *, attach=False):
        nonlocal inspected
        calls.append(args)
        if args[0] == "inspect":
            inspected += 1
            return json.dumps([changed if inspected == inspection else value])
        if args[0] == "diff":
            return ""
        pytest.fail("missing profile evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: local container evidence is invalid\n"
    assert [args[0] for args in calls] == (
        ["inspect"] if inspection == 1 else ["inspect", "diff", "inspect"]
    )


@pytest.mark.parametrize("exit_code", [0, 7])
def test_docker_default_profile_preserves_exact_start_and_exit(monkeypatch, capsys, exit_code):
    launcher = load_launcher()
    value = candidate()
    assert value["AppArmorProfile"] == "docker-default"
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
