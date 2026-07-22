# Family Definition

## 1. Canonical axes

Family identity is exchange invariant:

```text
canonical_sorted_pair(left, right) = sorted normalized pair joined deterministically

axis_a_family = canonical_sorted_pair(N1_frag, N3_frag)
axis_b_family = canonical_sorted_pair(C4_frag, C5_frag)

combined_family =
    skeleton + "::A=" + axis_a_family + "::B=" + axis_b_family
```

Swapping N1/N3 or C4/C5 cannot change the family. Null, blank, or unrecognized fragments normalize to the explicit token `unknown`; they never produce NaN family values.

## 2. Meaning of first-phase symmetry

The legacy graph builder enforced mirror-exchange canonicalization/deduplication. It did not require identical substituents on the two positions of each axis.

Audited evidence:

- only 896 of 401,856 candidates (0.223%) have both N1=N3 and C4=C5;
- the full pool has 528 axis-A, 406 axis-B, and 214,368 exact combined families.

Code and tests must therefore assert exchange invariance, not strict positional equality.

## 3. Skeleton source

Priority is:

1. explicit skeleton column;
2. explicit, versioned source metadata;
3. tested SMARTS classification;
4. `unknown`.

The audited Phase 0 snapshot is explicitly the imidazolium candidate pool, so `skeleton=imidazolium` is source metadata. A filename substring is not used as a classifier.

## 4. Model behavior

H1 initially uses additive partially pooled effects for `skeleton`, `axis_a_family`, and `axis_b_family`. Unknown effects equal zero and fall back to the global affine prediction.

The 71 labels contain:

- 38 axis-A families, including 22 singletons;
- 35 axis-B families, including 16 singletons;
- 71 exact combined families, all singletons.

Exact combined-family effects are therefore disabled in the MVP. They can be reconsidered only with adequate group support and grouped-CV evidence.
