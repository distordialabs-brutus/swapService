"""Finite Docker-reported non-root primary runtime identity policy."""
from __future__ import annotations

import copy
import json

import pytest

from test_custody_external_launcher import (
    CONTAINER, IMAGE, approved_config, candidate, load_launcher,
)


@pytest.mark.parametrize("user", [
    "0:0", "0:1000", "1000:0", "", "root", "root:root", "root:1000", "1000:root",
    "private-account:private-group", "1000", "1000:", ":1000", "1000:1000:1000",
    "00:1000", "01000:1000", "1000:01000", "+1000:1000", "1000:+1000",
    "-1:1000", "1000:-1", " 1000:1000", "1000:1000 ", "1000:1000\n",
    "١٠٠٠:١٠٠٠", "1000:1.0", "1e3:1000", "2147483648:1", "1:2147483648",
    "4294967296:1", "1:4294967296", "99999999999:1", "1:99999999999",
    None, False, True, 0, 1000, 1000.0, [], {}, ["1000:1000"],
])
def test_root_or_ambiguous_runtime_user_refuses_matching_approval(monkeypatch, capsys, user):
    launcher = load_launcher()
    value = candidate()
    value["Config"]["User"] = user
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
    assert captured.err == "custody launcher refused: container non-root numeric runtime identity is required\n"
    assert [args[0] for args, _ in calls] == ["inspect"]


def test_missing_runtime_user_refuses_matching_approval(monkeypatch, capsys):
    launcher = load_launcher()
    value = candidate()
    del value["Config"]["User"]
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("missing runtime identity reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: container non-root numeric runtime identity is required\n"
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("user", ["0:0", "root", None, "missing", "1001:1001"])
def test_runtime_user_drift_refuses_before_later_diff_or_start(monkeypatch, capsys, user):
    launcher = load_launcher()
    value = candidate()
    changed = copy.deepcopy(value)
    if user == "missing":
        del changed["Config"]["User"]
    else:
        changed["Config"]["User"] = user
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
        pytest.fail("changed runtime identity reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: container configuration does not match independent approval\n"
    assert [args[0] for args in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("user", [
    "1:1", "1000:1000", "65532:65532", "1:2147483647", "2147483647:1", "2147483647:2147483647",
])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_explicit_nonroot_primary_ids_preserve_exact_start_and_exit(monkeypatch, capsys, user, exit_code):
    launcher = load_launcher()
    value = candidate()
    value["Config"]["User"] = user
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
