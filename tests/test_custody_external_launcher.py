"""Offline external-launcher tests; the Docker authority is an injected boundary."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "custody_external_launcher.py"
IMAGE = "sha256:" + "a" * 64
CONTAINER = "b" * 64


def load_launcher():
    assert SCRIPT.is_file(), "external pre-execution image admission guard is missing"
    spec = importlib.util.spec_from_file_location("external_launcher", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("extra_hosts", [
    ["rpc.internal:host-gateway"],
    ["rpc.internal:192.0.2.10", "witness.internal:host-gateway"],
])
def test_extra_hosts_gateway_indirection_refuses_matching_approval(monkeypatch, capsys, extra_hosts):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["ExtraHosts"] = extra_hosts
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
    assert captured.err == "custody launcher refused: container extra-host gateway indirection is not disabled\n"
    assert [args[0] for args, _ in calls] == ["inspect"]


@pytest.mark.parametrize("extra_hosts", [False, 0, 0.0, "rpc:host-gateway", {}, [None], [False], [[]]])
def test_malformed_extra_hosts_refuse_without_exposing_evidence(monkeypatch, capsys, extra_hosts):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["ExtraHosts"] = extra_hosts
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("invalid extra-host evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: container extra-host gateway indirection is not disabled\n"
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("extra_hosts", [["rpc:host-gateway"], ["rpc:192.0.2.11"], [None]])
def test_extra_hosts_drift_between_checks_refuses(monkeypatch, capsys, extra_hosts):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["ExtraHosts"] = ["rpc:192.0.2.10"]
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            seen = copy.deepcopy(value)
            if len(calls) == 3:
                seen["HostConfig"]["ExtraHosts"] = extra_hosts
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        pytest.fail("changed extra-host evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("extra_hosts", [
    "missing", None, [], ["rpc:192.0.2.10"], ["rpc:2001:db8::10"],
    ["host-gateway:192.0.2.10", "witness:2001:db8::11"],
])
def test_literal_or_disabled_extra_hosts_preserve_start_and_exit(monkeypatch, capsys, extra_hosts):
    launcher = load_launcher()
    value = candidate()
    if extra_hosts == "missing":
        value["HostConfig"].pop("ExtraHosts", None)
    else:
        value["HostConfig"]["ExtraHosts"] = extra_hosts
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


@pytest.mark.parametrize("number", ["1e309", "-1e309", "1.7976931348623159e308"])
@pytest.mark.parametrize("inspection", [1, 2])
def test_overflowing_json_numbers_refuse_before_execution(monkeypatch, capsys, number, inspection):
    launcher = load_launcher()
    value = candidate()
    value["State"]["private-evidence"] = {"nested": ["number-placeholder"]}
    payload = json.dumps([value]).replace('"number-placeholder"', number)
    # These are standard JSON number lexemes, not NaN/Infinity constants.
    # The default decoder silently turns them into nonfinite float evidence.
    assert json.loads(payload)[0]["State"]["private-evidence"]["nested"][0] in (
        float("inf"), float("-inf")
    )
    calls = []
    inspected = 0

    def engine(args, *, attach=False):
        nonlocal inspected
        calls.append((args, attach))
        if args[0] == "inspect":
            inspected += 1
            return payload if inspected == inspection else json.dumps([candidate()])
        if args[0] == "diff":
            return ""
        assert args == ["start", "--attach", CONTAINER] and attach
        return 7

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: local container evidence is invalid\n"
    expected = ["inspect"] if inspection == 1 else ["inspect", "diff", "inspect"]
    assert [args[0] for args, _ in calls] == expected


@pytest.mark.parametrize("number", [
    "0.0", "-0.0", "1e-300", "-1e-300",
    "1.7976931348623157e308", "-1.7976931348623157e308",
    '"1e309"', "1" + "0" * 309,
])
def test_finite_json_numbers_preserve_exact_start_and_exit(monkeypatch, capsys, number):
    launcher = load_launcher()
    value = candidate()
    value["State"]["private-evidence"] = {"nested": ["number-placeholder"]}
    value["Config"]["numeric-evidence"] = "number-placeholder"
    payload = json.dumps([value]).replace('"number-placeholder"', number)
    # Independently use the pre-fix decoder/encoder to verify approval identity
    # is unchanged for finite floats, quoted text and arbitrary-precision integers.
    approval = approved_config(json.loads(payload)[0])
    calls = []

    def engine(args, *, attach=False):
        calls.append((args, attach))
        if args[0] == "inspect":
            return payload
        if args[0] == "diff":
            return ""
        assert args == ["start", "--attach", CONTAINER] and attach
        return 7

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approval]) == 7
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect", "diff", "start"]


@pytest.mark.parametrize("mode", ["host", "", None, False, 0, 0.0, [], {}, "missing"])
def test_nonprivate_cgroup_namespace_refuses(monkeypatch, capsys, mode):
    launcher = load_launcher()
    value = candidate()
    if mode == "missing":
        del value["HostConfig"]["CgroupnsMode"]
    else:
        value["HostConfig"]["CgroupnsMode"] = mode
    # A matching independent pin cannot exempt an unsafe namespace policy.
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
    assert captured.err == "custody launcher refused: container private cgroup namespace is required\n"
    assert [args[0] for args, _ in calls] == ["inspect"]


@pytest.mark.parametrize("mode", ["host", "", "missing"])
def test_cgroup_namespace_drift_between_checks_refuses(monkeypatch, capsys, mode):
    launcher = load_launcher()
    value = candidate()
    calls = []

    def engine(args, *, attach=False):
        calls.append((args, attach))
        if args[0] == "inspect":
            seen = copy.deepcopy(value)
            if len(calls) == 3:
                if mode == "missing":
                    del seen["HostConfig"]["CgroupnsMode"]
                else:
                    seen["HostConfig"]["CgroupnsMode"] = mode
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        pytest.fail("changed cgroup namespace reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect"]


# Independent minimum policy from Moby d74daf1a daemon/pkg/oci/defaults.go.
# Do not derive this inventory from the launcher under test.
SYSTEM_PATH_POLICY = {
    "MaskedPaths": [
        "/proc/acpi", "/proc/asound", "/proc/interrupts", "/proc/kcore",
        "/proc/keys", "/proc/latency_stats", "/proc/sched_debug", "/proc/scsi",
        "/proc/timer_list", "/proc/timer_stats", "/sys/devices/virtual/powercap",
        "/sys/firmware",
    ],
    "ReadonlyPaths": ["/proc/bus", "/proc/fs", "/proc/irq", "/proc/sys", "/proc/sysrq-trigger"],
}


@pytest.mark.parametrize("field", ["MaskedPaths", "ReadonlyPaths"])
@pytest.mark.parametrize("evidence", ["missing", None, [], {}, False, 0, "private-evidence", [None]])
def test_unconfined_system_paths_refuse_matching_approval(monkeypatch, capsys, field, evidence):
    launcher = load_launcher()
    value = candidate()
    if evidence == "missing":
        del value["HostConfig"][field]
    else:
        value["HostConfig"][field] = evidence
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
    assert captured.err == "custody launcher refused: container system path protections are required\n"
    assert [args[0] for args, _ in calls] == ["inspect"]


@pytest.mark.parametrize("field,path", [
    (field, path) for field, paths in SYSTEM_PATH_POLICY.items() for path in paths
])
def test_each_baseline_system_path_is_required(monkeypatch, capsys, field, path):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"][field].remove(path)
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
    assert capsys.readouterr().err == (
        "custody launcher refused: container system path protections are required\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("field", ["MaskedPaths", "ReadonlyPaths"])
@pytest.mark.parametrize("extra", [None, [], {}, False])
def test_complete_system_path_inventory_with_invalid_member_refuses(monkeypatch, capsys, field, extra):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"][field].append(extra)
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
    assert capsys.readouterr().err == (
        "custody launcher refused: container system path protections are required\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("field", ["MaskedPaths", "ReadonlyPaths"])
@pytest.mark.parametrize("change", ["missing", "empty", "partial"])
def test_system_path_drift_before_second_inspection_refuses(monkeypatch, capsys, field, change):
    launcher = load_launcher()
    value = candidate()
    calls = []

    def engine(args, *, attach=False):
        calls.append((args, attach))
        if args[0] == "inspect":
            seen = copy.deepcopy(value)
            if len(calls) == 3:
                if change == "missing":
                    del seen["HostConfig"][field]
                elif change == "empty":
                    seen["HostConfig"][field] = []
                else:
                    seen["HostConfig"][field].pop()
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        return 7

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("extra_paths", [False, True])
def test_confined_system_paths_preserve_exact_start_and_exit(monkeypatch, capsys, extra_paths):
    launcher = load_launcher()
    value = candidate()
    for field in SYSTEM_PATH_POLICY:
        value["HostConfig"][field].reverse()
        if extra_paths:
            value["HostConfig"][field].append("/independently-approved-extra")
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


@pytest.mark.parametrize("options", [
    "missing", None, [], {}, False, 0, 0.0, "no-new-privileges",
    ["seccomp=unconfined"], ["no-new-privileges=false"],
    ["no-new-privileges:0"], ["no-new-privileges=0"],
    ["no-new-privileges", "no-new-privileges:False"],
    ["no-new-privileges", "no-new-privileges=garbled"],
    ["no-new-privileges=true", {}], ["no-new-privileges=true", []],
    ["no-new-privileges=true", False], ["no-new-privileges=true", 0],
    ["no-new-privileges", "no-new-privileges=false"],
    ["no-new-privileges=false", "no-new-privileges"],
    ["no-new-privileges", "no-new-privileges:0"],
    ["no-new-privileges=true", None],
])
def test_privilege_gain_policy_refuses_matching_approval(monkeypatch, capsys, options):
    launcher = load_launcher()
    value = candidate()
    if options == "missing":
        value["HostConfig"].pop("SecurityOpt", None)
    else:
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
    assert captured.err == "custody launcher refused: container no-new-privileges policy is required\n"
    assert [args[0] for args, _ in calls] == ["inspect"]


@pytest.mark.parametrize("options", [
    ["no-new-privileges"], ["no-new-privileges=true"],
    ["apparmor=docker-default", "no-new-privileges=true"],
    ["no-new-privileges", "no-new-privileges=true"],
])
def test_no_new_privileges_preserves_exact_start_and_exit(monkeypatch, capsys, options):
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
                          "--approved-config", approved_config(value)]) == 7
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect", "diff", "start"]


@pytest.mark.parametrize("options", [None, [], ["no-new-privileges=false"], "missing"])
def test_no_new_privileges_drift_between_checks_refuses(monkeypatch, capsys, options):
    launcher = load_launcher()
    value = candidate()
    calls = []

    def engine(args, *, attach=False):
        calls.append((args, attach))
        if args[0] == "inspect":
            seen = copy.deepcopy(value)
            if len(calls) == 3:
                if options == "missing":
                    del seen["HostConfig"]["SecurityOpt"]
                else:
                    seen["HostConfig"]["SecurityOpt"] = options
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        pytest.fail("changed privilege policy reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect"]


def candidate():
    return {
        "Id": CONTAINER, "Image": IMAGE,
        "Path": "/usr/local/bin/python3", "Args": ["/opt/swapService/swapService.py"],
        "Config": {"Env": ["STATE_DB_PATH=/var/lib/swapservice/custody.db"],
                   "WorkingDir": "/opt/swapService", "User": "1000:1000"},
        "HostConfig": {"ReadonlyRootfs": True, "Privileged": False, "AutoRemove": False,
                       "UsernsMode": "", "GroupAdd": None,
                       "SecurityOpt": ["no-new-privileges"],
                       "CapDrop": ["ALL"], "CapAdd": None, "Tmpfs": {}, "Runtime": "runc",
                       "UTSMode": "", "PidMode": "", "CgroupnsMode": "private", "IpcMode": "private", "Init": False, "NetworkMode": "bridge",
                       "Devices": [], "DeviceCgroupRules": None, "DeviceRequests": None,
                       "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0}, "Links": None,
                       **copy.deepcopy(SYSTEM_PATH_POLICY),
                       "Mounts": [
                           {"Type": "bind", "Source": "/protected/custody", "Target": "/var/lib/swapservice",
                            "ReadOnly": False, "BindOptions": {"NonRecursive": True, "Propagation": "rprivate"}},
                           {"Type": "bind", "Source": "/protected/secrets", "Target": "/run/swapservice-secrets",
                            "ReadOnly": True, "BindOptions": {"NonRecursive": True, "Propagation": "rprivate"}},
                       ]},
        "Mounts": [
            {"Type": "bind", "Source": "/protected/custody", "Destination": "/var/lib/swapservice", "RW": True},
            {"Type": "bind", "Source": "/protected/secrets", "Destination": "/run/swapservice-secrets", "RW": False},
        ],
        "State": {"Status": "created", "Running": False, "Error": "",
                  "StartedAt": "0001-01-01T00:00:00Z"},
        "NetworkSettings": {"Networks": {"bridge": {"Aliases": None}}},
        "Platform": "linux", "AppArmorProfile": "docker-default",
        "ProcessLabel": "", "MountLabel": "",
    }


def approved_config(value):
    # Independent contract: exact execution command, config, host policy and mounts.
    selected = {key: value[key] for key in (
        "Image", "Path", "Args", "Config", "HostConfig", "Mounts", "NetworkSettings",
        "Platform", "AppArmorProfile", "ProcessLabel", "MountLabel",
    )}
    raw = json.dumps(selected, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def test_unapproved_image_refuses_before_repository_execution(monkeypatch):
    launcher = load_launcher()
    value = candidate()
    approval = approved_config(value)
    value["Image"] = "sha256:" + "c" * 64
    commands = []

    def engine(args, *, attach=False):
        commands.append((args, attach))
        assert args[0] == "inspect", "rejected image reached execution"
        return json.dumps([value])

    monkeypatch.setattr(launcher, "_engine", engine)
    with pytest.raises(launcher.LaunchError, match="image"):
        launcher.launch(CONTAINER, IMAGE, approval)
    assert all(command[0][0] != "start" for command in commands)


@pytest.mark.parametrize("field", ["Path", "Args", "Config", "HostConfig", "Mounts"])
def test_unapproved_execution_configuration_cannot_start(monkeypatch, field):
    launcher = load_launcher()
    value = candidate()
    approval = approved_config(value)
    value[field] = {"unapproved": "pre-import side effect"}
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        assert args[0] != "start"
        return json.dumps([value])

    monkeypatch.setattr(launcher, "_engine", engine)
    with pytest.raises(launcher.LaunchError):
        launcher.launch(CONTAINER, IMAGE, approval)
    assert not any(args[0] == "start" for args in calls)


def test_exact_immutable_execution_starts_once_after_two_checks(monkeypatch):
    launcher = load_launcher()
    value = candidate()
    calls = []

    def engine(args, *, attach=False):
        calls.append((args, attach))
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        assert args == ["start", "--attach", CONTAINER] and attach
        return 7  # Preserve the attached child's exit status, not a invented success.

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.launch(CONTAINER, IMAGE, approved_config(value)) == 7
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect", "diff", "start"]


@pytest.mark.parametrize("changed_file", [
    "/opt/swapService/swapService.py", "/opt/swapService/src/main.py",
    "/usr/local/bin/python3", "/usr/local/lib/python3.12/site-packages/httpx/__init__.py",
    "/usr/local/lib/python3.12/site-packages/solana/rpc/api.py",
    "/usr/local/lib/python3.12/site-packages/solders/rpc/requests.py",
    "/usr/local/lib/python3.12/os.py", "/usr/lib/libc.so.6",
    "/opt/swapService/src/__pycache__/main.cpython-312.pyc",
])
def test_changed_container_layer_cannot_execute_preimport_side_effect(monkeypatch, changed_file):
    launcher = load_launcher()
    value = candidate()
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        assert args[0] != "start"
        return json.dumps([value]) if args[0] == "inspect" else "C " + changed_file + "\n"

    monkeypatch.setattr(launcher, "_engine", engine)
    with pytest.raises(launcher.LaunchError, match="layer"):
        launcher.launch(CONTAINER, IMAGE, approved_config(value))
    assert not any(args[0] == "start" for args in calls)


@pytest.mark.parametrize("unsafe", [
    "writable_root", "privileged", "added_capability", "missing_cap_drop", "tmpfs",
    "code_mount", "writable_secrets", "anonymous_volume", "already_executed",
])
def test_unsafe_container_is_rejected_even_with_matching_config_pin(monkeypatch, unsafe):
    launcher = load_launcher()
    value = candidate()
    if unsafe == "writable_root":
        value["HostConfig"]["ReadonlyRootfs"] = False
    elif unsafe == "privileged":
        value["HostConfig"]["Privileged"] = True
    elif unsafe == "added_capability":
        value["HostConfig"]["CapAdd"] = ["SYS_ADMIN"]
    elif unsafe == "missing_cap_drop":
        value["HostConfig"]["CapDrop"] = []
    elif unsafe == "tmpfs":
        value["HostConfig"]["Tmpfs"] = {"/opt/swapService": "rw"}
    elif unsafe == "code_mount":
        value["Mounts"][0]["Destination"] = "/opt/swapService"
    elif unsafe == "writable_secrets":
        value["Mounts"][1]["RW"] = True
    elif unsafe == "anonymous_volume":
        value["Mounts"][0]["Type"] = "volume"
    else:
        value["State"]["Status"] = "exited"
    monkeypatch.setattr(launcher, "_engine", lambda args, **kwargs:
                        json.dumps([value]) if args[0] == "inspect" else "")
    with pytest.raises(launcher.LaunchError):
        launcher.launch(CONTAINER, IMAGE, approved_config(value))


@pytest.mark.parametrize("mode", ["container:mutable-donor", "container:" + "c" * 64])
def test_container_shared_network_refuses_matching_approval(monkeypatch, capsys, mode):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["NetworkMode"] = mode
    # Shared-network containers have no independent endpoint configuration.
    value["NetworkSettings"] = {"Networks": {}}
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        return 0

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container network file sharing is not disabled\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("mode", [None, False, 0, 0.0, [], {}, "", "missing"])
def test_missing_or_malformed_network_mode_refuses(monkeypatch, capsys, mode):
    launcher = load_launcher()
    value = candidate()
    if mode == "missing":
        del value["HostConfig"]["NetworkMode"]
    else:
        value["HostConfig"]["NetworkMode"] = mode
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("invalid network-mode evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container network file sharing is not disabled\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("mode", ["container:mutable-donor", None, "missing"])
def test_network_mode_drift_between_checks_refuses(monkeypatch, capsys, mode):
    launcher = load_launcher()
    value = candidate()
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            seen = copy.deepcopy(value)
            if len(calls) == 3:
                if mode == "missing":
                    del seen["HostConfig"]["NetworkMode"]
                else:
                    seen["HostConfig"]["NetworkMode"] = mode
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        pytest.fail("changed network-mode evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("mode", ["bridge", "default", "none", "approved-network"])
def test_noncontainer_network_modes_preserve_exact_start_and_exit(monkeypatch, mode):
    # This guard restricts donor-file sharing, not all host/private DNS or networking.
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["NetworkMode"] = mode
    value["NetworkSettings"] = {"Networks": {} if mode in {"none", "host"} else {mode: {"Aliases": None}}}
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
    assert launcher.launch(CONTAINER, IMAGE, approved_config(value)) == 7
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect", "diff", "start"]


def test_legacy_links_refuse_even_with_matching_approval(monkeypatch, capsys):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["Links"] = ["/mutable-donor:/service/donor"]
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        return 0

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container legacy links are not disabled\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("links", ["missing", False, 0, 0.0, "", "private-token", {}, [None], [""]])
def test_missing_or_malformed_legacy_links_refuse(monkeypatch, capsys, links):
    launcher = load_launcher()
    value = candidate()
    if links == "missing":
        del value["HostConfig"]["Links"]
    else:
        value["HostConfig"]["Links"] = links
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("invalid legacy-link evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container legacy links are not disabled\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("links", [["/mutable-donor:/service/donor"], "missing", False])
def test_legacy_link_drift_between_checks_refuses(monkeypatch, capsys, links):
    launcher = load_launcher()
    value = candidate()
    approval = approved_config(value)
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            seen = copy.deepcopy(value)
            if len(calls) == 3:
                if links == "missing":
                    del seen["HostConfig"]["Links"]
                else:
                    seen["HostConfig"]["Links"] = links
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        pytest.fail("changed legacy-link evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approval]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("links", [None, []])
def test_disabled_legacy_links_preserve_exact_start_and_exit(monkeypatch, links):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["Links"] = links
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
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect", "diff", "start"]


def test_daemon_init_refuses_even_with_matching_approval(monkeypatch, capsys):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["Init"] = True
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        return 0

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container daemon-supplied init is not disabled\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("init", ["missing", None, 0, 0.0, "false", "private-token", [], {}, [False]])
def test_missing_or_malformed_init_evidence_refuses(monkeypatch, capsys, init):
    launcher = load_launcher()
    value = candidate()
    if init == "missing":
        del value["HostConfig"]["Init"]
    else:
        value["HostConfig"]["Init"] = init
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("invalid init evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container daemon-supplied init is not disabled\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("init", [True, None, "missing"])
def test_init_drift_between_checks_never_starts(monkeypatch, capsys, init):
    launcher = load_launcher()
    value = candidate()
    approval = approved_config(value)
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            seen = copy.deepcopy(value)
            if len(calls) == 3:
                if init == "missing":
                    del seen["HostConfig"]["Init"]
                else:
                    seen["HostConfig"]["Init"] = init
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        pytest.fail("changed init evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approval]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("runtime", ["nvidia", "unapproved-runtime"])
def test_alternate_runtime_refuses_even_with_matching_approval(monkeypatch, capsys, runtime):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["Runtime"] = runtime
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        return 0

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container conventional runtime is required\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("runtime", ["missing", None, [], {}, False, 0, "", "RUNC", ["runc"]])
def test_missing_or_malformed_runtime_evidence_refuses(monkeypatch, capsys, runtime):
    launcher = load_launcher()
    value = candidate()
    if runtime == "missing":
        del value["HostConfig"]["Runtime"]
    else:
        value["HostConfig"]["Runtime"] = runtime
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("invalid runtime evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container conventional runtime is required\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("runtime", ["nvidia", "unapproved-runtime"])
def test_runtime_drift_between_checks_never_starts(monkeypatch, capsys, runtime):
    launcher = load_launcher()
    value = candidate()
    approval = approved_config(value)
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            seen = copy.deepcopy(value)
            if len(calls) == 3:
                seen["HostConfig"]["Runtime"] = runtime
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        pytest.fail("changed runtime reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approval]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("field,evidence", [
    ("Devices", [{"PathOnHost": "/dev/sda", "PathInContainer": "/dev/host-storage",
                  "CgroupPermissions": "rwm"}]),
    ("DeviceCgroupRules", ["a *:* rwm"]),
    ("DeviceRequests", [{"Driver": "unapproved", "Count": -1, "DeviceIDs": [],
                         "Capabilities": [["gpu"]], "Options": {}}]),
])
def test_host_device_access_refuses_even_with_matching_approval(monkeypatch, capsys, field, evidence):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"][field] = evidence
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        return 0

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container host-device access is not disabled\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("field", ["Devices", "DeviceCgroupRules", "DeviceRequests"])
@pytest.mark.parametrize("evidence", ["missing", {}, False, 0, "", "private-token", [None]])
def test_missing_or_malformed_device_evidence_refuses(monkeypatch, capsys, field, evidence):
    launcher = load_launcher()
    value = candidate()
    if evidence == "missing":
        del value["HostConfig"][field]
    else:
        value["HostConfig"][field] = evidence
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("invalid device evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container host-device access is not disabled\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("devices", [None, []])
@pytest.mark.parametrize("rules", [None, []])
@pytest.mark.parametrize("requests", [None, []])
def test_explicit_empty_device_evidence_starts_once(monkeypatch, devices, rules, requests):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"].update(Devices=devices, DeviceCgroupRules=rules, DeviceRequests=requests)
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
    assert launcher.launch(CONTAINER, IMAGE, approved_config(value)) == 7
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect", "diff", "start"]


@pytest.mark.parametrize("field", ["Devices", "DeviceCgroupRules", "DeviceRequests"])
def test_device_evidence_drift_between_checks_never_starts(monkeypatch, capsys, field):
    launcher = load_launcher()
    value = candidate()
    approval = approved_config(value)
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            seen = copy.deepcopy(value)
            if len(calls) == 3:
                seen["HostConfig"][field] = ["unapproved"]
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        pytest.fail("changed device evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approval]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("ipc_mode", ["host", "container:" + "c" * 64])
def test_shared_ipc_namespace_refuses_even_with_matching_approval(monkeypatch, capsys, ipc_mode):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["IpcMode"] = ipc_mode
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        return 0

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container private IPC namespace is required\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("ipc_mode", [
    "missing", None, [], {}, False, 0, "", "none", "shareable", "PRIVATE",
])
def test_missing_or_malformed_ipc_evidence_is_not_private(monkeypatch, capsys, ipc_mode):
    launcher = load_launcher()
    value = candidate()
    if ipc_mode == "missing":
        del value["HostConfig"]["IpcMode"]
    else:
        value["HostConfig"]["IpcMode"] = ipc_mode
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("invalid IPC namespace evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container private IPC namespace is required\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("ipc_mode", ["host", "container:" + "c" * 64])
def test_ipc_namespace_drift_between_checks_never_starts(monkeypatch, capsys, ipc_mode):
    launcher = load_launcher()
    value = candidate()
    approval = approved_config(value)
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            seen = copy.deepcopy(value)
            if len(calls) == 3:
                seen["HostConfig"]["IpcMode"] = ipc_mode
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        pytest.fail("changed IPC namespace reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approval]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("pid_mode", ["host", "container:" + "c" * 64])
def test_shared_pid_namespace_refuses_even_with_matching_approval(monkeypatch, capsys, pid_mode):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["PidMode"] = pid_mode
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        return 0

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container private PID namespace is required\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("pid_mode", ["missing", None, [], {}, False, 0, "private"])
def test_missing_or_malformed_pid_evidence_is_not_private(monkeypatch, capsys, pid_mode):
    launcher = load_launcher()
    value = candidate()
    if pid_mode == "missing":
        del value["HostConfig"]["PidMode"]
    else:
        value["HostConfig"]["PidMode"] = pid_mode
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("invalid PID namespace evidence reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container private PID namespace is required\n"
    )
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("pid_mode", ["host", "container:" + "c" * 64])
def test_pid_namespace_drift_between_checks_never_starts(monkeypatch, capsys, pid_mode):
    launcher = load_launcher()
    value = candidate()
    approval = approved_config(value)
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            seen = copy.deepcopy(value)
            if len(calls) == 3:
                seen["HostConfig"]["PidMode"] = pid_mode
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        pytest.fail("changed PID namespace reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approval]) == 1
    assert capsys.readouterr().err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args in calls] == ["inspect", "diff", "inspect"]


@pytest.mark.parametrize("policy", [
    {"Name": "always", "MaximumRetryCount": 0},
    {"Name": "unless-stopped", "MaximumRetryCount": 0},
    {"Name": "on-failure", "MaximumRetryCount": 3},
])
def test_daemon_restart_bypass_refuses_even_with_matching_approval(monkeypatch, policy):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["RestartPolicy"] = policy
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        return 0

    monkeypatch.setattr(launcher, "_engine", engine)
    with pytest.raises(launcher.LaunchError, match="restart"):
        launcher.launch(CONTAINER, IMAGE, approved_config(value))
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("policy", [
    "missing", None, [], "no", {},
    {"Name": "", "MaximumRetryCount": 0},
    {"Name": "no"}, {"MaximumRetryCount": 0},
    {"Name": "no", "MaximumRetryCount": False},
    {"Name": "no", "MaximumRetryCount": 0.0},
    {"Name": "no", "MaximumRetryCount": "0"},
    {"Name": "no", "MaximumRetryCount": -1},
    {"Name": "no", "MaximumRetryCount": 1},
])
def test_missing_or_malformed_restart_evidence_is_not_disabled(monkeypatch, policy):
    launcher = load_launcher()
    value = candidate()
    if policy == "missing":
        del value["HostConfig"]["RestartPolicy"]
    else:
        value["HostConfig"]["RestartPolicy"] = policy
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        assert args[0] == "inspect", "invalid restart evidence reached later action"
        return json.dumps([value])

    monkeypatch.setattr(launcher, "_engine", engine)
    with pytest.raises(launcher.LaunchError, match="restart"):
        launcher.launch(CONTAINER, IMAGE, approved_config(value))
    assert len(calls) == 1


@pytest.mark.parametrize("host", [None, [], "private-token", 0, False])
def test_nonobject_host_policy_is_sanitized_before_later_action(monkeypatch, capsys, host):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"] = host
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        if args[0] == "inspect":
            return json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("invalid host policy reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    # An independently matching digest is not proof of valid evidence shape.
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    error = capsys.readouterr().err
    assert error == "custody launcher refused: local container evidence is invalid\n"
    assert "private-token" not in error
    assert [args[0] for args in calls] == ["inspect"]


@pytest.mark.parametrize("drift", ["config", "state", "layer", "restart"])
def test_changed_evidence_between_checks_never_starts(monkeypatch, drift):
    launcher = load_launcher()
    value = candidate()
    calls = []

    def engine(args, *, attach=False):
        calls.append(args)
        assert args[0] != "start"
        if args[0] == "inspect":
            seen = copy.deepcopy(value)
            if sum(call[0] == "inspect" for call in calls) == 2:
                if drift == "config":
                    seen["Config"]["Env"].append("PYTHONPATH=/var/lib/swapservice")
                elif drift == "state":
                    seen["State"] = {"Status": "running", "Running": True}
                elif drift == "restart":
                    seen["HostConfig"]["RestartPolicy"]["Name"] = "always"
            return json.dumps([seen])
        return "A /opt/swapService/evil.py\n" if drift == "layer" and len(calls) == 4 else ""

    monkeypatch.setattr(launcher, "_engine", engine)
    with pytest.raises(launcher.LaunchError):
        launcher.launch(CONTAINER, IMAGE, approved_config(value))


@pytest.mark.parametrize("drift", ["network", "security_label"])
@pytest.mark.parametrize("between_checks", [False, True])
def test_network_and_security_drift_is_independently_pinned(monkeypatch, drift, between_checks):
    launcher = load_launcher()
    value = candidate()
    approval = approved_config(value)
    inspected = 0

    def engine(args, *, attach=False):
        nonlocal inspected
        assert args[0] != "start"
        if args[0] == "diff":
            return ""
        inspected += 1
        changed = copy.deepcopy(value)
        if not between_checks or inspected == 2:
            if drift == "network":
                changed["NetworkSettings"]["Networks"]["unapproved"] = {"Aliases": ["rpc"]}
            else:
                changed["AppArmorProfile"] = "unconfined"
        return json.dumps([changed])

    monkeypatch.setattr(launcher, "_engine", engine)
    with pytest.raises(launcher.LaunchError):
        launcher.launch(CONTAINER, IMAGE, approval)


@pytest.mark.parametrize("bad_options", [None, {}, {"ReadOnlyNonRecursive": True},
                                        {"NonRecursive": True, "Propagation": "shared"}])
def test_readonly_secrets_requires_nonrecursive_private_bind(monkeypatch, bad_options):
    launcher = load_launcher()
    value = candidate()
    value["HostConfig"]["Mounts"][1]["BindOptions"] = bad_options
    monkeypatch.setattr(launcher, "_engine", lambda args, **kwargs:
                        json.dumps([value]) if args[0] == "inspect" else "")
    with pytest.raises(launcher.LaunchError):
        launcher.launch(CONTAINER, IMAGE, approved_config(value))


@pytest.mark.parametrize("payload", [
    "null", "{}", "[]", "[{}, {}]", "[null]", '[{"Id": "wrong"}]',
    '[{"Id": "' + CONTAINER + '", "Id": "' + CONTAINER + '"}]',
])
def test_malformed_or_duplicate_inspection_is_sanitized(monkeypatch, payload):
    launcher = load_launcher()

    def engine(args, *, attach=False):
        assert args[0] == "inspect"
        return payload

    monkeypatch.setattr(launcher, "_engine", engine)
    with pytest.raises(launcher.LaunchError, match="invalid"):
        launcher.launch(CONTAINER, IMAGE, approved_config(candidate()))


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("inspection", [1, 2])
def test_non_json_numeric_constants_refuse_before_execution(monkeypatch, capsys, constant, inspection):
    launcher = load_launcher()
    value = candidate()
    calls = []
    inspected = 0
    # State is checked separately, not included in the canonical config digest.
    # Python's default decoder accepts these invalid JSON tokens even here.
    value["State"]["private-evidence"] = {"nested": ["constant-placeholder"]}
    payload = json.dumps([value]).replace('"constant-placeholder"', constant)

    def engine(args, *, attach=False):
        nonlocal inspected
        calls.append((args, attach))
        if args[0] == "inspect":
            inspected += 1
            return payload if inspected == inspection else json.dumps([candidate()])
        if args[0] == "diff":
            return ""
        assert args == ["start", "--attach", CONTAINER] and attach
        return 7

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: local container evidence is invalid\n"
    expected = ["inspect"] if inspection == 1 else ["inspect", "diff", "inspect"]
    assert [args[0] for args, _ in calls] == expected


@pytest.mark.parametrize("text", ["NaN", "Infinity", "-Infinity"])
def test_quoted_numeric_constant_text_remains_valid_evidence(monkeypatch, text):
    launcher = load_launcher()
    value = candidate()
    value["Config"]["Env"].append("DISPLAY_LABEL=" + text)
    value["State"]["private-evidence"] = {"nested": [text]}
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
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect", "diff", "start"]


@pytest.mark.parametrize("inspection", [1, 2])
def test_excessively_nested_inspection_is_sanitized(monkeypatch, capsys, inspection):
    launcher = load_launcher()
    value = candidate()
    calls = []
    inspected = 0
    # Valid JSON below the engine's byte limit can exceed the decoder's stack.
    # Python 3.12's C decoder has a separate recursion budget from Python frames.
    # Keep raw private evidence out of both the refusal and any traceback.
    depth = 10_000
    nested = '[' * depth + '"private-token"' + ']' * depth
    payload = json.dumps([value])[:-2] + ', "deep": ' + nested + '}]'
    assert len(payload.encode("utf-8")) < 1024 * 1024

    def engine(args, *, attach=False):
        nonlocal inspected
        calls.append(args)
        if args[0] == "inspect":
            inspected += 1
            return payload if inspected == inspection else json.dumps([value])
        if args[0] == "diff":
            return ""
        pytest.fail("excessively nested inspection reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    assert capsys.readouterr().err == "custody launcher refused: local container evidence is invalid\n"
    expected = ["inspect"] if inspection == 1 else ["inspect", "diff", "inspect"]
    assert [args[0] for args in calls] == expected


def test_duplicate_valid_inspection_refuses_before_execution(monkeypatch):
    launcher = load_launcher()
    value = candidate()
    payload = json.dumps([value]).replace('"Image":', '"Image": "' + IMAGE + '", "Image":', 1)

    def engine(args, *, attach=False):
        if args[0] == "inspect":
            return payload
        if args[0] == "diff":
            return ""
        pytest.fail("duplicate inspection reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    with pytest.raises(launcher.LaunchError, match="invalid"):
        launcher.launch(CONTAINER, IMAGE, approved_config(value))


@pytest.mark.parametrize("which,bad_pin", [
    (0, "service"), (0, CONTAINER.upper()), (0, CONTAINER + "\n"),
    (1, "service:latest"), (1, "sha256:" + "A" * 64), (1, "sha256:" + "a" * 63),
    (2, ""), (2, "3" * 64 + "\n"),
])
def test_invalid_pins_refuse_before_engine_access(monkeypatch, which, bad_pin):
    launcher = load_launcher()
    pins = [CONTAINER, IMAGE, approved_config(candidate())]
    pins[which] = bad_pin
    monkeypatch.setattr(launcher, "_engine", lambda *args, **kwargs: pytest.fail("engine accessed"))
    with pytest.raises(launcher.LaunchError, match="pins"):
        launcher.launch(*pins)


def test_engine_uses_fixed_binary_and_clean_local_environment(monkeypatch):
    import subprocess
    import sys

    launcher = load_launcher()
    real_popen = subprocess.Popen
    monkeypatch.setenv("DOCKER_HOST", "tcp://unapproved.example:2375")
    monkeypatch.setenv("DOCKER_CONTEXT", "unapproved")
    monkeypatch.setenv("PYTHONPATH", "/mutable")
    monkeypatch.setenv("LD_PRELOAD", "/mutable/interceptor.so")

    def popen(command, **kwargs):
        assert command == ["/usr/bin/docker", "inspect", "--type=container", CONTAINER]
        assert kwargs == {"env": {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
                          "stdin": launcher.subprocess.DEVNULL,
                          "stdout": launcher.subprocess.PIPE,
                          "stderr": launcher.subprocess.DEVNULL, "bufsize": 0}
        return real_popen([sys.executable, "-I", "-c", "print('[]', end='')"], **kwargs)

    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    assert launcher._engine(["inspect", "--type=container", CONTAINER]) == "[]"


@pytest.mark.parametrize("failure", ["timeout", "missing_binary", "nonzero", "oversized"])
def test_engine_failures_do_not_disclose_evidence_or_credentials(monkeypatch, capsys, failure):
    import subprocess
    import sys

    launcher = load_launcher()
    real_popen = subprocess.Popen

    def popen(command, **kwargs):
        if failure == "timeout":
            raise launcher.subprocess.TimeoutExpired(command, 15, output="private-token")
        if failure == "missing_binary":
            raise FileNotFoundError("private-token")
        source = "import sys; sys.stderr.write('private-token'); "
        source += "sys.exit(1)" if failure == "nonzero" else (
            "sys.stdout.buffer.write(b'x' * (1024 * 1024 + 1))"
        )
        return real_popen([sys.executable, "-I", "-c", source], **kwargs)

    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(candidate())]) == 1
    assert "private-token" not in capsys.readouterr().err


@pytest.mark.parametrize("unit,count", [(b"x", 1024 * 1024 + 1), (b"\xc3\xa9", 512 * 1024 + 1)])
def test_engine_limits_evidence_bytes_from_real_child(monkeypatch, unit, count):
    import subprocess
    import sys

    launcher = load_launcher()
    real_popen = subprocess.Popen

    def child(command, **kwargs):
        # Exercise actual pipe reads/decoding without needing Docker permission.
        return real_popen([sys.executable, "-I", "-c",
                           "import sys; sys.stdout.buffer.write(" + repr(unit)
                           + " * " + str(count) + ")"], **kwargs)

    monkeypatch.setattr(launcher.subprocess, "Popen", child)
    with pytest.raises(launcher.LaunchError, match="evidence is unavailable"):
        launcher._engine(["inspect", "--type=container", CONTAINER])


def test_engine_kills_and_reaps_overflowing_evidence_child(monkeypatch):
    import subprocess
    import sys

    launcher = load_launcher()
    real_popen = subprocess.Popen
    children = []

    def child(command, **kwargs):
        process = real_popen([sys.executable, "-I", "-c",
                              "import sys,time; sys.stdout.buffer.write(b'x' * (1024*1024+1)); "
                              "sys.stdout.buffer.flush(); time.sleep(0.2)"], **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(launcher.subprocess, "Popen", child)
    with pytest.raises(launcher.LaunchError, match="evidence is unavailable"):
        launcher._engine(["inspect", "--type=container", CONTAINER])
    assert len(children) == 1
    assert children[0].poll() is not None and children[0].returncode < 0
    assert children[0].stdout.closed


@pytest.mark.parametrize("unit,count", [(b"", 0), (b"x", 1024 * 1024),
                                         (b"\xc3\xa9", 512 * 1024)])
def test_engine_accepts_evidence_at_byte_boundary(monkeypatch, unit, count):
    import subprocess
    import sys

    launcher = load_launcher()
    real_popen = subprocess.Popen

    def child(command, **kwargs):
        source = "import sys; sys.stdout.buffer.write(" + repr(unit) + " * " + str(count) + ")"
        return real_popen([sys.executable, "-I", "-c", source], **kwargs)

    monkeypatch.setattr(launcher.subprocess, "Popen", child)
    assert launcher._engine(["diff", CONTAINER]) == (unit * count).decode("utf-8")


@pytest.mark.parametrize("behavior", ["idle", "trickle", "closed_stdout"])
def test_engine_deadline_kills_and_reaps_child(monkeypatch, capsys, behavior):
    import subprocess
    import sys

    launcher = load_launcher()
    real_popen = subprocess.Popen
    children = []
    commands = []
    monkeypatch.setattr(launcher, "_EVIDENCE_TIMEOUT", 0.2)

    def child(command, **kwargs):
        commands.append(command)
        source = "import os,sys,time; "
        if behavior == "trickle":
            source += "exec('while True:\\n sys.stdout.write(\"x\"); sys.stdout.flush(); time.sleep(0.01)')"
        elif behavior == "closed_stdout":
            source += "os.close(1); time.sleep(10)"
        else:
            source += "time.sleep(10)"
        process = real_popen([sys.executable, "-I", "-c", source], **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(launcher.subprocess, "Popen", child)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(candidate())]) == 1
    assert capsys.readouterr().err == "custody launcher refused: local container authority is unavailable\n"
    assert commands == [["/usr/bin/docker", "inspect", "--type=container", CONTAINER]]
    assert children[0].poll() is not None and children[0].returncode < 0
    assert children[0].stdout.closed


@pytest.mark.parametrize("behavior", ["stderr_flood", "invalid_utf8"])
def test_engine_does_not_capture_stderr_or_leak_invalid_bytes(monkeypatch, capsys, behavior):
    import subprocess
    import sys

    launcher = load_launcher()
    real_popen = subprocess.Popen
    children = []

    def child(command, **kwargs):
        source = "import sys; "
        if behavior == "stderr_flood":
            source += "sys.stderr.buffer.write(b'private-token' * 1000000); sys.stdout.write('[]')"
        else:
            source += "sys.stdout.buffer.write(b'private-token\\xff')"
        process = real_popen([sys.executable, "-I", "-c", source], **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(launcher.subprocess, "Popen", child)
    if behavior == "stderr_flood":
        assert launcher._engine(["inspect", "--type=container", CONTAINER]) == "[]"
    else:
        assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                              "--approved-config", approved_config(candidate())]) == 1
    output = capsys.readouterr()
    assert "private-token" not in output.out + output.err
    assert children[0].poll() is not None
    assert children[0].stdout.closed


def test_attached_service_output_is_not_captured_or_time_limited(monkeypatch):
    launcher = load_launcher()

    def run(command, **kwargs):
        assert command == ["/usr/bin/docker", "start", "--attach", CONTAINER]
        assert kwargs == {"env": {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
                          "stdin": launcher.subprocess.DEVNULL, "capture_output": False,
                          "text": True, "timeout": None, "check": False}
        return launcher.subprocess.CompletedProcess(command, 7)

    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher._engine(["start", "--attach", CONTAINER], attach=True) == 7


def test_external_cli_does_not_import_mutable_repository_before_refusal(tmp_path):
    import subprocess
    import sys

    marker = tmp_path / "pre-import-side-effect"
    tmp_path.joinpath("sitecustomize.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--container", "not-a-pin",
         "--approved-image", IMAGE, "--approved-config", approved_config(candidate())],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "canonical independent approval pins" in result.stderr
    assert not marker.exists()


@pytest.mark.parametrize("mode", ["host", "private", "missing", None, False, 0, 0.0, [], {}])
def test_nonprivate_uts_namespace_refuses_matching_approval(monkeypatch, capsys, mode):
    launcher = load_launcher()
    value = candidate()
    value["Config"]["Hostname"] = "approved-service-hostname"
    if mode == "missing":
        del value["HostConfig"]["UTSMode"]
    else:
        value["HostConfig"]["UTSMode"] = mode
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
    # A matching digest cannot authorize ignoring the approved hostname and
    # inheriting mutable host UTS state outside the image/configuration pins.
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "custody launcher refused: container private UTS namespace is required\n"
    assert [args[0] for args, _ in calls] == ["inspect"]


@pytest.mark.parametrize("mode", ["host", "missing", None])
def test_uts_namespace_drift_between_checks_refuses(monkeypatch, capsys, mode):
    launcher = load_launcher()
    value = candidate()
    calls = []

    def engine(args, *, attach=False):
        calls.append((args, attach))
        if args[0] == "inspect":
            seen = copy.deepcopy(value)
            if len(calls) == 3:
                if mode == "missing":
                    del seen["HostConfig"]["UTSMode"]
                else:
                    seen["HostConfig"]["UTSMode"] = mode
            return json.dumps([seen])
        if args[0] == "diff":
            return ""
        pytest.fail("changed UTS namespace reached execution")

    monkeypatch.setattr(launcher, "_engine", engine)
    assert launcher.main(["--container", CONTAINER, "--approved-image", IMAGE,
                          "--approved-config", approved_config(value)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "custody launcher refused: container configuration does not match independent approval\n"
    )
    assert [args[0] for args, _ in calls] == ["inspect", "diff", "inspect"]


def test_private_uts_namespace_preserves_pinned_hostname_and_exact_start(monkeypatch, capsys):
    launcher = load_launcher()
    value = candidate()
    assert value["HostConfig"]["UTSMode"] == ""
    value["Config"]["Hostname"] = "approved-service-hostname"
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
