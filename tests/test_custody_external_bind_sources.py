"""Lexical host bind-source containment; not host filesystem authorization."""
from __future__ import annotations

import copy
import json

import pytest

from test_custody_external_launcher import (
    CONTAINER, IMAGE, approved_config, candidate, load_launcher,
)


def set_source(value, mount_index, source):
    value["Mounts"][mount_index]["Source"] = source
    value["HostConfig"]["Mounts"][mount_index]["Source"] = source


@pytest.mark.parametrize("mount_index", [0, 1])
@pytest.mark.parametrize("source", [
    "/", "//", "/.", "/..", "/protected/..", "/protected/../custody",
    "//protected/custody", "/protected//custody", "/protected/./custody",
    "/protected/custody/", "/private-token\x00/custody", "", "relative/custody",
    None, False, 0, 0.0, [], {},
])
def test_noncanonical_or_root_bind_refuses_matching_approval(
        monkeypatch, capsys, mount_index, source):
    launcher = load_launcher()
    value = candidate()
    set_source(value, mount_index, source)
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
    assert captured.err == "custody launcher refused: container has an unsupported mutable mount\n"
    assert [args[0] for args, _ in calls] == ["inspect"]


@pytest.mark.parametrize("mount_index", [0, 1])
@pytest.mark.parametrize("change", ["root", "different-canonical", "declared-only", "observed-only"])
def test_source_drift_refuses_before_later_diff_or_start(monkeypatch, capsys, mount_index, change):
    launcher = load_launcher()
    value = candidate()
    changed = copy.deepcopy(value)
    if change == "root":
        set_source(changed, mount_index, "/")
    elif change == "different-canonical":
        set_source(changed, mount_index, "/private-token/other")
    elif change == "declared-only":
        changed["HostConfig"]["Mounts"][mount_index]["Source"] = "/"
    else:
        changed["Mounts"][mount_index]["Source"] = "/"
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
        pytest.fail("changed source reached start")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: container configuration does not match independent approval\n"
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("mount_index", [0, 1])
@pytest.mark.parametrize("side", ["declared", "observed"])
def test_source_disagreement_is_not_normalized(monkeypatch, capsys, mount_index, side):
    launcher = load_launcher()
    value = candidate()
    if side == "declared":
        value["HostConfig"]["Mounts"][mount_index]["Source"] += "/."
    else:
        value["Mounts"][mount_index]["Source"] += "/."
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("source disagreement reached start")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "private-token" not in captured.err
    assert captured.err == (
        "custody launcher refused: container bind mount policy is inconsistent\n"
        if side == "declared" else
        "custody launcher refused: container has an unsupported mutable mount\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("source", ["/custody", "/protected/custody", "/protected/.custody",
                                   "/protected/custody..backup", "/protected/custody space"])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_canonical_nonroot_sources_preserve_exact_start_and_exit(monkeypatch, capsys, source, exit_code):
    launcher = load_launcher()
    value = candidate()
    set_source(value, 0, source)
    set_source(value, 1, source + "-secrets")
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
