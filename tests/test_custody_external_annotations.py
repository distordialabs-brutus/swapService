"""Candidate-supplied OCI annotations must not configure the trusted runtime."""
from __future__ import annotations

import copy
import json

import pytest

from test_custody_external_launcher import (
    CONTAINER, IMAGE, approved_config, candidate, load_launcher,
)


@pytest.mark.parametrize("annotations", [
    {"org.systemd.property.CollectMode": "'inactive-or-failed'"},
    {"bundle": "/outside-approved-image"},
    {"org.criu.config": "/outside-approved-image"},
    {"example.metadata": "private-evidence"},
    [], ["private-evidence"], "private-evidence", False, 0, True,
])
def test_runtime_annotations_refuse_even_with_matching_approval(monkeypatch, capsys, annotations):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["Annotations"] = annotations
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
    assert captured.err == "custody launcher refused: container runtime annotations are not disabled\n"
    assert [args[0] for args, _ in calls] == ["inspect"]


@pytest.mark.parametrize("annotations", [
    {"org.systemd.property.CollectMode": "'inactive-or-failed'"},
    {"example.metadata": "private-evidence"}, [],
])
def test_runtime_annotation_drift_refuses_before_second_diff(monkeypatch, capsys, annotations):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["Annotations"] = {}
    calls = []
    inspected = 0

    def engine(args, *, attach=False):
        nonlocal inspected
        calls.append((args, attach))
        if args[0] == "inspect":
            inspected += 1
            seen = copy.deepcopy(value)
            if inspected == 2:
                seen["HostConfig"]["Annotations"] = annotations
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        pytest.fail("runtime annotation drift reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("annotations", ["missing", None, {}])
def test_disabled_runtime_annotations_preserve_exact_start_and_exit(monkeypatch, capsys, annotations):
    launcher = load_launcher()
    value = candidate()
    if annotations == "missing":
        value["HostConfig"].pop("Annotations", None)
    else:
        value["HostConfig"]["Annotations"] = annotations
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
                          "--approved-config", approved_config(value)]) == 7
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect", "diff", "start"]
