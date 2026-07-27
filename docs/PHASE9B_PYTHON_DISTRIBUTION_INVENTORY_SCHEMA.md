# Phase 9B-U5 Python Distribution Inventory Schema

`PythonDistributionInventoryV1` scans every non-symlink
`lib/python*/site-packages/*.dist-info` and
`lib64/python*/site-packages/*.dist-info` directory without running or importing
a package installer.

Each distribution requires a non-symlink, stable, strict-UTF-8 `METADATA` file
with `Name` and `Version`. The row binds directory name, environment-relative
directory, raw METADATA SHA256, original and canonical name, version, and
state/SHA256/byte count for `RECORD`, `INSTALLER`, `REQUESTED`,
`direct_url.json`, `entry_points.txt`, `top_level.txt`, and `WHEEL`. Those
auxiliary files may be absent but may not be symlinks or unstable non-regular
objects.

The inventory reports every distribution, not merely critical packages:

```text
all_distribution_count
all_distribution_inventory_sha256
canonical_name_version_sha256
duplicate_name_report
critical_distribution_projection
```

Duplicate normalized names and same-name/different-version rows are explicit
in the duplicate report. The critical projection always has one present/absent
row for AIMNet, ASE, geomeTRIC, h5py, networkx, NumPy, both NValChemi
distributions, pip, PySCF, pyscf-dispersion, SciPy, setuptools, six, and Torch.
Absence is evidence rather than an implicit omission because protected source
environments legitimately carry different package subsets.

Same-object before/after requires exact equality of the all-distribution
inventory. Changes to METADATA or any tracked auxiliary file therefore move
the stable protected projection.
