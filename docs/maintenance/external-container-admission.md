# External container admission primitive

## Status and trust boundary

This is one narrow Batch 0 increment, **not deployment or release acceptance**. The
standalone [launcher](../../scripts/custody_external_launcher.py) imports no repository
runtime. It refuses before starting a pre-created Docker container unless an independently
approved image ID and selected execution-configuration digest match, the container is new,
its root is read-only, and its writable upper layer is pristine. All existing witness,
restore, financial, service-identity and live-chain gates remain mandatory.

The launcher does not attest itself. Independently install and protect the launcher, its
Python interpreter/stdlib, `/usr/bin/docker`, local Docker daemon/image store, host/kernel
and approval arguments **outside** the mutable service artifact. Use a protected service
unit with a clean environment and Python isolated mode (`-I`); running this script from an
operator-writable checkout does not establish independent authority. Runtime credentials
and repository code must not be able to change the launcher, pins or Docker configuration.
No image, container or approval is created by this tool.

Exclusive trusted Docker administration must span inspection through start: Docker does not
provide an atomic inspect/diff/start compare-and-swap. Another Docker administrator can
bypass the tool or change evidence after the final check. Repeated inspections contain
observable drift; they do not eliminate this trust assumption. Independently protected
image storage and host integrity, not a Docker-reported ID alone, establish byte authority.

## Exact approval contract

The independent approver supplies:

- `--container`: full 64-character lowercase hexadecimal local container ID;
- `--approved-image`: `sha256:` followed by the full 64-character lowercase hexadecimal
  Docker image configuration ID, **not** a tag, short ID or registry manifest digest;
- `--approved-config`: SHA-256 of the ASCII canonical JSON projection of one Docker
  container-inspect object containing exactly these top-level fields:

```text
Image, Path, Args, Config, HostConfig, Mounts, NetworkSettings,
Platform, AppArmorProfile, ProcessLabel, MountLabel
```

Canonical encoding uses `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=True`
and no NaN/infinity values; array order is preserved. The projection deliberately omits
volatile status, timestamps and the container ID; the supplied exact container ID is
checked separately, and both observations must have status `created` and `Running=false`.
Network endpoints/aliases/ports and the entire selected security/host/configuration objects
are pinned, not inferred from a network label. A changed candidate needs independent review,
not automatic approval of its new digest. The launcher has no digest-export/approve mode.

`Config.Env` may contain credentials. Compute/review this projection in the protected
approval domain; do not publish raw inspect JSON or pass credentials as command-line
arguments. The launcher never prints inspected evidence or Docker inspection errors.
After approval it attaches to the service's normal output, whose existing secret-safe
logging obligations remain separate.

## Automatic healthcheck restriction

Both inspections require object-shaped `Config` evidence and `Config.Healthcheck`
to be absent, JSON null or an object whose `Test` is exactly `["NONE"]`. Enabled
`CMD`/`CMD-SHELL` probes, malformed values and ambiguous empty/default test objects
refuse even with matching independent approval. Prepare images/containers without
healthchecks or explicitly disable an inherited image probe with `--no-healthcheck`.
The daemon's merged container `Config`, not just the image recipe, is inspected;
the full configuration remains part of the existing approval digest.

[Moby's health monitor](https://github.com/moby/moby/blob/d74daf1a/daemon/health.go)
schedules probes and uses `ContainerExecStart` to run their commands independently
of the guarded entrypoint. A pinned healthcheck command is still a second automatic
execution path, potentially concurrent with custody startup, recovery or witness
admission. A long interval or start period is not disabled execution. Keep monitoring
outside container exec, using the separately approved read-only observability path.

This contains daemon-scheduled healthcheck commands, not administrator `docker exec`,
all runtime injection or complete executable authority. Exclusive protected daemon
administration, external image/witness binding and real Docker acceptance remain
required. The collected tests inject engine responses; no real health monitor or
claim/run/seal generation was exercised.

## Extra-host gateway restriction

Both inspections require `HostConfig.ExtraHosts` to be absent, JSON null or a
string array with no entry whose address (the portion after its first `:`) is
`host-gateway`. Matching independent approval does not exempt the restriction.
Explicit literal IPv4/IPv6 mappings and disabled forms remain supported and pinned;
a hostname literally named `host-gateway` with a literal IP is not indirection.
Malformed field shapes or non-string members refuse without exposing evidence.

[Moby's network initialization](https://github.com/moby/moby/blob/d74daf1a/daemon/container_operations.go)
replaces that special address with the daemon's `HostGatewayIPs` during startup.
Pinning `rpc.internal:host-gateway` therefore does not pin the resulting `/etc/hosts`
address: a changed daemon setting can redirect an approved hostname without changing
inspection approval or the image's writable-layer diff. Use independently approved
literal addresses instead of this daemon-resolved token.

This contains one late-bound host-address substitution, not all daemon-generated
DNS/hostname values or complete executable authority. Protected daemon administration,
endpoint identity/freshness and real Docker acceptance remain separate obligations.
Collected engine tests are offline/injected, not a real gateway-change rehearsal.

## Runtime annotation restriction

Both inspections require `HostConfig.Annotations` to be absent, JSON null or an
empty object. Nonempty objects and all other types refuse, even with independently
matching configuration approval. Absence is accepted for Docker versions that omit
this optional field; present annotations are never silently filtered or rewritten.
The exact representation remains part of the configuration digest.

Annotations are not necessarily passive metadata: [Moby passes this map into the
OCI specification](https://github.com/moby/moby/blob/d74daf1a/daemon/oci_linux.go),
and [runc identifies potentially unsafe annotation keys](https://github.com/opencontainers/runc/blob/v1.2.0/features.go),
including `bundle`, `org.criu.config` and the `org.systemd.property.` prefix.
For example, systemd properties can configure a host-created scope when the systemd
cgroup driver is used. A pinned image, read-only root and conventional runtime name
do not exclude such candidate-supplied runtime configuration. This guard rejects the
whole map rather than maintaining an incomplete runtime-specific key denylist.

This contains candidate-supplied OCI annotations only. Daemon-generated annotations,
trusted runtime/host configuration, protected deployment, complete executable closure,
external-image witness binding and real Docker acceptance remain separate obligations.
The collected tests inject inspection evidence; they do not prove a real host-systemd
change, runtime exploit or approved claim/run/seal generation.

## Writable-cgroup restriction

On both inspections, every `HostConfig.SecurityOpt` string with the key
`writable-cgroups` must be exactly `writable-cgroups=false`. Bare enabled options,
true values, contradictory duplicates and noncanonical forms (including deprecated
colon separators) refuse even with matching approval. Absence of that key preserves
existing behavior; other independently approved security options remain pinned.

[Moby's security-option parser](https://github.com/moby/moby/blob/d74daf1a/daemon/daemon_unix.go)
accepts the bare flag and boolean-valued options, in order. Its
[OCI mount construction](https://github.com/moby/moby/blob/d74daf1a/daemon/oci_linux.go)
clears the cgroup mount's read-only flag when enabled, even without a privileged
container. A read-only root, dropped capabilities and a private cgroup namespace
therefore do not exclude this explicitly requested writable runtime filesystem.

This contains candidate-requested writable cgroups, not all effective cgroup mount
policy: daemon user-namespace/rootless handling, host permissions, runtime contents,
protected deployment and real Docker enforcement remain external prerequisites.
Collected tests inject engine evidence; they do not establish a real cgroup write,
complete executable closure or an approved claim/run/seal generation.

## Automatic removal restriction

Both inspections require explicit boolean `HostConfig.AutoRemove=false`. Enabled,
missing, null and type-confused evidence refuse even with matching independent
approval. Prepare the candidate without `--rm`; approved execution must not authorize
its own evidence cleanup. The exact disabled field remains part of the approval digest.

[Moby's exit monitor](https://github.com/moby/moby/blob/d74daf1a/daemon/monitor.go)
removes containers with this policy after exit; its
[start failure cleanup](https://github.com/moby/moby/blob/d74daf1a/daemon/start.go)
also honors automatic removal. That can erase the exact container's inspection and
writable-layer evidence outside the guard, including after an unsuccessful run.
Retain the stopped candidate for independently authorized evidence collection and
cleanup instead. Retention does not authorize restarting an executed container.

This contains candidate-requested automatic evidence deletion only. It does not
provide durable evidence export or prevent trusted administrators, host failures,
log rotation or external cleanup from removing evidence. Complete executable closure,
protected deployment, external-image witness binding and real Docker acceptance
remain open. Collected tests inject engine responses; they do not exercise actual
daemon cleanup or an approved claim/run/seal generation.

## Container constraints

Prepare the candidate without starting it. The image must contain the repository,
interpreter, dependencies, standard library, bytecode/native libraries and intended
entrypoint in its read-only execution tree. Independently review its complete execution
closure and ensure neither custody nor secrets directories are import/plugin/executable
search roots or symlinks to executable locations. A pinned unsafe image is still unsafe.

The guard requires:

- object-shaped `HostConfig` evidence; null, arrays and scalar values refuse through
  the sanitized invalid-evidence boundary even if their approval digest matches;
- a never-started (`created`, not running) container with the exact approved image ID;
- `ReadonlyRootfs=true`, `Privileged=false`, `CapDrop=["ALL"]`, no added capabilities;
- explicit `HostConfig.PidMode=""`, Docker's default private PID namespace;
  host and `container:<id>` namespaces, missing evidence and malformed values refuse
  even with matching approval. Shared namespaces can expose other processes' filesystem
  roots through `/proc/<pid>/root`, outside the approved image/mount projection. A
  private namespace contains this cross-process route only; it does not attest runtime
  pseudo-filesystems or guarantee complete executable closure;
- explicit `HostConfig.RestartPolicy.Name="no"` and integer `MaximumRetryCount=0`;
  missing/malformed evidence and `always`, `unless-stopped` or `on-failure` policies
  refuse even if the configuration digest matches independent approval. Docker-managed
  restarts would reuse an executed container without repeating admission;
- no user-configured tmpfs, anonymous image volumes or legacy `HostConfig.Binds`;
- only explicit bind destinations `/var/lib/swapservice` (custody data) and
  `/run/swapservice-secrets` (read-only credentials); source paths, permissions and all
  other mount options are part of the independent config approval;
- each declared and observed bind agrees on source/target/read-only permission, with
  `BindOptions.NonRecursive=true` and explicit `Propagation=rprivate`. Nested host mounts
  are excluded; writable recursive secrets mounts and shared propagation are refused;
- empty `docker diff` on both checks, including for modifications made with `docker cp`
  before first execution.

Docker still supplies runtime pseudo-filesystems such as `/proc`, `/dev` and `/dev/shm`.
These and host-bind contents are not image bytes. No claim of complete immutable execution
or mapped-memory attestation follows from a read-only root or empty upper-layer diff.

The independently protected invocation has this shape (placeholders are intentionally
not approvals):

```bash
/protected/python3 -I /protected/custody_external_launcher.py \
  --container <FULL_CONTAINER_ID> \
  --approved-image sha256:<APPROVED_DOCKER_IMAGE_ID> \
  --approved-config <INDEPENDENT_CONFIG_SHA256>
```

The tool calls fixed `/usr/bin/docker` with an empty inherited environment except a fixed
system PATH and inert HOME, so caller-controlled Docker contexts, remote daemon URLs,
proxy configuration and loader/Python environment do not redirect the Docker child.
It inspects configuration and the upper layer twice, then starts/attaches to the exact
container ID without pulls, tag resolution, command overrides or retries. Child exit status
is preserved. It never deletes containers, clears custody holds or rewrites certificates.
Do not configure an independent automatic restart route that bypasses admission.

## Verification and remaining exits

Collected [offline tests](../../tests/test_custody_external_launcher.py) inject the trusted
Docker boundary. They verify reported image/command/configuration/network/security/layer
drift, mount constraints, private PID namespace admission, repeated checks, strict
pins/JSON, sanitized authority failures,
clean child environment and exact-ID start ordering. An actual isolated Python subprocess
verifies CLI refusal before a mutable `sitecustomize.py` can execute. These are not real
Docker file-mutation, complete service generation, witness-contention or deployment tests.

This host denies access to `/var/run/docker.sock`; no image/container was built or started.
The actual CLI consequently refuses with a sanitized authority-unavailable message.
Before accepting Batch 0, separately establish protected installation/approval ownership,
reproducible image construction and complete closure, witness binding to the external
image authority, real Docker inspect/mount/diff semantics, a clean approved
claim/run/seal generation and the full mutation/concurrency/crash matrix. Direct
`python swapService.py` remains unchanged and is not an externally attested launch path.
Production and real funds remain blocked. See [the evaluation](../EVALUATION.md) and
[the prioritized plan](../plans/2026-09-25-recovery-admission-and-capacity-fairness.md).

## Strict bind-option evidence

On both inspections, each bind's `BindOptions.ReadOnlyNonRecursive` must be
absent, JSON null or the exact boolean `false`. Numeric zero (including `0.0`
and negative floating zero), `true` and all other shapes refuse even when the
configuration approval matches. Python's equality between zero and `False`
is not evidence of a Docker boolean. Other nonrecursive/private declaration and
observed-mount checks remain mandatory; no evidence is normalized or rewritten.

The [focused bind-option tests](../../tests/test_custody_external_bind_options.py)
cover both custody and secrets mounts, malformed matching-approved evidence,
second-inspection drift and every pair of supported disabled forms with exact-ID
one-start/child-exit controls. These are injected inspection tests, not proof of
a numeric option accepted by a real Docker daemon, a mount exploit or complete
pre-execution authority. Protected deployment and actual Docker acceptance remain
separate obligations.
