# Model Specification

Status: B0/B1 and H1 are implemented and validated; production selection is deferred to Phase 4; H2 remains out of scope.

## B0 — raw xTB

```text
y_hat = xtb_deprot_kcal
```

This is the permanent ranking baseline. The common proton constant does not affect rank.

## B1 — global affine calibration

```text
y_hat = beta_0 + rho * xtb_deprot_kcal
```

The intercept and slope are free. The legacy 71-label fit found `rho≈0.716`, which is why a slope fixed at 1 is not acceptable. A positive affine slope cannot improve full-data ranking by itself, but fold-specific predictions, uncertainty, and absolute calibration still require honest evaluation.

## H1 — partially pooled additive family calibration

```text
y_i = beta_0 + rho*x_i
      + u_skeleton[s_i]
      + u_axis_a[a_i]
      + u_axis_b[b_i]
      + epsilon_i
```

The penalized objective is the weighted residual sum of squares plus separate L2 group penalties. The intercept is unpenalized; the slope penalty defaults to zero. Unknown categories contribute zero.

For dataset v001, all 71 labels have the single `imidazolium` skeleton. Its coefficient is therefore non-identifiable separately from the intercept and is fixed to exactly zero with status `inactive_single_level`. This is an identifiability rule, not a physical claim.

The estimator interface is:

```text
fit(X, y)
predict(X)
predict_components(X)
get_coefficients()
save(path)
load(path)
```

## Numerical rules

- Center/scale continuous inputs using training-fold statistics only.
- Store training ranges, category vocabularies, centering, penalties, rank, condition number, and solver fallback.
- Solve the penalized normal equations; use a pseudoinverse when rank/conditioning requires it and record that fact.
- Reject non-finite model inputs.
- Save deterministic model and manifest hashes.

## Optional H2 and ablations

At most one standardized size term may enter H2 after grouped/size-extrapolation evidence. Broad xTB electronics/ESP and exact combined families remain named ablations only. They cannot become the default from in-sample fit or ordinary random CV.

## Promotion

B1 or H1 replaces B0 only through the configured honest ranking gates. H1 must also beat or remain non-inferior to B1 without family collapse. A valid final outcome is that B0 wins or evidence is insufficient.
