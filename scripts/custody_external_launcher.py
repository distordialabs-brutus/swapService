#!/usr/bin/env python3
"""External admission for an independently approved local Docker container image.

Install this script and its interpreter outside the service image under independent
administration. Never import swapService code here. The Docker daemon/image store,
launcher, interpreter and host are trusted; this is not their self-attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import selectors
import subprocess
import sys
import time
from typing import Literal, overload


class LaunchError(Exception):
    """Public refusal without engine output, credentials or inspected configuration."""


_REQUIRED_SYSTEM_PATHS = {
    "MaskedPaths": frozenset({
        "/proc/acpi", "/proc/asound", "/proc/interrupts", "/proc/kcore",
        "/proc/keys", "/proc/latency_stats", "/proc/sched_debug", "/proc/scsi",
        "/proc/timer_list", "/proc/timer_stats", "/sys/devices/virtual/powercap",
        "/sys/firmware",
    }),
    "ReadonlyPaths": frozenset({
        "/proc/bus", "/proc/fs", "/proc/irq", "/proc/sys", "/proc/sysrq-trigger",
    }),
}


@overload
def _engine(args: list[str], *, attach: Literal[False] = False) -> str: ...


@overload
def _engine(args: list[str], *, attach: Literal[True]) -> int: ...


_EVIDENCE_LIMIT = 1024 * 1024
_EVIDENCE_TIMEOUT = 15


def _engine(args: list[str], *, attach: bool = False) -> str | int:
    command = ["/usr/bin/docker", *args]
    environment = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"}
    try:
        if attach:
            # Service output remains live and is not evidence to buffer or limit.
            return subprocess.run(
                command, env=environment, stdin=subprocess.DEVNULL,
                capture_output=False, text=True, timeout=None, check=False,
            ).returncode
        deadline = time.monotonic() + _EVIDENCE_TIMEOUT
        with subprocess.Popen(
            command, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
        ) as process:
            try:
                assert process.stdout is not None  # Guaranteed by stdout=PIPE.
                evidence = bytearray()
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise subprocess.TimeoutExpired(command, _EVIDENCE_TIMEOUT)
                        # Read at most the limit plus one sentinel byte. Never
                        # capture unbounded stdout/stderr before checking size.
                        chunk = os.read(process.stdout.fileno(),
                                        min(65536, _EVIDENCE_LIMIT - len(evidence) + 1))
                        if not chunk:
                            break
                        evidence.extend(chunk)
                        if len(evidence) > _EVIDENCE_LIMIT:
                            raise LaunchError("local container evidence is unavailable")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, _EVIDENCE_TIMEOUT)
                if process.wait(timeout=remaining) != 0:
                    raise LaunchError("local container evidence is unavailable")
                return evidence.decode("utf-8")
            finally:
                # Refusal must leave neither a blocked pipe writer nor a zombie.
                if process.poll() is None:
                    process.kill()
                process.wait()
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise LaunchError("local container authority is unavailable") from exc


def _finite_json_float(value: str) -> float:
    # Standard JSON exponents can overflow Python's float decoder even when
    # parse_constant rejects NaN/Infinity. Check every numeric token, including
    # fields outside the approval projection, without exposing private evidence.
    result = float(value)
    if not math.isfinite(result):
        raise ValueError
    return result


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError
        result[name] = value
    return result


def _reject_json_constant(value: str):
    # Python otherwise accepts NaN/Infinity, including outside the pinned fields.
    # Reject during parsing, without disclosing the inspection's private values.
    raise ValueError


def launch(container_id: str, image_id: str, config_sha256: str) -> int:
    if (re.fullmatch(r"[0-9a-f]{64}", container_id) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
            or re.fullmatch(r"[0-9a-f]{64}", config_sha256) is None):
        raise LaunchError("canonical independent approval pins are required")
    for _ in range(2):
        try:
            rows = json.loads(_engine(["inspect", "--type=container", container_id]),
                              object_pairs_hook=_unique_object, parse_float=_finite_json_float,
                              parse_constant=_reject_json_constant)
            if not isinstance(rows, list) or len(rows) != 1 or rows[0]["Id"] != container_id:
                raise ValueError
            value = rows[0]
            if value["Image"] != image_id:
                raise LaunchError("container image does not match independent approval")
            selected = {key: value[key] for key in (
                "Image", "Path", "Args", "Config", "HostConfig", "Mounts", "NetworkSettings",
                "Platform", "AppArmorProfile", "ProcessLabel", "MountLabel",
            )}
            raw = json.dumps(selected, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("ascii")
            if hashlib.sha256(raw).hexdigest() != config_sha256:
                raise LaunchError("container configuration does not match independent approval")
            # A matching digest records the candidate's choice; it cannot
            # authorize unconfined or unreviewed custom AppArmor policy. This
            # checks the reported name, not the protected host's profile bytes.
            if value["AppArmorProfile"] != "docker-default":
                raise LaunchError("container supported AppArmor profile is required")
            config = value["Config"]
            if not isinstance(config, dict):
                raise ValueError
            # Pin numeric primary IDs instead of resolving image account names
            # or defaulting to root. Restrict the supported range before int()
            # conversion; matching approval cannot exempt a root identity.
            runtime_user = config.get("User")
            if (not isinstance(runtime_user, str)
                    or re.fullmatch(r"[1-9][0-9]{0,9}:[1-9][0-9]{0,9}", runtime_user) is None
                    or any(int(part) > 2147483647 for part in runtime_user.split(":"))):
                raise LaunchError("container non-root numeric runtime identity is required")
            # The daemon schedules healthcheck execs independently of this one
            # admitted entrypoint. A pinned probe is still an automatic extra
            # command, potentially concurrent with custody admission/recovery.
            healthcheck = config.get("Healthcheck")
            if healthcheck is not None and (
                    not isinstance(healthcheck, dict)
                    or healthcheck.get("Test") != ["NONE"]):
                raise LaunchError("container automatic healthcheck is not disabled")
            host = value["HostConfig"]
            if not isinstance(host, dict):
                raise ValueError
            # Primary UID:GID does not exclude candidate-requested supplementary
            # grants. Do not resolve or approve additional group names/IDs here.
            if "GroupAdd" not in host or host["GroupAdd"] not in (None, []):
                raise LaunchError("container supplementary group additions are not disabled")
            # A candidate must not disable a protected daemon's UID/GID remapping.
            # Empty mode retains daemon policy; it does not prove remapping is on.
            if host.get("UsernsMode") != "":
                raise LaunchError("container user namespace opt-out is not disabled")
            # Preserve the exact admitted container's inspection/layer evidence
            # after exit or startup failure; daemon cleanup bypasses this guard.
            if host.get("AutoRemove") is not False:
                raise LaunchError("container automatic removal is not disabled")
            # This option clears the cgroup mount's read-only flag during OCI
            # construction, independently of ReadonlyRootfs and capabilities.
            # Reject every enabling/ambiguous occurrence, not merely the last.
            security_options = host.get("SecurityOpt")
            if isinstance(security_options, list) and any(
                    isinstance(option, str)
                    and option.partition("=" if "=" in option else ":")[0] == "writable-cgroups"
                    and option != "writable-cgroups=false" for option in security_options):
                raise LaunchError("container writable cgroups are not disabled")
            # Docker substitutes host-gateway from daemon configuration at start;
            # pinning the token does not pin the resulting /etc/hosts addresses.
            extra_hosts = host.get("ExtraHosts")
            if extra_hosts is not None and (
                    not isinstance(extra_hosts, list)
                    or not all(isinstance(entry, str) for entry in extra_hosts)
                    or any(entry.partition(":")[2] == "host-gateway" for entry in extra_hosts)):
                raise LaunchError("container extra-host gateway indirection is not disabled")
            # OCI annotations can configure the trusted runtime (for example,
            # runc's host systemd scope), not merely label the approved image.
            annotations = host.get("Annotations")
            if annotations is not None and (not isinstance(annotations, dict) or annotations):
                raise LaunchError("container runtime annotations are not disabled")
            # Read-only layers and CapDrop do not prohibit setuid/setgid exec.
            # Do not infer the effective setting from a mutable daemon default.
            security = host.get("SecurityOpt")
            enabled = {"no-new-privileges", "no-new-privileges=true"}
            if (not isinstance(security, list)
                    or not all(isinstance(option, str) for option in security)
                    or not any(option in enabled for option in security)
                    or any(option.partition("=" if "=" in option else ":")[0] == "no-new-privileges"
                           and option not in enabled for option in security)):
                raise LaunchError("container no-new-privileges policy is required")
            # Explicit empty lists disable Docker's /proc and /sys protections;
            # read-only root and diff do not cover these runtime filesystems.
            # Require the selected Moby baseline, not implicit daemon defaults.
            for field, required in _REQUIRED_SYSTEM_PATHS.items():
                paths = host.get(field)
                if (not isinstance(paths, list)
                        or not all(isinstance(path, str) for path in paths)
                        or not required.issubset(paths)):
                    raise LaunchError("container system path protections are required")
            # Alternate OCI runtimes can inject host libraries or hooks outside
            # the approved image/binds. The protected daemon's runc installation
            # and configuration remain trusted external prerequisites.
            if host.get("Runtime") != "runc":
                raise LaunchError("container conventional runtime is required")
            # Null/absent Init can inherit the daemon's default. An init enabled
            # explicitly or by default injects a daemon-supplied executable that
            # is not covered by the approved service image.
            if host.get("Init") is not False:
                raise LaunchError("container daemon-supplied init is not disabled")
            # A host cgroup namespace exposes cross-container/host topology
            # outside the approved image. Empty/absent evidence can inherit a
            # daemon default; require explicit private namespace admission.
            if host.get("CgroupnsMode") != "private":
                raise LaunchError("container private cgroup namespace is required")
            # Host UTS sharing ignores the approved Config.Hostname and reads
            # mutable host identity instead. Docker reports private UTS as "".
            if host.get("UTSMode") != "":
                raise LaunchError("container private UTS namespace is required")
            # Host networking shares the daemon host's network namespace and
            # local services; a configuration pin cannot authorize that access.
            # Other network modes still need independently enforced endpoint policy.
            if host.get("NetworkMode") == "host":
                raise LaunchError("container host networking is not permitted")
            # Candidate seccomp options override the protected daemon policy;
            # even "builtin" can replace its custom profile. Match Moby's key
            # parsing (equals takes precedence over the deprecated colon form).
            seccomp_options = host.get("SecurityOpt")
            if (not isinstance(seccomp_options, list)
                    or not all(isinstance(option, str) for option in seccomp_options)
                    or any(option.partition("=" if "=" in option else ":")[0] == "seccomp"
                           for option in seccomp_options)):
                raise LaunchError("container seccomp override is not permitted")
            # Shared PID namespaces can expose another process's filesystem via
            # /proc/<pid>/root, outside this image's mount/layer approval.
            # Docker reports the default private namespace as an empty string.
            if host.get("PidMode") != "":
                raise LaunchError("container private PID namespace is required")
            # Host/container IPC sharing adds externally writable /dev/shm
            # contents not covered by the approved image or explicit bind list.
            if host.get("IpcMode") != "private":
                raise LaunchError("container private IPC namespace is required")
            # Host devices and device-driver requests expose authority outside
            # the approved image/bind list, even with a read-only root.
            for field in ("Devices", "DeviceCgroupRules", "DeviceRequests"):
                if field not in host or host[field] not in (None, []):
                    raise LaunchError("container host-device access is not disabled")
            # Container networking reuses the donor's hostname/hosts/resolver
            # files at startup. Its name/ID does not pin those mutable bytes,
            # which are outside the approved image and explicit bind projection.
            network_mode = host.get("NetworkMode")
            if (not isinstance(network_mode, str) or not network_mode
                    or network_mode.startswith("container:")):
                raise LaunchError("container network file sharing is not disabled")
            # Legacy links can add environment values from a different container
            # during OCI construction. Pinning the link name does not pin those
            # late-bound values; Config.Env is not the complete startup environment.
            if "Links" not in host or host["Links"] not in (None, []):
                raise LaunchError("container legacy links are not disabled")
            restart = host.get("RestartPolicy")
            if (not isinstance(restart, dict)
                    or restart.get("Name") != "no"
                    or type(restart.get("MaximumRetryCount")) is not int
                    or restart["MaximumRetryCount"] != 0):
                # A daemon restart would skip admission and reuse a previously
                # executed container rather than a pristine created candidate.
                raise LaunchError("container automatic restart policy is not disabled")
            # Docker can retain status=created after failed OCI startup, after
            # setup or runtime code already ran. Do not authorize another attempt
            # or disclose the daemon's potentially private failure details.
            state = value["State"]
            if not isinstance(state, dict) or state.get("Error") != "":
                raise LaunchError("container prior startup failure is not excluded")
            # Status and an empty error cannot erase positive prior-start
            # evidence. Require Docker's canonical Go zero-time observation;
            # missing/malformed timestamps are unknown, not never-started.
            if state.get("StartedAt") != "0001-01-01T00:00:00Z":
                raise LaunchError("container prior execution is not excluded")
            if (value["State"]["Status"] != "created"
                    or value["State"]["Running"] is not False
                    or host["ReadonlyRootfs"] is not True
                    or host["Privileged"] is not False
                    or host["CapDrop"] != ["ALL"] or host["CapAdd"] not in (None, [])
                    or host.get("Tmpfs") not in (None, {})):
                raise LaunchError("container is not a new read-only-root execution candidate")
            declared = host.get("Mounts")
            if not isinstance(declared, list) or host.get("Binds") not in (None, []):
                raise LaunchError("explicit nonrecursive bind mounts are required")
            destinations = set()
            if not isinstance(value["Mounts"], list) or len(declared) != len(value["Mounts"]):
                raise ValueError
            for mount in value["Mounts"]:
                destination = mount["Destination"]
                if (mount["Type"] != "bind" or destination in destinations
                        or not isinstance(mount["Source"], str)
                        or not mount["Source"].startswith("/")
                        # Never expose the daemon host root. Require lexical
                        # canonicality instead of normalizing a path whose host
                        # symlinks/filesystem this process cannot safely resolve.
                        or "\x00" in mount["Source"]
                        or any(part in {"", ".", ".."}
                               for part in mount["Source"].split("/")[1:])
                        or destination not in {"/var/lib/swapservice", "/run/swapservice-secrets"}
                        or type(mount["RW"]) is not bool
                        or (destination == "/run/swapservice-secrets" and mount["RW"])):
                    raise LaunchError("container has an unsupported mutable mount")
                declarations = [item for item in declared if item["Target"] == destination]
                if len(declarations) != 1:
                    raise ValueError
                specification = declarations[0]
                options = specification.get("BindOptions")
                if (specification["Type"] != "bind"
                        or specification["Source"] != mount["Source"]
                        or type(specification["ReadOnly"]) is not bool
                        or specification["ReadOnly"] is mount["RW"]
                        or not isinstance(options, dict)
                        or options.get("NonRecursive") is not True
                        or options.get("Propagation") != "rprivate"
                        or (options.get("ReadOnlyNonRecursive") is not None
                            and options["ReadOnlyNonRecursive"] is not False)
                        or mount.get("Propagation", "rprivate") != "rprivate"):
                    raise LaunchError("container bind mount policy is inconsistent")
                destinations.add(destination)
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            # A byte-bounded JSON response can still exhaust decoder/encoder
            # nesting limits. Refuse without exposing raw inspection evidence.
            raise LaunchError("local container evidence is invalid") from exc
        # Even a never-started container can be changed with docker cp. Reject its
        # entire upper layer, not just a finite source/dependency inventory.
        if _engine(["diff", container_id]).strip():
            raise LaunchError("container writable layer differs from approved image")
    # No tag resolution, pull, command override, automatic restart or retry here.
    # Exclusive trusted Docker administration must span both checks and start.
    return _engine(["start", "--attach", container_id], attach=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--approved-image", required=True)
    parser.add_argument("--approved-config", required=True)
    args = parser.parse_args(argv)
    try:
        return launch(args.container, args.approved_image, args.approved_config)
    except LaunchError as exc:
        print(f"custody launcher refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
