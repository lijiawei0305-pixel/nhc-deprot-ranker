# Phase 9B science pilot v003 plan

## Scope

This is a one-candidate, non-production continuation for
`LBNPGYISTSLAHY-UHFFFAOYSA-N`. Stage A reads the retained v002 XYZ bytes and
performs geometry-only adjudication. It does not run AIMNet2, PySCF, RDKit,
force fields, xTB, or any production control plane.

Stage B is reachable only when the durable Stage A classification is exactly
`SAME_BASIN_LIKELY`. It then uses the retained v002 AIMNet2 final XYZ bytes for
two serial frozen-protocol PySCF single points. It never changes the v002
terminal result or the production 10-degree gate.

## Frozen identities

- candidate: `LBNPGYISTSLAHY-UHFFFAOYSA-N`;
- atom map: C2=14, N1=8, N3=15;
- cation: +1, multiplicity 1, 26 atoms, H23 hosted by C2;
- neutral: 0, multiplicity 1, 25 atoms, no cation H23;
- v002 result SHA256:
  `b1362a3b1df7ef7ba276bac0c91fd8002fd27123eca37d84a82b937edacd7071`;
- cation final SHA256:
  `ea796a5c81504184382b965d57c588c74968a09de8942148d3d9cbadf70a7774`;
- neutral final SHA256:
  `c40ca77bce9d8c8deefc2357bf2633fb4c0981ce9d4bd23aceb342d40646bc93`.

## Stage A method

The review uses frozen atom order, NumPy deterministic linear algebra, and the
same covalent-radius plus 1.30 tolerance connectivity rule used by v002. It
does not perform graph isomorphism or same-element atom exchange.

The analysis reports whole-geometry Kabsch metrics, exact added/removed bonds,
connected components, the unique five-membered N1-C2-N3 ring, all five ring
bonds and angles, best-fit-plane metrics, five ring dihedrals, C2 height above
the other four ring atoms, all heavy-atom dihedrals, side-chain changes, and
the cation-minus-H23 common-atom comparison.

Stage A classifies `SAME_BASIN_LIKELY` only if all user-frozen identity and
connectivity conditions hold and all of the following review-only diagnostic
criteria hold:

- one connected component, no added/removed bond, and minimum pair distance
  at least 0.70 angstrom (the production 0.20-angstrom gate is also reported);
- globally aligned RMSD at most 1.0 angstrom and maximum aligned displacement
  at most 2.5 angstrom;
- each C2-N change at most 0.15 angstrom and each final C2-N bond between
  1.20 and 1.60 angstrom;
- unique five-membered ring identity unchanged;
- final ring RMS out-of-plane at most 0.10 angstrom, maximum ring
  out-of-plane at most 0.20 angstrom, C2 height above the other-four-atom
  ring plane at most 0.20 angstrom, and maximum absolute ring dihedral at most
  30 degrees;
- aligned ring-plane normal changes by at most 30 degrees and no resolved
  ring flip is observed;
- no ring-to-side-chain dihedral changes by 120 degrees or more;
- the preregistered 10-degree N1-C2-N3 gate is the only failed v002 structure
  gate.

These review diagnostics are not production gates and do not replace the
frozen 10-degree gate. They make the conditional scientific adjudication
reproducible. `SAME_BASIN_LIKELY` means the retained geometry supports
topology and local-conformation continuity; it is not a mathematical proof of
membership in one potential-energy basin.

Any identity/connectivity/ring failure is `DIFFERENT_BASIN_OR_INVALID`.
Missing, contradictory, or unreliable evidence is `INCONCLUSIVE`.

## Stage B boundary

Only an exact Stage A `SAME_BASIN_LIKELY` receipt permits creation of the new
`science_pilot_lbn_pyscf_v003` root. Stage B performs no geometry optimization.
It copies each retained v002 final XYZ as raw bytes, proves source/copy/parser
byte equality, and runs cation then neutral single points using the repository
frozen method. There is no retry, parameter substitution, second candidate,
production acceptance, or label-table write.

## Retained Stage A terminal

The one-shot execution of commit `16968e549bebde0f69b7cdfe91a0505344fc4c47`
ended `INCONCLUSIVE`. Its signed ring dihedrals use a convention in which a
planar ring is near plus or minus 180 degrees, but the executed adjudicator
compared their absolute values with 30 degrees. The resulting planarity boolean
is invalid even though the independently recorded best-fit-plane metrics show
the final ring became more planar. The raw review was retained without
overwrite or rerun, and Stage B did not start.
