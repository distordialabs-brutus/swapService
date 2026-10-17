"""Docker must not schedule extra commands outside the admitted entrypoint."""
from __future__ import annotations

import json

import pytest

from test_custody_external_launcher import (
    CONTAINER, IMAGE, approved_config, candidate, load_launcher,
)


@pytest.mark.parametrize("test", [
    ["CMD", "/usr/local/bin/python3", "/opt/swapService/swapService.py"],
    ["CMD-SHELL", "python3 /opt/swapService/swapService.py"],
])
def test_enabled_healthcheck_refuses_matching_approval(monkeypatch, capsys, test):
    launcher = load_launcher()
    value = candidate()
    value["Config"]["Healthcheck"] = {"Test": test}
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
    assert captured.err == "custody launcher refused: container automatic healthcheck is not disabled\n"
    assert [args[0] for args, _ in calls] == ["inspect"]


@pytest.mark.parametrize("healthcheck", [
    False, 0, 0.0, "NONE", [], ["NONE"], {}, {"Test": None},
    {"Test": []}, {"Test": "NONE"}, {"Test": ["none"]},
    {"Test": ["NONE", "private-command"]}, {"Test": [None]},
])
def test_invalid_healthcheck_evidence_refuses(monkeypatch, capsys, healthcheck):
    launcher = load_launcher()
    value = candidate()
    value["Config"]["Healthcheck"] = healthcheck
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("invalid healthcheck evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: container automatic healthcheck is not disabled\n"
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("config", [None, False, 0, 0.0, "private-config", [], ["NONE"]])
def test_nonobject_config_refuses_sanitized(monkeypatch, capsys, config):
    launcher = load_launcher()
    value = candidate()
    value["Config"] = config
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("invalid configuration reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: local container evidence is invalid\n"
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("healthcheck", [
    "absent", None, {"Test": ["NONE"]},
    {"Test": ["NONE"], "Interval": 30000000000, "Timeout": 3000000000, "Retries": 3},
])
def test_disabled_healthcheck_preserves_exact_start_and_exit(monkeypatch, capsys, healthcheck):
    launcher = load_launcher()
    value = candidate()
    if healthcheck == "absent":
        value["Config"].pop("Healthcheck", None)
    else:
        value["Config"]["Healthcheck"] = healthcheck
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


@pytest.mark.parametrize("healthcheck", [
    {"Test": ["CMD", "private-command"]}, {"Test": ["CMD-SHELL", "private-command"]},
    {"Test": []}, False,
])
def test_healthcheck_drift_between_inspections_refuses(monkeypatch, capsys, healthcheck):
    launcher = load_launcher()
    value = candidate()
    value["Config"]["Healthcheck"] = {"Test": ["NONE"]}
    calls = []
    inspections = 0

    def engine(args, *, attach=False):
        nonlocal inspections
        calls.append(args)
        if args[0] == "inspect":
            inspections += 1
            if inspections == 2:
                value["Config"]["Healthcheck"] = healthcheck
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("changed healthcheck reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args in calls] == ["inspect", "diff", "inspect"]
