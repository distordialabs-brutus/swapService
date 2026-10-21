# External container admission primitive

## Prior-start timestamp restriction

Both inspections require explicit `State.StartedAt="0001-01-01T00:00:00Z"`,
Docker's canonical Go zero-time spelling. A reported nonzero start, missing value,
wrong type or alternate zero-time spelling refuses before another diff or start,
even with matching independent approval. State is outside the approval projection,
so this is checked independently on each read; no timestamp is printed or rewritten.

[Moby v28.5.1 state handling](https://github.com/moby/moby/blob/v28.5.1/container/state.go)
records `StartedAt` on running transitions and derives created status from its zero
value. A nonzero start alongside `Status="created"` is therefore **contradictory
injected evidence**, not a demonstrated genuine Docker restart path. The launcher
previously accepted that contradiction. Exact zero-time matching deliberately
refuses unknown/noncanonical encodings rather than attempting timestamp repair.

This closes one malformed/history-evidence admission gap only. A zero timestamp
and empty error do not attest complete execution history or prevent protected
administrator/daemon evidence mutation. Failed setup before a recorded start,
complete executable authority, mandatory image/witness binding and real Docker
acceptance remain separate gates. The
[focused tests](../../tests/test_custody_external_started_at.py) inject evidence
on both reads and preserve exact-ID one-start/child-exit controls. No container,
chain or custody generation is exercised; production and real funds remain blocked.

## Canonical non-root bind-source restriction

Both inspections require custody and secrets bind sources to be strings spelling
canonical, non-root absolute paths. `/`, relative/empty paths, NULs, repeated or
trailing slashes and `.`/`..` path components refuse even with independently
matching approval. This intentionally rejects noncanonical spellings rather than
normalizing them. The launcher must not resolve a daemon host's paths against its
own filesystem. Declared and observed sources still require exact agreement; the
full source evidence stays pinned, so second-read changes refuse before another
diff or start. Refusal never prints inspected source values.

This closes the demonstrated host-root bind path and ambiguous lexical spellings
only. **It is not a narrowly rooted source allowlist**: canonical paths such as
`/etc` or `/home` are not made safe by this check. Symlinks, inode/content continuity,
host ownership/permissions, source-subtree policy and exclusive protected daemon
administration still require independent verification. Read-only secrets and
nonrecursive binds do not make arbitrary host contents approved image bytes.
The [focused tests](../../tests/test_custody_external_bind_sources.py) inject engine
evidence and preserve exact-ID one-start/child-exit controls; no real Docker mount
or chain is exercised. Complete executable authority, mandatory image/witness
binding, coherent restore and real-engine acceptance remain open. Production and
real funds remain blocked.

## Host network namespace restriction

Both inspections refuse `HostConfig.NetworkMode="host"` even with matching
independent approval. Sharing the daemon host's network namespace exposes host
interfaces and local services outside the container's own network namespace;
a pinned configuration is not permission to take that authority. The full host
configuration and endpoint projection stay pinned, so second-read changes refuse
before a later diff or start. No network values are printed or rewritten.

This is **candidate-selected host-network sharing containment only**. Other
approved non-host modes keep their existing behavior; this rule is not an
allowlist for custom networks or endpoints. DNS, routing, proxies, published
ports, daemon-generated files, host firewall policy and effective enforcement
remain external gates. See [Docker's host-network description](https://docs.docker.com/engine/network/drivers/host/).
The [focused tests](../../tests/test_custody_external_host_network.py) inject
engine evidence, cover matching-approved refusal, second-read drift and exact-ID
one-start/child-exit controls. No real Docker container or chain request is used.
Complete executable authority, mandatory image/witness binding, narrowly rooted
bind sources, coherent restore and real-engine acceptance remain open; production
and real funds remain blocked.

## Candidate seccomp override restriction

Both inspections require explicit string-array `HostConfig.SecurityOpt` evidence
with **no option whose key is `seccomp`**. Every occurrence refuses, regardless
of order or independently matching approval: `seccomp=unconfined`, `seccomp=builtin`,
custom/inline profiles, empty values and deprecated `seccomp:<value>` forms.
Key parsing follows Moby: `=` takes precedence if present, otherwise `:`.
Missing/null/type-confused arrays or non-string members also fail closed. The
complete array stays pinned, so any second-read change refuses before later
diff/start. Refusal prints no inspected profile or option values.

[Moby's option parser](https://github.com/moby/moby/blob/d74daf1a/daemon/daemon_unix.go)
assigns each candidate seccomp option to the container profile. Its
[OCI seccomp construction](https://github.com/moby/moby/blob/d74daf1a/daemon/seccomp_linux.go)
prioritizes that profile over the daemon default. Even `builtin` selects Moby's
built-in profile instead of an independently protected custom daemon policy (see
[the pinned constant](https://github.com/moby/moby/blob/d74daf1a/daemon/config/config.go)).
Prepare the candidate without any `--security-opt seccomp=...`; this guard does
not rewrite options or issue approvals.

This contains **candidate-requested seccomp overrides only**, not effective
filtering. Independently protect and verify daemon/kernel policy: the daemon can
itself default to unconfined, and an unsupported kernel can omit the default
filter. Absence of an override does not attest those settings or runtime filter
bytes. Complete executable authority, mandatory image/witness binding, other
semantic host policy, coherent restore and real Docker effective readback remain
open. The [focused tests](../../tests/test_custody_external_seccomp.py) inject
engine evidence; no real container, chain, funds or custody generation is used.

## Supplementary group addition restriction

Both inspections require explicit `HostConfig.GroupAdd` evidence, either JSON
null or an empty array. Nonempty group lists (numeric IDs or names), missing and
malformed/type-confused evidence refuse even with matching independent approval.
The full host configuration remains pinned: any second-read change, including
between the two disabled forms, refuses before another diff or start. The launcher
never resolves, filters or rewrites group grants, and refusal discloses no values.

[Moby's user construction](https://github.com/moby/moby/blob/d74daf1a/daemon/oci_linux.go)
resolves `HostConfig.GroupAdd` and appends these groups to the OCI process's
`AdditionalGids`, independently of its primary UID/GID. An approved non-root
`Config.User`, dropped capabilities and a read-only root do not exclude these
candidate-requested supplementary access grants. Prepare the candidate without
`--group-add`; older/malformed evidence omitting the field deliberately fails closed.

This contains **candidate-requested group additions only**. Image account/group
membership, effective credentials, daemon remapping and host/bind permissions still
require independent review. Empty `GroupAdd` does not prove that the process has
no supplementary groups. Complete protected executable authority, mandatory
image/witness binding and real Docker enforcement remain open. The
[focused tests](../../tests/test_custody_external_groups.py) inject engine evidence;
no real container, chain, funds or custody generation is exercised.

## Non-root primary runtime identity restriction

Both inspections require explicit `Config.User` in canonical ASCII decimal
`UID:GID` form, with **both IDs between 1 and 2147483647 inclusive**. Empty or
missing identities, names, UID-only forms, root UID or primary GID, signs, leading
zeros, whitespace, Unicode digits, out-of-range numbers and non-string evidence
refuse even with matching independent approval. This is an intentionally narrow
supported identity format, not a claim that every other spelling is invalid Docker
syntax. The complete `Config` remains pinned; second-read changes, including a
change to another otherwise supported identity, refuse before later diff/start.

[Moby's user construction](https://github.com/moby/moby/blob/d74daf1a/daemon/oci_linux.go)
resolves `Config.User` into the OCI process UID/GID. Explicit numeric primary IDs
avoid relying on account-name/default-primary-group resolution for this check.
An approved read-only root and dropped capabilities do not make an initial root
identity non-root. Independently prepare ownership/permissions for the approved
numeric identity; the guard never repairs the image or bind sources.

This checks **Docker-reported primary IDs**, not effective runtime credentials,
supplementary groups (including image group membership and `HostConfig.GroupAdd`),
daemon UID/GID remapping, host/bind permissions or later identity transitions.
The protected daemon/runtime and image account databases remain external trust.
No-new-privileges and other existing controls must be retained; complete executable
authority, semantic host policy, mandatory witness-bound launch and actual Docker
acceptance remain open. Collected tests inject engine evidence; no container,
chain, funds or custody generation is exercised.

## Supported AppArmor profile restriction

Both inspections require explicit top-level `AppArmorProfile="docker-default"`.
Empty, `unconfined`, custom, missing and malformed profile evidence refuses, even
when the present value has an independently matching configuration digest. A
second-read change refuses before another diff or start; the profile remains part
of the existing approval projection. This intentionally excludes hosts without
AppArmor support and unreviewed custom profiles rather than treating an approval
digest as a policy exception. Refusals never print the candidate's profile value.

This is a finite **Docker-reported profile-name policy**, not attestation of the
registered profile's bytes, the host's AppArmor enablement or actual runtime
application/enforcement. Independently protect and verify host/kernel/daemon
policy, including the registered `docker-default` profile. Seccomp, network,
runtime-user and host bind-source policy, complete executable authority, mandatory
witness-bound launch and real Docker acceptance remain open. Collected tests inject
engine evidence; no container or custody generation is exercised.

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

### Reviewed published boundary at `64995d7`

The published launcher now rejects 15 narrow Docker-reported conditions. The earlier annotation,
host-gateway, healthcheck, numeric `ReadOnlyNonRecursive`, writable-cgroup, auto-remove, userns-opt-out and
prior-start-error controls are joined by supported AppArmor, canonical non-root primary UID:GID, no
supplementary groups, no candidate seccomp override, no host network and canonical non-root bind-source
spelling, then canonical zero `State.StartedAt` evidence on both inspections. The fresh staged-candidate
suite accepts only these injected-evidence boundaries; no complete history or real Docker semantics follow.

A broader four-file dirty overlay reviewed against old base `93ed7dd9` contains private IPC/cgroup/UTS, explicit device evidence, `runc`, no
daemon init/links, baseline system paths, no-new-privileges, no container-shared networking and bounded
strict JSON/byte/deadline capture. It passed 2,297 offline tests at that base but is historical candidate
evidence, not a current-tip candidate or this document's published contract. Rebase and review exact bytes
before integration; do not reconstruct them from this summary.

Fresh matching-approval probes reached injected start on the old-base published and overlay trees with a custom network and
canonical but broadly located `/etc` custody and `/home` secrets sources. Lexical source canonicality does
not define approved roots or attest symlink/inode/content continuity, ownership or permissions. A pinned
custom network does not attest DNS, routing, proxies, endpoints, ports or firewall behavior. The launcher
also is not called by `swapService.py`, `src/main.py` or the witness client; its image/configuration pins
are absent from the witness certificate. Do not install a direct Python/systemd route.

No operator may treat a matching configuration digest as an exception to semantic policy. Batch 0 exit
requires one independently protected launcher/interpreter/Docker/runc/image/approval closure, explicit
custom-network/endpoint and source-root policy with effective readback, one witness-bound sole route and
real-engine mutation/contention/crash/failed-start evidence. Coherent restore remains a separate P0
financial-authority gate.

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

## Prior startup failure restriction

Both inspections require object-shaped `State` with explicit `Error=""`, in
addition to `Status="created"` and `Running=false`. Nonempty errors, missing/null
and type-confused error values refuse before any later diff or start, without
printing the potentially private daemon error. `State` remains outside the
configuration digest; matching independent approval cannot exempt this check, and
a change on the second inspection must still refuse.

[Moby's startup path](https://github.com/moby/moby/blob/d74daf1a/daemon/start.go)
records `State.SetError(retErr)` after a failed start. Networking, mounts, OCI
construction and task creation can precede that failure; `SetRunning` occurs only
after a successful task start. A candidate can therefore still report `created`
after startup side effects. Do not automatically retry that container through the
pristine-candidate guard. Preserve its evidence for independently authorized
investigation; this launcher neither clears errors nor creates replacements.

This is containment of observed prior startup failure, not a complete audit of
execution history or protection from trusted-administrator evidence mutation.
Empty error text does not certify that no earlier side effects occurred. Protected
exclusive daemon administration, complete executable authority, external-image
witness binding and actual Docker failed-start/crash/restore acceptance remain
separate requirements. Collected tests inject engine evidence, not a real failed
OCI startup or claim/run/seal generation.

## User-namespace opt-out restriction

Both inspections require explicit `HostConfig.UsernsMode=""`, Docker's conventional
mode retaining daemon user-namespace policy. `host`, missing/null/type-confused
values and unsupported modes refuse even with matching independent approval. A
changed second inspection refuses before the second diff or start. The full field
remains part of the existing configuration approval digest.

[Moby's namespace construction](https://github.com/moby/moby/blob/d74daf1a/daemon/oci_linux.go)
only applies the daemon's UID/GID mappings when
[`UsernsMode.IsPrivate()`](https://github.com/moby/moby/blob/d74daf1a/api/types/container/hostconfig.go)
is true; `host` explicitly opts out. A read-only root and dropped capabilities do
not prevent that candidate-requested loss of identity confinement. Configure any
required remapping independently in the protected daemon, not through an approved
per-container opt-out.

This does **not** prove remapping is enabled: empty mode still uses the protected
daemon's configured mapping, which may be absent. Host permissions, initial user
identity, bind content, complete executable authority, external-image witness
binding and real Docker acceptance remain separate requirements. Collected tests
inject engine evidence and do not establish actual user-namespace enforcement.

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
