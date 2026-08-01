# Phase 9B Parent-Level P01-R2 Report

Final classification:

`INCONCLUSIVE — 环境或资源证据仍不足以完成parent-level paired benchmark`

The R1 protocol and grid evidence were verified by SHA and were not rerun. A
safe short path was created and propagated correctly, but the single authorized
technical smoke stopped in its smoke driver before CUDA/NVRTC evaluation. The
formal replacement Group A attempt and Group B therefore did not start.

## Historical bindings

| Evidence | Verified SHA256 |
|---|---|
| R1 protocol lock | `cb309900d01038425fbdb5785c6311b1c5ccc1783c005e44cee8819398eabb71` |
| Frozen protocol | `227c22a527e567bc4de873ab743fe9f493779eccbb1a698d2913c87695ebf87a` |
| R1 Grid-4 result | `b6a80da336fa97a1b795f5c0fcaa36661de5b4fd384233c2c63aa6c7fb12f5a9` |
| R1 post-exit manifest | `c44e372e5ff56970ded04db7968b3a8df10b676a5968c6f2c5585daeee009d1d` |

No CPU discovery, SMT calibration, Grid-3, Grid-4, grid comparison, method
identity audit, D3 audit, or protocol freeze was rerun.

The retained R1 error path was the `TMPDIR` assigned by science-pilot cache
isolation. Its private absolute path was 139 characters. It is publicly
projected as:

```text
<private-r1-root>/paired_benchmark/group_a/aimnet_stage/
science_pilot_lbn_v002/aimnet2/cache/tmpdir
```

## Short-path recovery

`/dev/shm` was a real writable directory with 134,697,390,080 bytes available.
`mkdtemp(prefix="p01r2.")` created a private root projected as
`/dev/shm/p01r2.<private-suffix>`: 24 characters, owned by the current user,
mode `0700`, and not a symlink.

The following variables were set to private subdirectories beneath that root:

```text
TMPDIR
TMP
TEMP
CUDA_CACHE_PATH
TORCH_EXTENSIONS_DIR
TRITON_CACHE_DIR
XDG_CACHE_HOME
NUMBA_CACHE_DIR
```

The actual MLFF Python parent probe and a `python -I -B` child observed identical
values. `tempfile.gettempdir()` equalled `TMPDIR`. The controller environment is
constructed from `os.environ.copy()` and explicitly validates that every path
remains below the short root.

## One-evaluation smoke

The actual command was the following path-sanitized projection; the unredacted
argv is retained in `smoke_resource_usage.txt`:

```bash
env -u PYTHONHOME -u PYTHONPATH -u PYTHONSTARTUP \
  NHC_P01R2_SHORT_TMP_ROOT=/dev/shm/p01r2.<private-suffix> \
  TMPDIR=/dev/shm/p01r2.<private-suffix>/tmp \
  TMP=/dev/shm/p01r2.<private-suffix>/tmp \
  TEMP=/dev/shm/p01r2.<private-suffix>/tmp \
  CUDA_CACHE_PATH=/dev/shm/p01r2.<private-suffix>/cuda \
  TORCH_EXTENSIONS_DIR=/dev/shm/p01r2.<private-suffix>/torch \
  TRITON_CACHE_DIR=/dev/shm/p01r2.<private-suffix>/triton \
  XDG_CACHE_HOME=/dev/shm/p01r2.<private-suffix>/xdg \
  NUMBA_CACHE_DIR=/dev/shm/p01r2.<private-suffix>/numba \
  timeout --signal=TERM --kill-after=10s 600s \
  <exact-mlff-python> -I -B <exact-r2-helper> smoke \
  --xyz <frozen-cation-xyz> --weight <frozen-aimnet2-weight> \
  --gpu-index 0 --gpu-uuid <private-bound-v100-uuid>
```

The model constructor was invoked once and no optimizer was created. The helper
then called the generic endpoint `energy_and_forces()` method before binding the
frozen element sequence through `new_atoms(elements=..., coordinates=...)`.
The real wrapper rejected the empty element binding before any CUDA energy/force
evaluation:

```text
Aimnet2RuntimeError: an endpoint geometry must have at least one atom
```

Therefore:

```text
smoke status       INCONCLUSIVE_SMOKE_DRIVER_ERROR
failure code       SMOKE_DRIVER_EMPTY_ELEMENT_BINDING
NVRTC reached      false
energy/forces      unavailable
optimizer started  false
trajectory frames  0
label created      false
external wall      15.763935804 s
exit code          1
```

This is not an AIMNet2 species, molecular geometry, CUDA-memory, PySCF, or
parent-protocol failure. The helper was corrected afterward to create an atoms
object with the frozen element sequence and then call the shared finite
energy/force reader. The one-smoke/no-retry contract prohibited executing that
correction in P01-R2.

## Formal routes

The replacement Group A prerequisite did not pass, so no formal Group A command
was executed. There are no cation/neutral AIMNet2 optimizations, handoffs,
parent-level endpoint energies, Group A label, or Group A route time.

Consequently the fixed idle interval and Group B were not started. There is no
Group B geometry optimization, final single point, label, total time, speedup,
geometry comparison, endpoint energy penalty, or label delta.

## Cleanup and evidence

After confirming no related process remained, the short-root file count and
byte count were recorded. Cache binaries were not copied into scientific
evidence. The specifically validated `/dev/shm/p01r2.*` directory was removed;
it no longer exists and residual file/process counts are zero.

| Evidence | SHA256 |
|---|---|
| Environment parent | `720947e35a486d652b358c97df04ccd389cf38611ea5843a367138c5f2abba8e` |
| Environment child | `a7644462f30cd5f9f9c8bcf8df66051b03452dcb02b5d8f644ce4088fcd78a96` |
| Smoke stderr | `11e840a681abb0ab2097a061ff210e83af26ba5e1c0e80c9ade9149ccfff484a` |
| Smoke result | `052bc904fe2b649679490ad46f17fbde17c222dd57aba1fe19707b2c2f2f72a5` |
| Cleanup | `facf2c269a5a5e239009cde5b79902f721521207419c126d5939e43b20045cb8` |
| R2 terminal | `8d75e1e2c7b15a2964c41b6b71920efc6ee464d2e942046a5b0fe78850ddc92a` |
| R2 manifest | `94aecdb1d9eec6dfda98175e80d00fe61b02b5e1736d63730b1cf136cf98bf98` |

The ignored private mirror is `results/phase9b_parent_level_p01_r2/`. The
post-exit manifest is stable and contains no temporary compiler cache.

## Boundary confirmation

- no Grid-4, CPU, SMT, method, D3, or protocol rerun;
- no xTB/GFN/DFTB/MMFF/UFF, retry, third Group A attempt, second candidate,
  extension, or batch;
- no production permit, accepted state, or label insertion;
- production runner/v9 unchanged;
- all 11 public gates remain false and production labels remain 71.

The only next step is separate authorization for one corrected one-evaluation
smoke using the already-patched `new_atoms` element binding. It must not
automatically start Group A or Group B.
