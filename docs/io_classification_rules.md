# MaleCNS I/O classification rules (v1.0.0)

Status: **implemented** in `src/io_analysis/classification.py`, which
follows exactly these documented rules (no ad hoc heuristics diverging
from what's written here). `r/build_io_census.R` still computes its own
provisional `io_role` tally inline, purely for the Phase 1 report - that
one is not persisted to any CSV; the real, persisted table is
`data/io_classification.parquet`.

**Version history**: v0 (draft, unimplemented) -> v1.0.0 (this version) -
implemented, then twice corrected after real bugs were found: the
`output_category` rule was rewritten from `exitNerve`-only to
`subclass`-first (misclassified 63+ motor neurons), then `xm` was fixed to
map straight to `unknown` instead of leaking through `exitNerve` into a
specific wrong body part. This document only states the current,
corrected rules.

Every rule below states its source field(s), its confidence, and its
fallback. Per the project's development principles: **unknown is always
preferred over a fabricated classification**, and no rule may be based
solely on a neuron's `type`/`name` string unless explicitly written out
here (none currently are).

**Confidence scale** (replaces plain low/medium/high, which conflated "this
faithfully reflects a dataset annotation" with "this is biologically
validated" - it never meant the latter):

| level | meaning |
|---|---|
| `annotation-direct` | a direct read of one MaleCNS field (e.g. `superclass`, motor `subclass`) - as reliable as the dataset's own annotation, no interpretation added |
| `derived` | a documented combination/transformation of dataset fields (e.g. folding several `class` values into one `input_category`) |
| `external-mapping` | requires outside anatomical/nomenclature knowledge not present in any MaleCNS field (the `exitNerve` -> body-part table) - lower confidence by construction |
| `unresolved` | intentionally left `unknown`/`not_input`/`not_output` rather than guessed |

## 1. `io_role`

Source field: `superclass` only. Coverage: `superclass` is populated for
164,606 / 165,122 (99.7%) of `status == "Traced"` rows, and is NA for
almost all non-traced rows (glia/orphan/assign/unimportant) - see the
report's status-crosstab. This makes `superclass` the single
highest-confidence field available for a first split.

**Explicit override, applied before the table below:** any `superclass`
value ending in `_tbc` ("to be confirmed") is mapped to `unknown`,
regardless of what the base category would otherwise suggest. The dataset
is telling us it isn't sure; we don't overrule that.

| superclass value(s) | io_role | confidence | rationale |
|---|---|---|---|
| `cb_sensory`, `ol_sensory`, `vnc_sensory`, `sensory_ascending`, `sensory_descending` | `sensory_input` | annotation-direct | superclass name states sensory function directly |
| `ol_intrinsic`, `visual_projection`, `visual_centrifugal` | `optic_processing` | annotation-direct | optic-lobe intrinsic and OL<->CB relay neurons |
| `cb_intrinsic` | `central_processing` | annotation-direct | direct match |
| `vnc_intrinsic` | `vnc_processing` | annotation-direct | direct match |
| `ascending_neuron` | `ascending` | annotation-direct | direct match |
| `descending_neuron` | `descending` | annotation-direct | direct match |
| `vnc_motor`, `cb_motor` | `motor_output` | annotation-direct | superclass name states motor function directly |
| `vnc_endocrine`, `cb_endocrine` | `endocrine_output` | annotation-direct | direct match |
| `vnc_efferent`, `cb_efferent`, `efferent_ascending`, `efferent_descending` | `other_efferent` | annotation-direct | efferent but not explicitly motor/endocrine; bucket exists for exactly this |
| `ENS` (enteric nervous system) | `unknown` | unresolved | ENS neurons don't fit any defined `io_role` bucket cleanly (peripheral, not brain/VNC intrinsic, not motor/sensory in the same sense); rather than force a fit, left `unknown`. Only 50 rows. Revisit if ENS becomes analytically important. |
| any `*_tbc` value | `unknown` | unresolved | dataset's own uncertainty marker, see override above |
| `NA` (no superclass) | `unknown` | unresolved | mostly non-traced bodies (glia/orphan/fragment); see report |

Actual counts from `classification.py`'s output (211,579 total rows):
`optic_processing` 99,167, `unknown` 45,023, `central_processing` 32,164,
`sensory_input` 17,885, `vnc_processing` 13,161, `ascending` 1,846,
`descending` 1,314, `motor_output` 815, `other_efferent` 110,
`endocrine_output` 94. `cb_intrinsic`/`ol_intrinsic`/`vnc_intrinsic` are
**not** part of `unknown` - they're their own `*_processing` io_role
values, per the mapping table above. The `unknown` bucket (45,023) is
instead 99.7% rows with no `superclass` at all
(44,879 - mostly `Orphan`/`Glia`/`Unimportant`/non-traced bodies, though
516 are `Traced` with no `superclass` recorded, a genuine minor data
gap), plus 94 `*_tbc` rows and 50 `ENS` rows.

## 2. `input_category`

Source field: `class` only. `subclass` is used only by `output_category`
(section 3); `entryNerve` is not used by any rule.

`class` is well populated specifically for sensory-superclass rows: only
111 of 17,885 sensory-superclass rows have a missing `class` - verified
directly against `data/io_census_nodes.csv`, correcting an earlier
"162 of ~9,600" figure that didn't match either the full census or the
Traced-only sensory count. That makes `class` high-confidence for this
category, unlike for `output_category` (see below).

| `class` value | `input_category` | confidence |
|---|---|---|
| `visual` | `vision` | annotation-direct |
| `olfactory` | `olfaction` | annotation-direct |
| `gustatory` | `gustation` | annotation-direct |
| `mechanosensory`, `mechanosensory_tactile`, `mechanosensory_bristle`-type subclasses | `mechanosensation` | annotation-direct |
| `mechanosensory_proprioceptive` | `proprioception` | annotation-direct |
| `mechanosensory_tbc` | `unknown` | unresolved (tbc override, same rule as io_role) |
| `hygrosensory` | `hygrosensation` | annotation-direct |
| `thermosensory` | `thermosensation` | annotation-direct |
| `chemosensory` | `other_sensory` | annotation-direct (unspecified chemosensation - not asserted to exclude olfaction/gustation, just not separately labeled as either by the dataset) |
| `unknown_sensory` | `unknown` | unresolved (dataset explicitly says "unknown") |
| `NA` and row has a sensory superclass | `unknown` | unresolved - only 111 rows |
| anything else / non-sensory superclass | `not_input` | annotation-direct |

**Open question, not yet resolved:** the candidate category
`auditory_antennal` has no matching `class` value. The only hints are in
`subclass`: `auditory` (115 rows) and `wind_gravity` (475 rows) - both
currently folded into `mechanosensation` via `class == "mechanosensory*"`.
`chordotonal organ` (425 rows) is a separate case: all 425 have
`class == "mechanosensory_proprioceptive"`, so they already land in
`proprioception`, not `mechanosensation`. Splitting out `auditory_antennal`
will require an explicit `subclass`-level rule; deferred to a future
revision of this document rather than guessed now.

## 3. `output_category`

Source fields, in priority order:

1. **`subclass`, for motor rows only** (`superclass` in `vnc_motor`,
   `cb_motor`). MANC motor-neuron nomenclature encodes the target muscle
   group directly in `subclass` - `fl`/`ml`/`hl` (front/middle/hind leg),
   `wm` (wing), `hm` (haltere), `nm` (neck), `ad` (abdomen), `pm`
   (proboscis). `subclass` is 100% populated for all 815 motor rows -
   `annotation-direct` confidence, and takes priority over `exitNerve`.
2. **`xm` -> `unknown`, always, never `exitNerve`.** MANC's own systematic-
   type scheme defines `xm` as its explicit "unknown target" code (one of
   its 8 official subclasses, confirmed against the primary MANC
   literature) - letting it fall through to a specific `exitNerve` guess
   would reintroduce exactly the kind of unsupported certainty rule 1
   exists to avoid: without this rule, 4 `xm`/`DMetaN` neurons would
   become `haltere` and 2 `xm`/`PDMNa` neurons would become `wing`.
3. **`exitNerve`, as fallback** - for non-motor efferent/endocrine rows
   (`class` is 100% missing for all of these, so `exitNerve` is what's
   left), and for the small number of motor rows whose `subclass` isn't
   one of the eight codes above and isn't `xm` (`am`, `rm` - not part of
   MANC's documented scheme, no confirmed meaning either way, left to this
   fallback rather than guessed).

**Why the original `exitNerve`-only version was wrong:** `exitNerve` says
which nerve bundle a fiber exits through, not which muscle group it
drives, and the two don't always agree with the motor-neuron's own
documented `subclass` label. Concretely: 20 `DProN` neurons are annotated
`nm` (neck motor) but were classified `front_leg`; 19 `MesoAN` neurons
annotated `wm` (wing motor) were classified `middle_leg`; 16 `AbN1`
neurons annotated `hm` (haltere motor) were classified `abdomen`; 8 more
`AbN1` neurons annotated `hl` (hind-leg motor) were also classified
`abdomen`. At least 63 motor neurons were misassigned this way, and every
annotated haltere motor neuron was excluded from the `haltere` category
entirely. Using `subclass` first fixes all of these.

| `exitNerve` value(s) | fallback `output_category` | confidence |
|---|---|---|
| `ProLN`, `ProCN`, `DProN`, `VProN`, `ProAN` | `front_leg` | external-mapping (T1/prothoracic leg nerves) |
| `MesoLN`, `MesoAN` | `middle_leg` | external-mapping (T2/mesothoracic leg nerves) |
| `MetaLN` | `hind_leg` | external-mapping (T3/metathoracic leg nerve) |
| `DMetaN` | `haltere` | external-mapping (T3 dorsal nerve, halteres are the T3 dorsal appendage by homology with T2 wings) |
| `ADMN`, `PDMN`, `PDMNa`, `PDMNp` | `wing` | external-mapping (T2 dorsal mesothoracic nerves) |
| `CvN` | `neck` | external-mapping (cervical nerve) |
| `PhN`, `aPhN`, `MxLbN` | `proboscis` | external-mapping (feeding-related head nerves) |
| `AbN1`, `AbN2`, `AbN3`, `AbN4`, `AbNT` | `abdomen` | external-mapping (abdominal nerves 1-4 and trunk) |
| `NCC` | `endocrine` | external-mapping (nervi corporis cardiaci - classic insect neurosecretory/endocrine output route) |
| `AN` (as exit nerve, rare) | `other_motor` | external-mapping (low confidence within this tier) |
| `ON` (as exit nerve, rare), `TBD` | `unknown` | unresolved |
| `PrN` | *(unmapped - falls to `unknown`)* | unresolved - T1-neuromere membership alone doesn't establish a specific leg target; 0 rows currently affected |
| comma-separated multi-nerve values (e.g. `ADMN,MesoAN`) | `unknown` | unresolved - needs an explicit multi-valued-field rule |
| `NA` | `not_output` if superclass is not output-related, else `unknown` | annotation-direct / unresolved |

`endocrine` here is derived from `exitNerve == "NCC"`, not from the
`cb_endocrine`/`vnc_endocrine` superclasses directly - those superclasses
should be cross-checked against this rule rather than assumed to agree.

## 4. General rules that apply throughout

1. A rule only exists if it is written down in this document; no
   undocumented heuristic may run in Phase 2 code.
2. Any dataset-native uncertainty marker (`_tbc` superclass suffix, `TBD`
   exit nerve, `unknown_sensory`/`mechanosensory_tbc` class) is passed
   through as `unknown`, never overridden by a more specific guess.
3. `type`/`name` string matching is not used by any rule above. If a future
   revision adds one, it must be listed here explicitly with its exact
   pattern and rationale before being used in code (development principle
   #5).
4. Synapse/connection weight is never used as an input to classification;
   classification is based on cell identity metadata only.
5. Raw fields (`data/io_census_nodes.csv`) are never overwritten by derived
   fields; Phase 2 will add `io_role`/`input_category`/`output_category` as
   a separate derived table, not by mutating the census file in place.
