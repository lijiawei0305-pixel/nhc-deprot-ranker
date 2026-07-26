# Phase 9A-S4 — Deduplicated Interpreter and Installed-Source Inspection

**Status: complete. `loader_decision: A`, grade `source_proven`.**

Attempt `phase9a-s4-v001`, one authorized SSH invocation, one used. Phases 9A-S,
9A-S2 and 9A-S3 keep their recorded results and are not modified.

## The correction that made this work

Phase 9A-S3 counted interpreter *names* before deduplicating them. This one
resolves every name to its target and keys on `(st_dev, st_ino)` **before** any
count is taken:

```text
names enumerated          python  python3  python3.1  python3.11  python3.11-config
name count before dedup   5
unique inodes after dedup 2
  inode A   python, python3, python3.1, python3.11    <- one binary, four names
  inode B   python3.11-config                          <- excluded: fails the probe
full matches              1
```

Four names, one binary. The `-config` shim was excluded by failing to run the
standard-library probe, not by a name pattern.

## Chain of custody

```text
mlff.sh          783 bytes, sha256 9a8ae2b2...e437b6, regular file, not a symlink
                 re-verified against the Phase 9A-S3 measurement; no drift
                 line 13 conda activate "<literal absolute prefix>"
                 exactly one activation target; never sourced
conda.sh         2479 bytes, sha256 c2591662..., recorded as mechanism only
interpreter      <MLFF_ENV_ROOT>/bin/python3.11, python 3.11.15
                 device/inode recorded; realpath inside the bound root
packages         aimnet 0.2.0   ase 3.29.0   torch 2.8.0
torch/version.py __version__ = "2.8.0+cu128" (line 3), cuda = "12.8" (line 5)
```

16 AIMNet files and 25 ASE files were read as text and analysed with `ast`.
Nothing was imported.

## The twenty loader questions

The path Phase 9B would pass is an **absolute** `.pt` path in the AIMNet cache.

**1. Dispatch order in `AIMNet2Calculator.__init__`** (L284–492). A regex is built
inline, `^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$` — exactly one slash. Then:

```text
L316  isinstance(model, str)
L319    _is_hf_dir     = os.path.isdir(model)
L320    _looks_like_hf = bool(_HF_ID_RE.match(model))
L321    if _looks_like_hf or _is_hf_dir:   -> Hugging Face branch
L346    else:                              -> local / registry branch
L352  elif isinstance(model, nn.Module):   -> module branch
L358  else: raise TypeError
```

An absolute path fails the regex (leading `/` empties the first segment, and it
has several slashes) and is not a directory, so it takes **L346**.

**2/3. Local-file check, and whether it precedes registry and hub.** Yes. At L347
`if not os.path.isfile(model)` guards the registry-family lookup, and
`get_model_path` (L124, `model_registry.py`) is:

```python
def get_model_path(s: str) -> str:
    # direct file path
    if not os.path.isfile(s):
        s = get_registry_model_path(s)
    return s
```

An existing file is returned unchanged. The hub branch was already skipped at
L321.

**4/5. Which branch, which helper.** L346–351: `get_model_path` (returns the path
unchanged), then `load_model(p, device=self.device)` from `aimnet/models/base.py`
L53.

**6/7. Mechanism and return.** `load_model` calls `torch.load`, not
`torch.jit.load`:

```python
try:
    data = torch.load(path, map_location=device, weights_only=True)
except Exception:
    data = torch.load(path, map_location=device, weights_only=False)
```

`weights_only=True` is attempted first; the fallback exists for legacy
TorchScript `.jpt` archives. It returns `tuple[nn.Module, ModelMetadata]`.

**8/9/10. Registry, hub, network on the local branch.** None, none, none.
`get_registry_model_family` is skipped by the `isfile` guard;
`get_registry_model_path` — the only route to `_maybe_download_asset` and its
`requests.get` — is unreachable when the path exists; the hub import at L323 is
inside the branch not taken. **The local-path branch contains no network call.**

**11. revision/token.** Consumed only by `load_from_hf_repo` at L330–336, inside
the hub branch. `get_model_path(s)` takes one argument. They cannot affect a
local path.

**12. ensemble_member.** Same: passed only to `load_from_hf_repo`. It does not
rewrite a local path.

**13. `.pt` format.** After `torch.load`, one of:

```text
dict containing "model_yaml"  -> v2: yaml.safe_load -> build_module ->
                                 load_state_dict(data["state_dict"], strict=False)
                                 requires data["cutoff"]; optional needs_coulomb,
                                 needs_dispersion, coulomb_mode, d3_params,
                                 implemented_species, family, ...
torch.jit.ScriptModule        -> v1 legacy, cutoff read from the module
anything else                 -> ValueError("Unknown model format")
```

**14. Device placement.** `device=None` resolves at L299–301 to
`"cuda" if torch.cuda.is_available() else "cpu"`, then `str(torch.device(device))`.
`load_model` applies it twice: `map_location=device` in `torch.load`, and
`model.to(device)` at base.py L118.

**15. `.eval()`.** **It is never called.** The constructor uses, at L478–484:

```python
self._train = train                 # train: bool = False
self.model.train(train)
if not train:
    for param in self.model.parameters():
        param.requires_grad_(False)
```

`train(False)` is what `eval()` does, and the parameters additionally have
`requires_grad` cleared. So inference mode is set — by a different call than
expected. Phase 9B must not "add the missing `.eval()`"; it is already handled.

**16/17. compile.** L366–369: `self._was_compiled = bool(compile_model)`, and
`torch.compile` is called **only** when `compile_model` is truthy.
`compile_model=False` therefore means exactly: no `torch.compile`, and the flag
recorded as False. Nothing else changes.

**18. `AIMNet2ASE`.** `base_calc: AIMNet2Calculator | str = "aimnet2"` (L45–51). It
accepts a calculator or a string; a string is forwarded to
`AIMNet2Calculator(base_calc)` at L58–59. It does **not** accept an `nn.Module`.

**19. charge/mult.** At the `AIMNet2ASE` layer: `self.charge = charge`,
`self.mult = mult`, then `self.update_tensors()` (L65–67), with `set_charge` and
`set_mult` available afterwards. They are not constructor arguments of
`AIMNet2Calculator`.

**20. The production constructor.**

```python
AIMNet2ASE(
    AIMNet2Calculator(model=str(absolute_pt_path), device="cuda:0"),
    charge=charge,
    mult=1,
)
```

## A versus B

**A — pass the explicit local path to `AIMNet2Calculator`.** Grade:
`source_proven`.

The two options are not a trade-off between safety and convenience, because A
*is* B: `AIMNet2Calculator` reaches the same public `aimnet.models.base.load_model`
that B would call by hand. B would then enter the `nn.Module` branch at L352,
where `self.cutoff = getattr(self.model, "cutoff", 5.0)` silently falls back to
5.0 if the attribute is missing, whereas A takes `metadata["cutoff"]` and fails
loudly. B adds a code path and a silent default without removing a single
network call.

One source-proven constraint on A: **the path must be absolute.** A relative path
with exactly one slash, such as `models/aimnet2.pt`, matches `_HF_ID_RE`, enters
the branch at L321, imports `huggingface_hub` and calls `is_hf_repo_id` before
falling through. An absolute path cannot match the regex at all.

## ASE 3.29.0 optimizer interface

`ase/optimize/lbfgs.py` sha256 `e9bf98b1946a75f8...`, `ase/optimize/optimize.py`
sha256 `6ec1b31733b7bd6c...`.

```text
1  LBFGS.__init__(atoms, restart=None, logfile='-', trajectory=None,
                  maxstep=None, memory=100, damping=1.0, alpha=70.0,
                  use_line_search=False, **kwargs)
2  Optimizer.run(fmax=0.05, steps=DEFAULT_MAX_STEPS)   DEFAULT_MAX_STEPS = 100000000
3  attach(function, interval=1, *args, **kwargs); a non-callable has .write taken
4  step count is self.nsteps, incremented in Dynamics.irun after self.step();
   get_number_of_steps() reads it; irun sets self.max_steps = self.nsteps + steps
5  forces come from self.optimizable.get_gradient(), called in irun before the
   log and again before each convergence test
6  a per-step deadline callback goes in via attach(cb, interval=1); observers run
   at irun L350
7  trajectory=None means no trajectory; a str/Path constructs one
8  restart: str | Path | None
9  restart=None (default) -> self.initialize(); set and the file exists ->
   self.read() then self.comm.barrier()
10 to disable restart, leave restart=None; that is the guaranteed no-file path
11 run() returns the convergence bool; converged(forces=None) is also available
12 actual steps: self.nsteps / get_number_of_steps()
13 observers are called AFTER the step and AFTER the log, and BEFORE the next
   convergence evaluation (irun L344-355)
14 nothing wraps call_observers() in a try, so an exception raised by a deadline
   observer propagates out of irun, out of Dynamics.run, out of Optimizer.run
```

Point 13 matters for Phase 9B: a deadline observer sees the state *after* the
step that may have exceeded the budget, which is the correct place to abort.

## Server invariance

```text
activation script before == after     true
conda.sh before == after              true
interpreter before == after           true
sources before == after               true
torch/version.py before == after      true
caches before == after                true
installed packages before == after    true
__pycache__ count before == after     true
new files                             none
weight stat before == after           true
third-party modules imported          none
```

Weights were stat-ed only — never opened, never digested.
`aimnet2_wb97m_d3_0.pt` is 8836941 bytes, matching the registered size. The
historical `inspect_aimnet2_model_d024b2a.sh` was **not** opened; no conclusion
here rests on it.

## Local validation, before the call

96 checks over 19 scenarios, led by the direct Phase 9A-S3 regression: a
conda-shaped `bin/` where `python`, `python3`, `python3.1` and `python3.11` are
links onto one binary must yield **one** interpreter. Also covered: two genuinely
distinct interpreters, zero interpreters, a `-config` shim alone, a dangling
link, a link escaping the environment root, a non-Python candidate, wrong python
and package versions, a missing distribution, missing `torch/version.py`, a wrong
local version segment, missing AIMNet and ASE source, activation byte drift, a
second activation target, and a non-literal activation target.

Three real defects were found and fixed before anything was sent:

```text
finish() crashed on the drift path because conda_sh was None rather than
absent -- that stop would have returned no output at all and wasted the call
conda_sh before/after compared records with differing key sets, so the check
could never have been true
a dangling link was excluded by a later stat failure instead of being named
```

## Scope note

The ASE closure was seeded with `ase/optimize/__init__.py`, which imports the
whole optimize package, so 25 files were read rather than the two required. All
sit on the optimizer surface; none are training or dataset source. The AIMNet
closure read 16 files and deliberately did not follow into training code.

## What did not change

```text
runner source schema        v7
runner_source_sha256        d7060a31...9c22
v7 identities               prepared_not_authorized
execution gates             eleven, all false
production loader           not implemented
identity rebaseline         none
real computation            none
```
