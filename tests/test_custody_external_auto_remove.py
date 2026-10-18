"""Retain admitted-container evidence rather than authorize daemon auto-removal."""
from __future__ import annotations

import json

import pytest

from test_custody_external_launcher import (
    CONTAINER, IMAGE, approved_config, candidate, load_launcher,
)


@pytest.mark.parametrize("auto_remove", [True, "missing", None, 0, 0.0, 1, "false", [], {}])
def test_auto_removal_refuses_even_with_matching_approval(monkeypatch, capsys, auto_remove):
    launcher = load_launcher()
    value = candidate()
    if auto_remove == "missing":
        value["HostConfig"].pop("AutoRemove")
    else:
        value["HostConfig"]["AutoRemove"] = auto_remove
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
    assert captured.err == "custody launcher refused: container automatic removal is not disabled\n"
    assert [args[0] for args, _ in calls] == ["inspect"]


@pytest.mark.parametrize("auto_remove", [True, "missing", None, 0, "false"])
def test_auto_removal_drift_refuses_before_second_diff(monkeypatch, capsys, auto_remove):
    launcher = load_launcher()
    value = candidate()
    calls = []

    def engine(args, *, attach=False):
        calls.append((args, attach))
        if args[0] == "inspect":
            seen = candidate()
            if len(calls) == 3:
                if auto_remove == "missing":
                    seen["HostConfig"].pop("AutoRemove")
                else:
                    seen["HostConfig"]["AutoRemove"] = auto_remove
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        pytest.fail("changed removal policy reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("exit_status", [0, 7, 125])
def test_retained_container_preserves_exact_start_and_exit(monkeypatch, capsys, exit_status):
    launcher = load_launcher()
    value = candidate()
    assert value["HostConfig"]["AutoRemove"] is False
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
        return exit_status

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == exit_status
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect", "diff", "start"]
