# Phase 9A-I Model Weight Closure

## The single admissible weight

```text
filename  aimnet2_wb97m_d3_0.pt
bytes     8836941
sha256    f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28
family    wb97m-d3
member    0
```

The SHA256 is the complete 64-character digest, read from the merged Phase 9A-R
evidence file. Abbreviated forms such as `f0f7c054...4e28` appear in prose for
readability and are never used for comparison.

Members `_1`, `_2`, and `_3` do not exist locally. Downloading them is
prohibited. This phase runs on member `_0` alone and makes **no ensemble
uncertainty claim** of any kind.

## Preload verification

Before the weight is opened, all of the following must hold:

```text
path exists
path is a regular file
path is not a symlink
byte size == 8836941
sha256 == f0f7c054539ad3261bd36f9b11c56d12f87cb723e25bea7521755bbd3ec24e28
```

Any mismatch fails closed. On failure the run does **not** try another weight,
another path, another member, or a registry lookup. A weight that fails identity
is not a reason to search; it is a reason to stop.

## No automatic resolution

The Phase 9A-R preflight established that the calculator constructor exposes a
remote-fetch surface:

```text
AIMNet2Calculator(model='aimnet2', ..., ensemble_member=0,
                  revision=None, token=None)
```

The default `'aimnet2'` string can therefore resolve against a remote hub. All
of the following are prohibited in this phase:

```text
the literal model string "aimnet2"
any Hugging Face repository name
any registry alias
the revision parameter
the token parameter
any automatic model resolution
```

The calculator is constructed from the **explicit local weight path** only.

## Offline enforcement

Set before any `aimnet`, `torch`, or Hugging Face import, not after:

```text
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_DATASETS_OFFLINE=1
PYTHONDONTWRITEBYTECODE=1
python -I -B
```

Ordering matters. These libraries read their offline configuration at import
time, so setting the variables after the import would leave the fetch path live
while appearing to be protected.

Offline mode is a second line of defence, not the primary one. The primary
defence is that no code path in this phase supplies a model name at all.

## Post-load identity readback

After construction, before the first calculation, record from the live object:

```text
model identity
implemented_species
dtype
device
calculator implemented_properties
weight identity as loaded
```

`implemented_species` is compared against the selected candidate's element set
(`C F H N`). All four must be covered or the run fails closed with
`validate_species=True` in force.

The readback exists because a successfully loaded file is not proof that the
loaded model is the intended one. Identity is asserted from the object, not
inferred from the filename.

## Weight immutability

The weight file is read-only input. The run must not write to, move, rename,
re-serialize, re-export, quantize, compile-cache, or fine-tune it, and must not
write anything into the weight cache directory. Cache redirection is specified
in `docs/PHASE9A_I_CACHE_ISOLATION_PLAN.md`.

After the run, the weight file's byte size and SHA256 are recomputed and must be
unchanged.
