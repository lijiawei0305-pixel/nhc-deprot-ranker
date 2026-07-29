# Phase 9B Parent-Level P01-R3 Report

Final classification:

`INCONCLUSIVE — environment or Group A evidence remains insufficient for the parent-level paired benchmark`

The corrected AIMNet2 technical smoke passed and executed a real CUDA kernel.
The sole formal Group A replacement attempt then failed before model load because
the science-pilot offline-cache verifier still compared the valid short cache
paths against the long evidence cache root. The no-retry rule was honored and
Group B did not start.

## Source and historical identity

- starting commit: `e3dc66e247a3d80f368a49b4d9986778d82b1256`;
- execution source commit: `b24a7de020b580542fdaac288879511e37f86f4c`;
- branch: `agent/phase9b-science-pilot`.

| Historical evidence | Verified SHA256 |
|---|---|
| Protocol identity | `227c22a527e567bc4de873ab743fe9f493779eccbb1a698d2913c87695ebf87a` |
| Protocol lock | `cb309900d01038425fbdb5785c6311b1c5ccc1783c005e44cee8819398eabb71` |
| Grid-4 result | `b6a80da336fa97a1b795f5c0fcaa36661de5b4fd384233c2c63aa6c7fb12f5a9` |
| R1 manifest | `c44e372e5ff56970ded04db7968b3a8df10b676a5968c6f2c5585daeee009d1d` |
| R2 manifest | `94aecdb1d9eec6dfda98175e80d00fe61b02b5e1736d63730b1cf136cf98bf98` |

No CPU/SMT/Grid-3/Grid-4/D3/method audit or protocol freeze was rerun.

## Corrected element binding and short environment

The helper uses the actual runtime API:

```python
calculator = base.calculator_for(charge=1, multiplicity=1)
atoms = calculator.new_atoms(elements=elements, coordinates=coordinates)
energy, forces = runtime.read_energy_and_forces(atoms, atom_count=len(elements))
```

The real frozen XYZ parser produced 26 elements and 26 coordinate rows with
three columns. Element-order SHA256 was
`eb7439bedb2ecbc38e2a1dd214b5f4ed08c1cb775a88fe853bcc60ad23d13f4a`.

The private root projected as `/dev/shm/p01r3.<private-suffix>` was 23
characters, mode `0700`, owned by the current user, non-symlink, writable, and
had 134,697,390,080 bytes available. Parent and child observed identical
`TMPDIR`, `TMP`, `TEMP`, CUDA/Torch/Triton/XDG/Numba paths, and
`tempfile.gettempdir()` equalled `TMPDIR`.

## Corrected technical smoke

The actual command was:

```bash
env -u PYTHONHOME -u PYTHONPATH -u PYTHONSTARTUP \
  NHC_P01R2_SHORT_TMP_ROOT=/dev/shm/p01r3.<private-suffix> \
  TMPDIR=/dev/shm/p01r3.<private-suffix>/tmp \
  TMP=/dev/shm/p01r3.<private-suffix>/tmp \
  TEMP=/dev/shm/p01r3.<private-suffix>/tmp \
  CUDA_CACHE_PATH=/dev/shm/p01r3.<private-suffix>/cuda \
  TORCH_EXTENSIONS_DIR=/dev/shm/p01r3.<private-suffix>/torch \
  TRITON_CACHE_DIR=/dev/shm/p01r3.<private-suffix>/triton \
  XDG_CACHE_HOME=/dev/shm/p01r3.<private-suffix>/xdg \
  NUMBA_CACHE_DIR=/dev/shm/p01r3.<private-suffix>/numba \
  timeout --signal=TERM --kill-after=10s 600s \
  <exact-mlff-python> -I -B <exact-r3-helper> smoke \
  --xyz <frozen-cation-xyz> --weight <frozen-aimnet2-weight> \
  --gpu-index 0 --gpu-uuid <private-bound-v100-uuid>
```

| Smoke metric | Result |
|---|---:|
| Parsed atoms / coordinate shape | 26 / 26x3 |
| CUDA evaluation | reached |
| NVRTC/kernel | `PASS_CUDA_KERNEL_EXECUTED` |
| Energy | `-38353.04313413836 eV`, finite |
| Forces | 26x3, finite |
| Maximum force | `2.6004734797483597 eV/Angstrom` |
| Model loads | 1 |
| Endpoint wrappers | 1 |
| Calculator invocations | 2 |
| Optimizer / trajectory / label | none / 0 / none |
| Internal / external wall | `31.145939308 / 37.710401773 s` |
| Exit | 0 |

The shared reader made one energy and one force property request at the same
frozen geometry, producing two measured calculator invocations. This measured
count is retained rather than relabelled as one low-level forward call. Smoke
time was not included in formal Group A timing.

## Formal Group A replacement

The exact private argv is retained in `controller_resource_usage.txt`; its
portable projection was:

```bash
env <same-short-cache-environment> \
  OMP_NUM_THREADS=27 MKL_NUM_THREADS=27 OPENBLAS_NUM_THREADS=27 \
  NUMEXPR_NUM_THREADS=27 BLIS_NUM_THREADS=27 \
  OMP_DYNAMIC=FALSE MKL_DYNAMIC=FALSE OMP_PROC_BIND=close OMP_PLACES=cores \
  timeout --signal=TERM --kill-after=30s 21590s \
  taskset -c 0,2-27 <exact-gpupyscf-python> -I -B \
  <exact-parent-benchmark> assisted-controller \
  --threads 27 --cpu-list 0,2-27 --max-memory-mb 64000
```

The attempt ended after `0.464874506 s`, before model load or the first
trajectory frame. `verify_offline_environment()` was still called with the long
attempt cache root, while the deliberately isolated environment pointed to the
audited short root. It rejected `TORCHINDUCTOR_CACHE_DIR`:

```text
GROUP_A_SHORT_CACHE_VERIFIER_ROOT_MISMATCH
cache root is not redirected into the attempt: TORCHINDUCTOR_CACHE_DIR
```

This is an environment-verifier integration failure, not a molecular, model,
CUDA-memory, PySCF, or parent-protocol scientific failure. The verifier call was
subsequently patched to use the audited short root in opt-in mode and retain the
historical long attempt root otherwise. It was not executed again.

Consequently cation/neutral AIMNet2 optimization, structure review, handoff,
parent-level single points, Group A label and route timing are unavailable.

## Group B and comparison

Group A did not complete, so the 60-second idle and Group B were not started.
There is no PySCF-only optimization, final single point, label, route wall,
speedup/lower bound, geometry comparison, endpoint energy penalty or label
delta.

## Cleanup and evidence

The short root was safely removed after recording its file count and bytes.
Residual file and process counts are zero; compiler caches are excluded from the
durable manifest.

| Evidence | SHA256 |
|---|---|
| Corrected smoke | `3c0f7ad1fa644feb5cf4959739a85ce0479d6576d662eb37dbf817612c05a22f` |
| Group A failure terminal | `1821b7280354958064f257024672ad923dfe71817c7df0b3ce2139e8ac37dcb0` |
| R3 terminal | `1550cf7d7f5df926a40763015ff2c7f70ea9c5fe291cc93c755695516344bdb2` |
| R3 post-exit manifest | `b4dcf1bc9582f7462b86d7910ddc03246291a1405cad6390c467871bfb05c8a8` |

The ignored private mirror is `results/phase9b_parent_level_p01_r3/` and the
manifest is post-exit stable.

## Boundary confirmation

- no Grid/CPU/protocol rerun;
- exactly one corrected smoke and no smoke retry;
- exactly one formal replacement Group A attempt and no additional attempt;
- no Group B, second candidate, extension, batch, xTB/GFN or rescue method;
- no production permit, production label insertion, runner/v9 or gate change;
- all 11 public gates remain false and production labels remain 71.

The only next step is separate authorization for one new formal Group A attempt
using the already-patched effective short-cache-root verifier. It must not
repeat the smoke or automatically start Group B.
