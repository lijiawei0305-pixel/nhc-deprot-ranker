# Phase 9B Parent-Level P01-R1 Report

P01-R1 closed `INCONCLUSIVE`. The mandatory full-core grid-4 audit passed and
froze grid 4, but the one authorized Group A attempt stopped before its first
AIMNet2 trajectory frame because NVRTC rejected an overlong private temporary
directory path. This is an environment/path failure, not a parent method,
molecule, memory, AIMNet2 model, or grid-4 scientific failure. The no-retry rule
was honored and Group B was not started.

## Resource selection

| Field | Observed/selected value |
|---|---:|
| System logical CPUs | 112 |
| System physical cores | 56 |
| Scheduler allocation | none detected |
| cgroup effective CPU list | `0-111` |
| initial process/taskset affinity | `0-111` |
| node exclusive | no; `NODE_NOT_CONFIRMED_EXCLUSIVE` |
| safe physical cores | 27 |
| safe logical CPUs | 54 |
| final `ALLOWED_CPU_LIST` | `0,2-27` |
| final `N_THREADS` | 27 |
| SMT used | no |
| available memory | 238,866,767,872 bytes |
| cgroup memory limit | unlimited |
| PySCF `max_memory` | 64,000 MB |

The shared-node policy kept all work on socket 0, excluded the active core seen
at discovery, and left socket 1 untouched. The 27-physical-core calibration
took `116.379018 s`; the same one-cycle calculation on 54 SMT logical CPUs took
`122.524717 s`. SMT was 5.28% slower, so it did not meet the preregistered 5%
improvement threshold.

PySCF used its bundled OpenBLAS 3.3 and `libgomp`; NumPy reported
scipy-openblas 0.3.31. `lib.num_threads()` was 27. Runtime libraries created up
to 80 OS tasks, but GNU time measured 2525% average CPU against the 2700%
selected capacity and no active oversubscription was observed.

## Grid-4 command and result

The exact private invocation is retained in
`grid4_audit/resource_usage.txt`. Its portable command shape and all effective
resource values were:

```bash
env -u PYTHONHOME -u PYTHONPATH -u PYTHONSTARTUP \
  PYTHONDONTWRITEBYTECODE=1 \
  OMP_NUM_THREADS=27 MKL_NUM_THREADS=27 OPENBLAS_NUM_THREADS=27 \
  NUMEXPR_NUM_THREADS=27 BLIS_NUM_THREADS=27 \
  VECLIB_MAXIMUM_THREADS=27 OMP_DYNAMIC=FALSE MKL_DYNAMIC=FALSE \
  OMP_PROC_BIND=close OMP_PLACES=cores \
  timeout --signal=TERM --kill-after=30s 43190s \
  taskset -c 0,2-27 <exact-gpupyscf-python> -I -B \
  <exact-p01-r1-audit-source> grid-audit \
  --root <private-r1-root> --cpu-list 0,2-27 --threads 27 \
  --memory-mb 64000 --xyz <frozen-cation-xyz> \
  --audit-source <exact-p01-r1-audit-source> \
  --audit-source-sha256 0b0abcb1b22184462a5ad0d6f9f34b936f6acbf2568555cbb0d774f812f209e0 \
  --interpreter-sha256 24a07a0a383fd666309acf92ad4e913dd372b3f2d4592d60f1f2f0ca7138fc61
```

| Metric | Grid 3 | Grid 4 | Grid 4 - Grid 3 |
|---|---:|---:|---:|
| SCF converged | yes | yes | — |
| SCF cycles | 13 | 2 | -11 |
| Grid points | 346,168 | 679,168 | 333,000 |
| Energy (Eh) | -1409.4738459183304 | -1409.4738305457154 | 0.0000153726151 |
| Energy (kcal/mol) | — | — | 0.00964646159 |
| D3 contribution (Eh) | -0.04286372842069901 | -0.04286372842069901 | 0 |
| Gradient RMS (Eh/Bohr) | 0.001639669461 | 0.001643055513 | 0.00000338605243 |
| Gradient max (Eh/Bohr) | 0.006971400996 | 0.006979380254 | 0.00000797925749 |
| SCF/gradient wall (s) | 1041.425954 | 655.006288 | — |

Grid 4 used the exact converged grid-3 density as `dm0` and independently met
`conv_tol=1e-9`; its energy, analytic gradient, and D3 contribution are finite.
The shorter grid-4 wall is therefore not an intrinsic grid cost claim. No
scientific threshold had been preregistered, so the more robust grid 4 was
frozen as required. Protocol identity is
`227c22a527e567bc4de873ab743fe9f493779eccbb1a698d2913c87695ebf87a`.

## Conditional paired benchmark

Group A used the same frozen cation/neutral input bytes, a free same-model V100,
and the audited CPU/memory configuration. The AIMNet2 weight loaded once. At
the first cation calculation, Warp/NVRTC emitted
`NVRTC_ERROR_COMPILATION`: the generated private `TMPDIR` path was too long for
NVRTC temporary-file creation. No trajectory frame was produced, and the
controller stopped after `17.732833385 s`.

No PySCF endpoint in Group A started. Under the explicit no-retry contract, the
path was not shortened and Group A was not rerun. Since Group A was incomplete,
the fixed 60-second idle and Group B were not started. Consequently there are
no paired endpoint energies, labels, Group A/B wall comparison, speedup, or
lower bound.

## Evidence identities

| Evidence | SHA256 |
|---|---|
| CPU topology | `90aad41579df8158e642bdaf0681487171885c09d03585d43af58c9b010794b7` |
| Thread selection | `39f8618c2235b86bb0d7ee77b53529cb848cc2b0e38ab40eb281ee3c2c9669bc` |
| Grid-3 result | `713ed88686eebe5de744f6430449e81970e90f9e0669dc87391a9fba1ff440e6` |
| Grid-4 result | `b6a80da336fa97a1b795f5c0fcaa36661de5b4fd384233c2c63aa6c7fb12f5a9` |
| Grid comparison | `a0bd3a43a79c2a98ef4b5111482f68dda83eae6bac2f882589acfbdf66cc53e2` |
| Protocol lock | `cb309900d01038425fbdb5785c6311b1c5ccc1783c005e44cee8819398eabb71` |
| Group A NVRTC stderr | `a2680f4a9c2e439f94f09b6d9a5c03226710701ed4f36eb3a0fcee2d5be45cad` |
| Paired terminal | `705c0d2e7631c0f35504f93037fc16c6f5ecd1f623b5799e2ae7bcca5fcaefe6` |
| Post-exit manifest | `c44e372e5ff56970ded04db7968b3a8df10b676a5968c6f2c5585daeee009d1d` |

The private mirror is `results/phase9b_parent_level_p01_r1/`; it is ignored by
Git. The manifest excludes AIMNet2 runtime caches and is post-exit stable.

## Boundary confirmation

- no xTB, GFN, DFTB, MMFF, UFF, retry, second candidate, or batch;
- no unauthorized CPU: all chemistry remained in `0,2-27`;
- no production permit, production acceptance, or label insertion;
- production runner/v9 and historical P01/v001-v006 evidence unchanged;
- all 11 public execution gates remain false; production labels remain 71.

Final classification:

`INCONCLUSIVE — 未获得足够的parent-level或资源一致性证据`

The only next step is to fix the single NVRTC temporary-path-length blocker and
seek separate authorization for one new Group A attempt. No retry is performed
under P01-R1, and Group B cannot start until Group A completes.
