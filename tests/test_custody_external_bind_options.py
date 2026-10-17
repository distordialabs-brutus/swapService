"""Bind-policy booleans must not accept JSON numbers via Python equality."""
from __future__ import annotations

import json

import pytest

from test_custody_external_launcher import (
    CONTAINER, IMAGE, approved_config, candidate, load_launcher,
)


@pytest.mark.parametrize("read_only_nonrecursive", [
    0, 0.0, -0.0, True, 1, 1.0, "false", "private-evidence", [], {}, [False],
])
@pytest.mark.parametrize("mount_index", [0, 1], ids=["custody", "secrets"])
def test_invalid_readonly_nonrecursive_refuses_matching_approval(
    monkeypatch, capsys, read_only_nonrecursive, mount_index,
):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["Mounts"][mount_index]["BindOptions"]["ReadOnlyNonRecursive"] = read_only_nonrecursive
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
    assert captured.err == "custody launcher refused: container bind mount policy is inconsistent\n"
    assert [args[0] for args, _ in calls] == ["inspect"]


@pytest.mark.parametrize("custody_option", ["absent", None, False])
@pytest.mark.parametrize("secrets_option", ["absent", None, False])
def test_disabled_readonly_nonrecursive_preserves_exact_start_and_exit(
    monkeypatch, capsys, custody_option, secrets_option,
):
    launcher = load_launcher()
    value = candidate()
    for mount, setting in zip(value["HostConfig"]["Mounts"], (custody_option, secrets_option)):
        options = mount["BindOptions"]
        if setting == "absent":
            options.pop("ReadOnlyNonRecursive", None)
        else:
            options["ReadOnlyNonRecursive"] = setting
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


@pytest.mark.parametrize("read_only_nonrecursive", [0, 0.0])
@pytest.mark.parametrize("mount_index", [0, 1], ids=["custody", "secrets"])
def test_readonly_nonrecursive_drift_between_inspections_refuses(
    monkeypatch, capsys, read_only_nonrecursive, mount_index,
):
    launcher = load_launcher()
    value = candidate()
    options = value["HostConfig"]["Mounts"][mount_index]["BindOptions"]
    options["ReadOnlyNonRecursive"] = False
    approval = approved_config(value)
    calls = []
    inspections = 0

    def engine(args, *, attach=False):
        nonlocal inspections
        calls.append(args)
        if args[0] == "inspect":
            inspections += 1
            if inspections == 2:
                options["ReadOnlyNonRecursive"] = read_only_nonrecursive
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("changed bind evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approval]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args in calls] == ["inspect", "diff", "inspect"]
