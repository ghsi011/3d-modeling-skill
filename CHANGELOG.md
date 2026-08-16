# Changelog

All notable changes to the **3d-modeling** skill are documented here.
This project loosely follows [Keep a Changelog](https://keepachangelog.com/) and
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed — the confined child stops importing `ezdxf` for candidates that never mention it

`build123d/__init__.py` is eager: 24 submodules, and importing any one of them executes
the package body first, so a candidate asking for seven names also pays for `ezdxf`,
`sklearn` and everything those two drag. `pipeline/lazy_build123d.py` binds `build123d`
in the child to a module built from `find_spec` — real path, real loader, *not executed*
— carrying a PEP 562 `__getattr__` that resolves a name by importing the package's own
submodules in the package's own order, minus `{exporters, import_dxf, brep_from_stl}`.
Anything the search cannot serve executes the real `__init__.py`, so no name and no side
effect is lost; they are deferred, and only while nothing asks.

**Measured, one fresh confined child per run, arms interleaved, on the real bearing
candidate:** median wall **5.931 s → 4.299 s (1.632 s, 27.5%)** and `build_seconds`
**4.910 s → 3.404 s (1.505 s, 30.7%)**, ranges not overlapping, one STL sha256 and one
declared-`PARAMS` digest across every run of both arms. `docs/baseline.md` carries the
arm-by-arm attribution and is where the change point is recorded: `build_seconds` still
measures the phase it always measured and the implementation underneath it got faster,
so figures from before that heading are preserved and are not comparable with figures
after it.

**The omission is the design, and one of the three is in it for a reason that is not
speed.** `exporters` and `import_dxf` are `__init__`'s sixth and ninth imports, ahead of
the submodules carrying `Box` and `chamfer`, and each is worth about 0.7 s. Omitting
`brep_from_stl` measured **+0.011 s** against a 0.39 s spread — nothing — and it was
removed on that; the identity sweep put it back, because it binds `copy` to the *module*
where `__init__` leaves the *function*. It is omitted because it cannot be served
correctly.

**Only for releases actually swept.** The optimization arms itself on first contact with
the package, and only for a `build123d` version whose whole namespace has been compared
object by object (0.11.1: 474 names, 0 conflicts). Any other release executes the real
`__init__.py` — asserted against an arm that never installed a facade. `pyproject.toml`
keeps `build123d>=0.9`: narrowing a dependency range to protect a speedup would pay for
it with the ability to install.

**Ten defects found before this shipped, none of which a build could have seen behind a
byte-identical mesh, and every one of them a route into the package the facade's hooks
did not answer the way build123d does.** Three the equivalence sweep caught while the
slice was being written: `dir(build123d)` returning 11 names where the package returns
485; `build123d.pack` answering with the submodule where `__init__` binds a function of
the same name; and `build123d.__doc__` reading `None`. Three more were found by
independent reads at a head where every suite was green and seventeen mutations were
killed — all three routes that do not reach `__getattr__`, which PEP 562 consults only
about a lookup that *failed*:

* `vars(build123d)` and `build123d.__dict__` carried **9** names against **485**, and
  `'Box' in vars(build123d)` was `False`. A module's `__dict__` cannot fail, so nothing
  was ever asked. The module's *class* is the only hook for it, and the facade now has
  one whose `__dict__` executes the real `__init__.py` — putting `types.ModuleType` back
  when it does, so nothing of it outlives the fallback;
* the import system *writes* that namespace. `import build123d.pack` binds the submodule
  onto its parent by `setattr`, and `__init__.py` leaves a *function* there, so
  `build123d.pack(shapes)` raised `TypeError: 'module' object is not callable` through
  the boundary and worked without it. Measured against the executed package, all 24
  submodule names: exactly `pack` and `import_dxf` are rebound, and those two writes are
  declined. The other 22 are what an ordinary import leaves and they stand;
* `install()` stepped aside for a candidate's own `build123d.py` and installed itself
  over a candidate's own `build123d/`. Before the repair the candidate's first attribute
  access died with `ModuleNotFoundError: No module named 'build123d.persistence'`, from a
  package it had supplied itself. **A third reading found that repair incomplete**, and
  it is the clearest case in this entry of a rule answering the wrong question: requiring
  the spec to carry the search's 24-name inventory proves *shape*, and a candidate that
  ships a complete `build123d/` has exactly that shape — while `installed_version()` goes
  on reading the installed distribution's metadata, which is a fact about site-packages
  and not about the package on `sys.path`. Measured: the shape rule returned True and
  `install()` returned True over a 24-name candidate package. A `build123d` is now
  declined on **origin** as well — the boundary passes the sealed input directory it put
  on `sys.path`, and a spec resolved out of it is the candidate's whatever it looks like.

And four more from independent probes against the heads that repaired those, which is the
plainest statement available that a repair is a change and has to be measured like one:

* **`importlib.reload` executed the package body twice, and the `vars()` repair is what
  introduced it.** `SourceLoader.exec_module` reads `module.__dict__` to execute *into*,
  and that read was the new namespace property — so it executed `__init__.py` and the
  reload then executed it again: `modify_copyreg` twice where the real package runs it
  once. The facade now retires without executing when the import system rebinds
  `__spec__` to a fresh spec, which it does before the exec;
* **a candidate's monkeypatch did not survive the fallback.** `build123d.Box = ...`
  followed by a read of one of the seven deferred-only names re-executed `__init__.py`,
  which rebound the name; the real package keeps the write because an ordinary attribute
  read re-executes nothing. Writes that arrive from outside are now put back after the
  execution — and deliberately *not* after a reload, which is supposed to wipe them;
* **first contact was not exactly-once and left a window.** `if not flag: flag = True`
  has a gap between its test and its set, so two threads could both arm — running
  `modify_copyreg()` twice — and the hooks came off *before* the package body ran, so a
  second thread could meet an ordinary module with no `__getattr__` and a half-filled
  namespace and get `AttributeError` for a name the package has. The claim is now
  `dict.setdefault`, the loser waits on a latch, and the hooks come off after the
  execution rather than before.

`install()` also stopped raising `AttributeError` on a loader without `get_code`, which
PEP 451 does not require of a loader the import system handles perfectly.

28 mutations attempted, 28 killed, 0 survived
(`benchmarks/mutations/lazy-build123d-facade.json`). The `dir()` guard survived twice and
moved its fixture twice rather than being dropped: first because the whole-surface
comparison reads `__version__` before it asks for `dir`, then because the `vars()` repair
answers `dir()` before `__dir__` is reached — CPython fetches `__dict__` through ordinary
attribute access first — so it is now named against a direct `build123d.__dir__()` call.
Three entries were removed rather than kept as survivors, because each repair removed the
code its predecessor protected.

Deliberately not done, so the scope is legible later: no generic lazy-import machinery,
nothing under `site-packages` touched, no library stubbed, no warm child kept alive, no
cache semantics changed, and the trimesh lane untouched — a candidate that never names
build123d pays one `find_spec`.

### Added — revision 4's run: the first `CAD_PASS / 3MF_PASS`

A fresh isolated designer, dispatched after revision 4 was frozen and pushed, cleared
**all eighteen CAD rows and all five 3MF rows** — the first time a candidate working only
from the request has satisfied F1's hard acceptance end to end. The surface distance read
0.0011 mm against the 0.300 mm band.

**It does not exercise revision 4's change, and that is stated in the fixture rather than
left to be assumed.** Measured: this candidate's interior ring count drops from two to one
at z = 20.95, and so does the reference's — they agree on divider height, so the divider
region had nothing to exclude and the row would have read the same at revision 3. What
establishes the exclusion is the adversarial pair on constructed geometry, not this run.

The height masks did carry real work here, so the pass is not an artefact of masking
everything: retained p99 0.0011 against an unmasked p99 of 0.251 and a worst point of
0.8824. And the row can still fail — proven three ways at this head, not inferred from a
run that passed: the lip-support control fails at 0.8097, the mutation that makes the row
always pass is killed, and the mutation that broadens the divider exclusion into the whole
height band is killed by that same control.

Still `NEEDS_MORE_EVIDENCE` from the pipeline itself, for the reason every run has hit:
the compiled plan sets `verification_dispatch: NEVER` and no renderer is installed, so the
`CAD_PASS` is the benchmark's verdict and not the pipeline's.

### Changed — the distance row's scope now matches the request at the divider (revision 4)

The reviewer's ruling on run 03: do not state a divider height from the hidden reference,
and do not demote the whole registered-distance row. Keep the row, and make its scope
match the request — above the compartment band, exclude the **divider region
geometrically, not the whole z band**, because the lip and its support at those same
heights remain determined and must stay hard-judged.

The exclusion is a slab about the divider's own plane: ±3.6 mm across (half the stated
1.2 mm thickness, plus the stated 0.2 mm tolerance, plus the 2.8 mm internal fillet the
cited file contemplates), ±17.95 mm along it (the published short footprint less the
published lip depth less the tolerance, so the lip ring is never inside it), above
z = 18.0 (the compartment band's own top). Every bound is arithmetic on a request-side
fact; none comes from run 03, the reference, or any measured residual. It is applied
identically to both solids — an asymmetric rule would be a handicap, not a scope.

**The control was built first, and it had to be re-sized.** A 10 mm notch in the lip
support removes 65.68 mm³ — about half a percent of the sampled surface — and p99 could
not see it at all (0.0000), which is the limit the fixture already records. The control
that ships removes the lip support along a whole long side (463.31 mm³) and failed the
row at p99 = 0.7931 against revision 3, *before* the exclusion existed. With the
exclusion in place it still fails, at 0.8097 — so the repair did not collapse into a
height band.

Two bins differing only in divider top height now both clear the row (p99 = 0.0000 in
both directions), in L0 and again against the hidden reference in L0-heavy. What the
exclusion deliberately does not reach is recorded: the divider's last stretch where it
meets the lip ring leaves 0.427 % of samples beyond the band, worst point 1.97 mm, under
the p99 cut. Extending the bound further would start excluding the lip ring itself.

Two mutations added — removing the exclusion, and broadening it into the whole height
band — both killed. 34 in the manifest.

### Added — revision 3's first run: sixteen named rows pass, one whole-shape row does not

A fresh isolated designer, dispatched after revision 3 was frozen and pushed, scored
`CAD_FAIL / 3MF_PASS`. **All sixteen named predicates passed** on geometry nobody here
authored — the base profile to 0.0 mm, the two feet, the floor height, both lip rows,
and `outer_corner_radius_mm` at 3.7549, which is the row run 02 failed. The revision-3
fix is confirmed by a candidate dispatched after it.

`reference_surface_distance_p99_mm` failed at 0.3849 against 0.300, and the residual is
one feature. Every height band from the plate to 18.2 mm reads median 0.0000 and p99 at
or under 0.0227; all 282 samples beyond the band (1.07 %) sit between z = 18.2 and 21.0
with |x| ≤ 0.95 mm, and the worst is exactly 2.800 = 21.0 − 18.2. Measured on both
solids: the interior ring count drops from two to one at 18.25 on the candidate and at
21.00 on the reference, while the opening at every height between them is identical to
three decimals. **It is the divider's top height, and the request does not determine
it** — the brief gives the divider's existence, axis and 1.2 mm thickness, and no cited
figure touches its height.

The candidate's own argument for stopping at 18.2 was checked and partly corrected: a
second copy of the reference seated on the reference interferes by 0.001 mm³ at a
20.65 mm lift and 19.438 mm³ at 20.60, so 20.65 is the seat — but the reference's own
divider reaches 20.95 and still does not foul, because the upper bin's feet are 0.5 mm
apart there and the divider passes between them. Any divider from 18.2 to the lip tip
is functionally sound.

**Left open on purpose.** This is run 02's defect class in a fourth place, but the three
repairs available — exclude the divider geometrically, demote the distance row to a
diagnostic (which the ruling permits), or have the requester state a divider height
(which has no published source) — are not equivalent and change what F1 measures. The
reviewer ruled once on this axis; the choice goes back rather than being taken while
looking at a failing candidate. Nothing in revision 3 was changed by this run.

### Changed — F1's first revision-2 run found a defect in revision 2 (revision 3)

The fresh candidate scored `CAD_FAIL / 3MF_PASS` on one row, `outer_corner_radius_mm`
at 6.7724 against 3.75 ± 0.2 — **and the failure was the fixture's.** Measured: that
candidate's outer corner radius is 3.7528 at every height from 6.9 mm upward, which is
the reference's own figure to four decimals. At the 6.0 mm probe height its section was
still two feet growing into one body, and the area-deficit formula assumes a rounded
rectangle.

The publication gives the base one height unit *including the structure tying the feet
together* and gives the profile 4.75 mm of it, so the feet finish becoming a body
somewhere in the 2.25 mm between — and nothing says where. The reference spends 0.25 mm
of it; the candidate spends all of it, and not by whim: the published 83.5 × 41.5 body
overhangs the two published 41.5 mm feet by about 30 mm² of flat ceiling, and the brief
asks for no supports. **The published geometry requires a designer to invent a
transition the publication does not specify.**

Revision 2 judged that span twice. The corner radius is now read 5.0 mm above the
published base height instead of at a fixed 6.0, and the hard distance masks
4.75–7.0 mm on the same rule as its other two masked ranges — bucketed by height, that
span was the *whole* of the run's disagreement (p99 1.2280 there, 0.0000 in every band
above it). Two mutations added, one per change; 32 in the manifest.

This is the same class of defect the reviewer's ruling named, found one layer deeper
than revision 2 looked. Run 02 is preserved as revision-2 evidence: not re-scored, not
presented as proof of revision 3, and revision 3 was not tuned to it — both new bounds
are arithmetic on published numbers and would be the right bounds if that candidate had
never run.

### Changed — F1 becomes a standard-conformance fixture (revision 2)

The reviewer's ruling on run 01: F1's truth model was stronger than its request. The
manifest said the standard fixes the answer and therefore hard acceptance may use
registered surface similarity, while the request deliberately withheld the base and lip
profile — and the live run then failed the hard surface-distance row *entirely* on those
withheld surfaces. Useful discovery evidence; not a fair reusable benchmark. The ruling
also refused the other repair: **do not perturb the 42 mm pitch**, because F1 was chosen
as a real standard-driven fixture and not an anti-memory synthetic task.

So the request now states the load-bearing interface, from a public source, with
provenance: `src/core/standard.scad` of
[`kennetek/gridfinity-rebuilt-openscad`](https://github.com/kennetek/gridfinity-rebuilt-openscad)
at `bed60a4`, which names <https://gridfinity.xyz/specification/> as its own source for
the base and stacking-lip constants, corroborated by
[`gridfinity-unofficial/specification`](https://github.com/gridfinity-unofficial/specification).
The primary page itself was opened and does **not** carry the profile figures in text —
recorded in the fixture, because a citation nobody opened is this repository's most
common defect. The figures taken: pitch 42, widest section 41.5 per unit leaving a
0.5 mm gap, corner radius 7.5/2, base profile 0.8 / 1.8 / 2.15 at 45° for a 4.75 mm rise
and 2.95 mm run, base height 7 including the structure tying the feet together, stacking
lip 0.7 / 1.8 / 1.9 from its inner tip with a depth of 2.6 and a height of 4.4 over a
1.2 mm support, and the height unit excluding the lip.

**Six new hard predicates**, each measuring a stated figure against a stated 0.2 mm
tolerance rather than a similarity band: `base_plug_profile_mm`, `base_feet`,
`outer_corner_radius_mm`, `compartment_floor_height_mm`, `stack_lip_depth_mm` and
`stack_lip_seat_height_mm`. `base_feet` exists because the published profile is stated
*per grid unit* — a two-cell bin stands on two feet with the published gap between them,
and one plinth of the same outline has the same bounding box at every height, so no span
can tell them apart. Both footprint rows changed from a range on the undersize to the
published figure, and the height band narrowed from 21–28 mm to 23.5–25.4 mm, both ends
computed from published numbers.

**The hard distance now judges only what the request determines.** Registration seats
both solids on their own base plane and footprint centre instead of centring bounding
boxes, because the publication cannot fix the overall height and a centroid fit would
spread half that legitimate difference over every surface. Two ranges are masked out of
the p99 row and reported as a diagnostic instead: the internal floor transition, where
the same public file offers a 2.8 mm fillet radius and the reference uses 1.1; and
everything above the lip's published land, where the final 1.9 mm chamfer would leave the
rim a knife edge at a 1.0 mm wall and every implementation truncates it by an amount the
publication does not state. Measured: an independent implementation of the same published
figures scores p99 = 0.0018 mm masked and 0.300 mm — exactly on the band — unmasked.

Reference conformance was measured before any of this was frozen, and it is not uniform:
the reference agrees with the publication on the footprint, all three base segments, the
corner radius (3.7528 by area deficit, 3.7500 by corner distance, against a published
3.75), the floor height, the lip depth, the lip seat height and the lip's first two
segments — and *disagrees* on the final chamfer, 1.3 against 1.9. The disagreement is
reported rather than reconciled, and it is what the mask removes.

Run 01 is preserved as revision-1 discovery evidence. It was not re-scored, it is not
evidence about revision 2, and revision 2 was not tuned to it: the two figures that
candidate got wrong — a 2.4 mm capture ramp and a 4.0 mm corner radius — are wrong
against the public source, and both are now mutation probes.

Thirty mutations, all killed. Also fixed on the way: the scorer ignored the
`probe_samples` the fixture declared, and the masked row and its unmasked diagnostic now
come from one sampling pass rather than two — which halves the dominant harness cost and
makes it impossible for the two to disagree about the same pair of solids.

### Added — F1's live end-to-end arm, and the first real run through it

Slice A of [`docs/agents/qa-e2e-implementation.md`](docs/agents/qa-e2e-implementation.md):
the minimum needed to materialise the grid-bin request, run the real design path, gate
what comes back, and say so in one report. F1 only. No interface framework, no scorer
generalisation, no new dependency.

`tools/e2e.py` decides twelve hard CAD predicates and four 3MF ones. Ten of the CAD
rows are measured off horizontal cross-sections rather than a CAD feature tree — the
compartment count is the number of interior rings, the divider axis is the
disjointness of the two cavity footprints, a stacking lip is an opening that narrows
near the rim, and "no scoops and no label flange" is one statement, that the
compartment is prismatic. The other two are the registered comparison: bidirectional
sampled surface distance, with a pose set of the **24 proper rotations of a cuboid**,
so no reflection is available to the fitter.

**The bands are calibrated from same-geometry noise, not chosen.** 0.3 mm is 2.6× the
coarsest measured re-tessellation p99 (0.1135 mm at 860 faces) and 2.8× below the
smallest real defect measured (0.835 mm for a two percent single-axis scale); the 3MF
band of 0.001 mm is 30× the measured round trip. The calibration caught its own first
attempt: OCCT reuses an existing triangulation, so three deflections returned one
identical mesh until `BRepTools.Clean_s` was added — a measurement of nothing, reading
as zero noise.

**Two states, not one.** `tools/f1_candidate.py` is a compliant bin this benchmark
wrote; `benchmarks/heavy/test_e2e_f1_heavy.py` puts the hidden reference — 21 120
faces from a pinned third-party generator — through the same ten predicates, and it
passes all of them. Twenty mutations in
`benchmarks/mutations/e2e-f1-gridbin.json`, all killed: six of the brief's seven
probes as candidate mutations, and the seventh as a reflection-guard mutation because
this bin is achiral — measured, the mirrored reference registers back at
p99 = 4.4e-11 mm.

**The requester-side prohibition is structural.** `audit_request` runs
`corpus.numbers_in` and `corpus.coincidences` over the materialised request package,
so a reference measurement that reached the brief is a hard failure rather than a
review finding. One coincidence is declared with its public source: the published
42 mm pitch states the short footprint to within 1.2%.

**The first real run: `CAD_FAIL / 3MF_PASS`, and the fixture learned more than the
designer did.** Eleven of twelve CAD rows passed; the surface distance failed at
p99 = 2.300 mm. Bucketed by height, the compartment walls and divider sit at a median
of 0.000 mm and every sample beyond 1 mm is below z = 21 — the parts the brief
dimensioned agree, and the base profile, floor height and lip profile, which it
withholds, are the whole of the failure. The finding that matters is worse than a
failed row: measured at 0.05 mm steps, the blind candidate's base plug matches the
reference's chamfer height, land height, segment count and 45° angle, differing only
in the capture ramp. 42 mm identifies the standard, so **F1 as built cannot separate
recall from derivation**, and withholding more cannot fix it — the repairs are a
fixture change, recorded in the fixture's own `run_findings`.

Harness overhead is reported apart from the design path and never summed: 18.77 s
against 1711 s, so 1.1% of the run, four fifths of it in one surface-distance call.

Two known defects reproduced on the way. `trimesh` cannot read a 3MF without `lxml`,
which is not in the default install, so `make_3mf.py`'s round-trip verification has
never run here (**D3**) — `e2e.read_three_mf` parses the archive with the standard
library instead, and walks build items through their components so a body hidden as a
second component is counted. And `make_3mf.py`'s `%.6g` vertices (**D2**) are now
quantified: p99 3.27e-05 mm, volume delta 0.0013 mm³.

L0 grew by 38 tests to 1299 collected, against a ceiling of 1440; revision 2 added a
further 18, to 1317.

### Fixed — a JSON `null` unit became the string `"None"` and passed the check against it (D33)

The rule that requires a unit tests `if not str(self.unit).strip()`. The loader read
units as `str(row.get("unit", default))`, and `str(None)` is the four-character
string `None` — not empty. So a datum or requirement written with `"unit": null`
arrived carrying a unit of `None` and satisfied the very check whose own message says
a number with no unit is a number two readers can read differently. A unitless
measurement then travelled through a field that drives design, wearing a unit; on the
datum row that number is also bound into the acceptance contract by D31, so it
reached the contract looking real. Reproduced through the production loader before
the fix rather than by constructing a row: `from_payload` returned `unit='None'` with
no finding about the unit.

**The sibling was live too.** D33's own text asked whether the same coercion on
neighbouring fields was in scope, and it is: `Requirement.unit` took
`str(row.get("unit", "mm"))` at the same loader, so a requirement's null unit became
`"None"` by the identical route.

`_unit()` now separates the two rows that mean different things. A key that is
**absent** means *use the default* and still does — `"mm"` for a requirement, empty
for a datum, which keeps `problems()` raising the existing missing-unit finding. A key
that is **present and not a string** means somebody wrote a unit and it is not one,
and that is a `SchemaError` naming the field. Refusing the absent case as well would
have broken every project that never mentioned a unit, which is why the defaults are
asserted by the same test rather than trusted: the fixture failed on five refusal
cases while the three default and verbatim cases passed, and a fix that over-refused
would have satisfied the refusals and broken the defaults in silence.

Deliberately not done, so the scope is legible later: no unit vocabulary, no
conversion, no normalisation, and the literal string `"None"` — which somebody can
still type — is left alone rather than made a second issue. No schema bump, no
rebinding of D31's contract payload, no golden re-recorded.

Both strict loader edges are mutation-proven by reverting each to the exact coercion
it replaced: 2 attempted, 2 killed, 0 survived.


### Fixed — a scope recorded which datums it depended on, not what they said (D31)

ADR 0003 decision 5 says a datum is a dependency binding: changing one produces a
new revision and invalidates the results that depended on it. Only the near half
had landed. `cli._preservation_feature` carried `datum_ids` into the frozen
contract, so re-placing an edit against a different reference moved
`contract_sha256`, but `_requirement_hash` built its payload from six keys and
`project.datums` was not among them — so correcting a referenced datum's value
while keeping its id left the contract byte-identical and a review answer written
against the old number stayed current. Measured before the fix, 12.4 → 12.9, same
id: the identical hash `4149de15…b712` twice.

`_referenced_datums` now binds `Datum.as_dict()` verbatim for exactly the datums
some edit scope names — one entry per identity, sorted by `datum_id` — under a key
that is absent when nothing references one. Only referenced datums participate
(§13.4), and two scopes sharing one datum bind one entry, which is decision 4 held
in the serialization rather than in prose. The contents deliberately do not go on
each preservation row: that would write one datum's number twice into one
contract, which is the two-authorities failure the ADR was written from. `note`,
`owner` and `settled_by` are bound with everything else because the row is the
model's own serialization, asserted by equality against `as_dict()` — a
hand-maintained field list would drop whichever field is added next.

The precise claim: **the contract binds `Datum.as_dict()` verbatim, and
`Datum.as_dict()` canonicalizes the order of the set-valued `valid_for` field.**
Datum values, units, provenance and D33's malformed-input behaviour are **not**
normalized. `valid_for` is sorted because `Project.validate` reads it as a
membership set — `set(datum.valid_for) & ({scope.artifact_id} | set(scope.interface_ids))`
— so two declarations differing only in the order of the same scopes are one
declaration, and identity was distinguishing a state the model does not: `("src",
"drawer")` hashed `50db5e53…` against `("drawer", "src")`'s `0a239014…`, cutting a
spurious acceptance revision. Canonicalized in `as_dict` rather than in the binding,
so the bound row stays the model's own serialization and the equality assertion
above keeps its force. One consequence: a project saved and reloaded gets
`valid_for` back sorted, so the round-trip fixture asserts the set survives rather
than the tuple order. Nothing else is touched — a datum declared `"unit": null`
arrives as the string `"None"` (D33) and is bound as `"None"`, since whether
identity follows the object the system accepted is a different question from whether
the loader built the right object. The unit regression uses `mm → cm` and depends on
neither.

`datum_ids` is sorted in the contract row — a set of references to declared
identities is not a precedence — and never deduplicated, because a repeated id is
a declaration `Project.validate` owns. `project.json` order is untouched. The
acceptance schema version is unchanged: the block exists only in the *input* to
`requirement_sha256`, so `acceptance_contract.json` keeps the same top-level
fields and stores only the resulting digest.

Driven end to end rather than composed: correcting the datum cuts revision 2, the
history's `changed` list holds exactly the `requirement_sha256` move and nothing
else, four receipts bound to revision 1 are invalidated and removed, and the
stored answer is refused with *"review envelope mismatch"*. No golden moved —
selftest 11/11 pins the five certified contracts by hash and all four replay
goldens pass unmodified.

The `EXPERIMENTAL_UNAVAILABLE` cap is untouched and still asserted; this makes the
binding correct and lifts nothing. ADR 0003 decision 6 remains open.

One mutation survived the first sweep and is the most useful thing in the slice.
Removing `sorted()` from the canonical block passed all fourteen fixtures, because
the referenced ids are collected into a *set*: the set had already discarded
declaration order, so two projects differing only in that order iterate
identically inside one process, and every reordering fixture compares two projects
in one interpreter. What none could see is that set iteration order is a function
of `PYTHONHASHSEED` — unsorted, one project serializes differently in two
interpreters, ending byte-identical reruns and clean-clone reproduction, which are
claims about *different processes*. Closed by an L0 order assertion and a heavy
fixture that runs the project in two children with seeds 0 and 1 and requires both
the order and the digest to match.

### Fixed — the seccomp syscall number was x86-64's, on a module that supports arm64

`confine_posix` names `aarch64` as supported and carried one `NR_seccomp = 317`.
That is the x86-64 number; arm64 takes the asm-generic 277. The consequence was
not subtle: `unavailable_reason()` probes the number, an arm64 kernel answers
`ENOSYS` for 317, the probe concludes seccomp is absent, and the boundary
refuses on every arm64 machine — safe, and still wrong. Now keyed by the same
`_ARCH` token as `_EXEC_SYSCALLS`, so a machine this module claims to support
has an entry in both tables or in neither, and an unknown machine yields no
number rather than a guess. Found by review, not by a run: this repository has
no arm64 machine, so the tests are arithmetic on the tables and say so.


### Fixed — a recorded path is parsed as it was written, not as the host would write it

The thirteen L0 tests that failed on Linux were one defect in two places, not a
platform exception: `Path` was the authority, and `Path` is whichever host is
reading. `ExternalFile.name` returned the whole recorded string on Linux and a
parent of `"."`, so the public record published a full Windows path through
`SourceRef.name` and three wall tests searched every fixture's prose for `"."`.
`conftest._executable_name` had the same shape, which left `git` — the one
program L0 may start — unrecognisable when the event carried a Windows path.

One rule each, stated once and never consulting the host: Windows for a drive
letter, a UNC name or any backslash; POSIX otherwise. Both flavours are covered
from either host, and both rules are mutation-proven -- seven attempted, seven
caught. No fixture hash, evidence
classification or request/reference assertion changed. Linux L0 went from 13
failed to 0.

### Added — the authoritative pre-merge gate builds the real Linux boundary

`pre-merge` ran on a bare hosted runner as uid 1001 with no `CAP_SYS_ADMIN`, so
the confinement could not be constructed and the tier reported on nothing. It
now runs in a digest-pinned container with `--cap-add=SYS_ADMIN` and one
measured AppArmor opt-out — the first hosted run held the capability and still
failed `mount(None -> /, 0x44000)` with `EACCES`, which is AppArmor's answer and
not seccomp's, so the syscall filter was left in place rather than loosened on a
guess. A preflight prints the capability masks and `describe_confinement()`,
fails with the exact `unavailable_reason()`, and builds one real confined child
before pytest runs. Nothing is skipped or marked xfail, and the heavy suite is
not split into a green hosted half and an unrun privileged half.


### Fixed — the boundary's availability probe asked about uid, not the capability

`confine_posix.unavailable_reason()` gated on `os.geteuid() != 0` as a stand-in
for `CAP_SYS_ADMIN`. That is a different question, and it was wrong in both
directions. A root process whose bounding set omits the capability — an ordinary
container, including the `ubuntu-latest` shape this repository's own `pre-merge`
job runs in — was told the boundary was **available**, and then failed with a
bare `EPERM` out of `unshare`: exactly the raw failure this function exists to
turn into a sentence, arriving after the point where it could be reported
cleanly. In the other direction a process holding effective `CAP_SYS_ADMIN` at a
nonzero uid was refused while holding precisely what the construction needs.

**The capability is now read from the kernel**, through the same `capget` the
drop verification already used: `_capability_sets()` returns the calling
thread's effective and permitted masks, `_effective_capabilities()` is now one
line over it, and `CAP_SYS_ADMIN` has a single named constant. No new
dependency — no libcap, no `capsh`, no subprocess.

**Effective, not permitted, and never raised.** A capability that is permitted
but not effective does not authorise the `unshare`, so it is refused — and the
reason says which of the two states it found, because that is what tells an
operator whether to grant the capability or to raise it. It is reported rather
than raised into the effective set: raising it would be a privilege escalation
performed on the operator's behalf and unasked, which is the opposite of a
boundary that says what it is. A `capget` that fails is unavailability too, not
an exception to propagate — a capability that could not be read has not been
established.

Every existing probe is unchanged and still runs in the same order, before any
candidate is staged. Three tests in `benchmarks/heavy/test_confine_posix_heavy.py`
set the two identities for real in a child process rather than simulating them,
because neither state is reachable from the test process itself: a capability
dropped is not regained and a uid lowered is not raised. Both directions of the
old proxy are killed by mutation — restoring the uid check fails all three, and
accepting `permitted` in place of `effective` fails the case that separates them.


### Fixed — the one L0 case that cannot answer in this process on Linux

`ReviewEnvelopeTest.test_stale_verification_response_after_render_change_is_rejected`
was the fourteenth L0 failure on Linux, against a documented allowance of
thirteen. It failed the tier guard's **spawn** check rather than its own
assertion: it is the single case in its class asking for `render=True`, and on
Linux `preview` selects the EGL platform, PyOpenGL resolves the library through
`ctypes.util.find_library`, and that shells out to `ldconfig` — plus `gcc` and
`ld` when EGL is absent. Having EGL installed does not avoid it, because
`find_library` runs `ldconfig` to answer at all, so no Linux machine escapes it
and the case could never pass the commit gate there.

**Moved to `benchmarks/heavy/`, which is what the guard's own failure text
prescribes**, rather than widening the allowance to fourteen to accommodate a
test in the wrong tier. The Linux L0 failure set is now exactly the thirteen
Windows-assumption cases `ROADMAP.md` describes. No new regression fixture was
added because the tier guard *is* the regression test — it is what caught this,
and it still fails the same way if the case returns to the gate.

The property under test is unaffected, and that was established by mutation
rather than by watching it pass: where the renderer cannot import, `witness`
records `renderer="unavailable: ..."` with no images, which is a different
witness record from the `"none"` of a job that never asked, so the envelope
still refuses the stale answer for the reason the case names. Leaving the second
run's render flag unchanged makes that same stale answer accepted, which is the
mutation the case kills. `_good_verification` became a module-level helper so
both tiers read one fixture rather than two spellings of it.

Found by running the full gate on Linux at `8ebfb80`; the failure predates the
branch and reproduces identically at the branch point `62fe422`.

### Fixed — two columns of one design are named as one (D28)

`compare._identical_designs` grouped formulations by `bindings.current`, which
reads the source digest off disk **now**. The block exists to stop a reader
taking two identical columns for two designs independently reaching one answer
— and it was silent on the only case in the repository that exercises it. On
`benchmarks/replays/branch-knob-seat-fallback` the shared root and `as-drawn`
were built from a byte-identical `model.py`, both receipts record
`artifact_hashes.source = 1e9b9ea…` and the same candidate digest, and every
measured value the comparison prints for them agrees — but `as-drawn`'s model
was revised after its run concluded, so the key had moved and the two identical
columns were printed side by side, unnamed.

**Grouped on what the completed receipts establish**, because the columns being
compared *are* the receipts and the working tree is not among them. The key is
`final_status.artifact_hashes`: `source`, `stl`, and `step` where the job
produced one.

**Not the source digest alone, which is what the defect proposed.** One
`model.py` builds different geometry under different parameters or different
inputs, so a source-only key would group two genuinely different designs and
print the strongest sentence in that file about them. The output digest is the
half a source digest cannot carry. The converse is refused too: two different
sources that emit byte-identical STLs are two implementations, and collapsing
them would destroy a genuine independent agreement — the opposite of the error
recorded here.

**Missing digests do not form a group.** A formulation with no
`final_status.json`, or a receipt carrying no source or no candidate digest, is
one nobody completed; grouping it would state the strongest available claim
about a run with no evidence, and two such formulations would group with each
other on a pair of absences. `step` is exempt: absent is a real answer for it,
two jobs that produced none still group, and a job that exported one never
groups with a job that did not.

**Grouping is not a claim about currency and did not become one.** `as-drawn`
is still `STALE` and its mandatory verdict is still `UNKNOWN_STALE`; those come
from `bindings.broken` and `status.derive`, which this does not touch. The
group's note says so, and an L1 test asserts it.

The L1 assertion that pinned the defect is inverted — its own message named the
value it would become — and `branch-knob-seat-fallback`'s recording moves by
exactly one field, `identical_designs` from `[]` to `[[".", "as-drawn"]]`.

### Fixed — the support ceiling and the candidate are measured in one frame (D15)

D15's last half, and the one its own fix's review found. Since `5ac852e` the
*candidate's* overhang has been measured through `contract.printer_transform`.
The ceiling it is measured against was still generated in whatever frame the
template assumed, so on a `MODIFY` job declaring any reorientation the two sides
of one inequality were two frames — and before the candidate half landed they
had at least been wrong the same way.

Three places each answered the frame question separately. `cli._print_plan`
called `designer_toolkit.plan.direct_template` without the project's
orientation, and `direct_template` wrote `IDENTITY_TRANSFORM` into its one
support rule whatever the job had declared. `cli._plan_features` copied that
rule's `downward_normal_z_max` and `bed_z_mm` into the contract row and dropped
its `model_to_printer_matrix`, so the contract's orientation silently stood in
for a declaration another artifact had made and nothing checked they agreed.
And `cli._inherited_overhang` called `metrics.overhang_area` with no
`transform=` at all, though that function documents the parameter for exactly
this.

**One authority chain, not a fourth transform reader.** `project.orientation` is
the declaration. It reached the acceptance contract already; it now reaches the
generated plan; the plan rule's copy travels into the contract feature row, so a
frozen contract records which frame each ceiling was measured in; and
`contract.preflight` refuses the run when the row and the orientation disagree
about the matrix or the bed height, before any geometry is paid for and without
preferring either declaration. Inherited overhang is measured under
`printer @ alignment` — each source placed out of its own coordinates into the
job's frame and then into the printer's. `contract.as_transform` is the single
resolution all of them use, which is why `"identity"` and the 4×4 identity are
one declaration in two spellings rather than a refusal.

A frame that cannot be resolved makes that source a **named gap**, never a
silent identity: crediting an allowance measured somewhere the source does not
sit fails in the direction that passes a bad part. D18's controlled partial
ceiling is unchanged, and a fixture pins that.

Identity orientation emits byte-identical plans, so no recorded
`print_plan_sha256` moved and the L1 replays passed unrecorded. The composition
fixture is a non-commuting pair — the alignment turns about Z and translates,
the printer turns about X — over a stepped source chosen because the five
candidate mutations land on five distinct areas: the composition 100.0 mm²,
the reversed product 0.0 mm², the alignment alone, the printer alone and no
transform at all 300.0 mm² each. All five are mutation-tested in
`test_orientation_ceiling.py`.

### Added — Release 3's context-budget foundation: what a job cost, and what it was allowed to cost

`MISSION.md` makes efficiency a first-class objective and `ARCHITECTURE.md` 15.6
lists the eight things that have to be visible before any of it can be held to.
The build measured one of them — `JobResult.llm_calls`, printed to stderr and
written down nowhere — and `docs/baseline.md` held four wall-clock figures a
person had taken by hand. You cannot hold a budget you do not measure.

**`cost.json`, per formulation, one entry per invocation.** `pipeline/cost.py`
writes it beside the receipts, and it is a *journal* rather than a snapshot for
one reason: a review round trip is three invocations of `design-tool run`, each
of which rebuilds the geometry from scratch, and a file describing only the last
one reports a third of what the job spent. It is bound by nothing, for
`lifecycle.json`'s reason — no receipt carries its digest, `bindings.RECEIPTS`
does not name it, and appending to it cannot make anything stale. A rerun on
unchanged inputs still moves no receipt and no run identity; what it moves is
this file, which is the honest record that the rerun happened and cost something.

Seven of the eight are recorded: dispatch count, context size, deterministic
runtime, cache reuse, repeated work, failed work, per-alternative incremental
cost. **Import cost is deliberately not decomposed** — separating a fresh
interpreter's `import trimesh` from the build inside it needs an import hook in
the confined child, which is machinery nothing has asked for and which
`docs/baseline.md` already decomposes by hand. What is recorded instead is
`warm_kernel`, one `sys.modules` lookup, which says which regime a measurement
was taken in: the same certified job is 0.18 s warm and 3.36 s cold.

**Two things the existing counter had wrong, now visible.** `llm_calls` is
reused rather than replaced — one counter, not two — and measuring around it
found both. It never counted the **designer commission**: `AGENT_COMMISSION` is
written by `cli.py` and returns before the runner is reached, `tools/replay.py`
already called it "the live dispatch on the `CUSTOM` lane", and the "1 llm call"
`docs/baseline.md` prices the `CUSTOM` riser at is that commission, counted by a
person. And summed across a resumable job it over-counts: the invocation that
finishes a job re-reads every answer written for it and increments again, so the
recorded `modify-ball-flange-flat` replay reports `llm_calls` 0, 1, 2 for two
questions ever asked. The ledger counts the question at the pause that wrote the
packet and records the re-reads as `reviews_reused`.

**Per-alternative incremental cost**, which `ARCHITECTURE.md` 15.2 asks for and
the vent-ball branch exercise had to take with a stopwatch. On the recorded
three-formulation `berlingo-knob` replay each sibling costs one dispatch, 23.8 kB
of context, ~2.9 s and two builds; the project pays six builds and three
dispatches; and `as-drawn`, which builds a candidate **byte-identical to its
parent's**, costs 2.91 s against the parent's 2.96 s. What is shared is intent,
and intent is free. The two mechanisms that could make that untrue are reported
separately because they are zero for different reasons: `builds_avoided` is
*measured* and is zero because the content cache is consulted **after**
`backend.build` returns — a hit confirms the bytes and saves nothing — and
`reviews_from_a_sibling` is zero *by construction*, because the review envelope
carries `alternative_id`.

**A budget that is declared and checked.** `cost.budget(plan)` is what one
invocation of a compiled plan may dispatch, derived from the plan and nothing
else; `runner.run` refuses a run that spends past it with stage `cost`, because a
dispatch the plan did not name is work done outside the plan and that is the
authority gate rather than a cost footnote. The per-route numbers are frozen in
`pipeline/cost.py` — in the shipped module, imported by the test, the way
`selftest.FROZEN_CONTRACTS` freezes a certified contract — so `ROADMAP.md` 3.4's
"no release may add an AI round trip to an existing path as an accidental side
effect" fails a test instead of going unnoticed.

Read by `design-tool status --json` under `cost`, by the terminal summary after
every run, and by the budget check itself. 23 gating fixtures, four in
`benchmarks/heavy` for the costs only the confined boundary has, two L1
assertions on recorded jobs, and eight mutations of the protections — the
ceiling, the counter, the commission, the journal, the build count, the cache
status, the incremental figure — each shown to turn a passing fixture red.

Not built, deliberately: context **packages**. Task-specific context assembly is
`ARCHITECTURE.md` 10 and nothing has asked for one; building it now would be the
broad unfinished framework 3.1 forbids. This is the measurement and the budget.

### Added — Release 3's lifecycle group: run identity, resume versus restart, seven honoured dispositions

Three items that belong together: what a run *is*, what continuing one means, and
what a formulation's declared state changes.

**Run identity, decided rather than deferred.** A previous scoping pass parked
this item with an argument worth engaging: the command surface is built so a
rerun on unchanged inputs is byte-identical — `--updated-utc` is required from
the caller for exactly that — so an invocation counter ends the property by
construction, and a content-derived id "is a hash that already exists". The first
half is right; the second is not. The identity is now
`pipeline.bindings.identity`, a SHA-256 over the *whole* binding map, and the last
entry in that map is which formulation this is. Two formulations are
byte-identical at the instant one is branched from the other — same contract
hash, same artifact digests, same plan — and no digest already in the build can
tell them apart. This one can, and a rerun on unchanged inputs still moves
nothing. `design-tool status --json` reports it as `run_id`; `next_action.json`'s
`state_sha256` is the same function, because an instruction and a receipt go
stale for the same reasons. No receipt gained a field, so no frozen contract hash
moved. The argument, the rejected alternatives and what it deliberately does not
decide are in [ADR 0004](docs/adr/0004-run-identity-is-content-derived.md).

**`--resume` and `--restart`.** Resume is what a bare `run` already did. The flag
asserts the precondition the default assumes — that something here has concluded
— and refuses with exit 2 when nothing has, rather than starting from scratch
under a word that promised otherwise.

Restart is the one that needed deciding, because invalidation is already scoped.
"Delete everything and start again" would discard the frozen acceptance contract
(cutting a spurious revision on the next run), the content cache (re-paying for
geometry still valid by content), the proposal and the model (inputs, not
conclusions) and — if scoped to the project rather than the formulation — every
sibling, which §13.5 forbids. So restart is scoped twice: to **one formulation**,
and to that formulation's **conclusions**. It removes the six removable receipts,
the review *answers* (not the packets, which are the questions) and
`next_action.json`; it keeps everything those were concluded from. What it buys
that resume cannot is the one case scoped invalidation is blind to by
construction: **a conclusion whose bindings all still hold and that somebody no
longer trusts**. A `PASS` answered against unmoved evidence is reused by resume
forever, correctly; restart is the only way to ask again.

**`lifecycle.json`.** Append-only at the project root, bound by nothing — no
receipt carries its digest and `bindings.RECEIPTS` does not name it, so writing
to it cannot make anything stale. It holds the two things that are decisions
rather than derivations: a restart with the digest and stored verdict of
everything it discarded, and every disposition transition. `bindings.invalidate`
already had the rule that a superseded pass must be "neither current nor erased"
and kept it by printing digests to stderr, where nothing can read them ten
minutes later. This is where they live now.

**All seven dispositions honoured, each changing something.** Previously two were
honoured and five were stored and read by nothing — the shape this repository
removed from `candidate_strategy` and `project_hash`. Rather than deleting five
states ARCHITECTURE.md §14.6 names, each was given behaviour:

* `PREFERRED` — **at most one per project**, refused otherwise, because two are
  two answers to what the job's design is. Switching demotes the previous holder
  to `ACTIVE` and journals both halves (§13.3: the previous preferred is not
  erased). This closes a declared proof.
* `FALLBACK` — **runnable**, which is the point. The vent-ball replay had to
  record a genuinely retained fallback as `ACTIVE` because a build that would not
  run one gives "retained" and "abandoned" the same behaviour. `design-tool
  status` names it as the option to fall back on exactly when the current
  formulation has no claim.
* `PAUSED` — not runnable, and its `next_action.json` is **kept**, because that
  is what to do on resuming. Resuming is a recorded transition, not a silent
  activation. `PAUSED` could previously be stored and never left; this closes the
  second declared proof.
* `REJECTED`, `SUPERSEDED`, `MERGED` — concluded. Their `next_action.json` is
  **cleared** (a formulation nobody will pick up is waiting for nothing) and
  every receipt is kept (§13.1: a rejection is evidence). The last two must name
  the declared formulation that replaced them, and `MERGED` is **refused unless
  that formulation's `parents` record the merge** — this build performs no
  merges, so the state cannot be claimed ahead of the graph that would justify
  it.

Every state but `ACTIVE` must carry a `basis` from a closed vocabulary, which
§14.6 always required and nothing enforced. A disposition that only labels is the
defect it was meant to fix with a nicer name.

Reached through `design-tool branch --disposition <state> [--of <id>] --basis
<basis> [--superseded-by <id>]`, which is not combined with creating a branch or
with `--activate`, validates the whole project before writing, and moves the
project off a formulation it has just made non-runnable.

**Cost and proof.** L0 43 s → **45 s** (838 → 869 tests, 458 → 477 subtests);
L1 unchanged at **62 s** against a 120 s budget; L0-heavy **889 s** over 353
tests, three of them the end-to-end restart cases this adds. `selftest` 11/11. `project.json` is byte-identical for any row
that carries no basis, so nothing in the corpus moved and no golden was re-pinned.
Every behaviour above has a fixture that fails when its protection is mutated:
**18 mutations, 18 caught** — an identity that mixes in a counter, a map that
drops the formulation, a restart that takes the inputs, one that keeps the review
answers, one scoped to the project, a resume that never refuses, a journal that
binds, a damaged journal overwritten, `FALLBACK` demoted to unrunnable, the basis
requirement, the single-`PREFERRED` rule, the `MERGED` graph check, the successor
rules, the demotion, the instruction clearing, the active-formulation move, a
refused transition that writes anyway, and a fallback that is never named.

### Changed — a commit gate that is one: 997 s to 43 s, with nothing dropped

`ROADMAP.md` section 5.1 puts L0 on every commit and section 4.4 budgeted it at
about five seconds. There was no L0 tier. There was one undifferentiated `pytest`
run costing **997 s**, and a ladder that existed in a document and nowhere else.

**Measured before deciding.** `--durations=0` plus a `sys.addaudithook` counting
process creation per test, over all 1163 tests: **194 of them started a child
interpreter and held 876 s of the 1020 s measured**, at about 1.6 s each, because
a fresh interpreter that reaches `import trimesh` costs that on this machine. The
other 969 cost 143 s together and nearly all are under 0.2 s. Not a long tail —
one mechanism. The full profile is in `docs/baseline.md` and
`benchmarks/heavy/README.md`.

**Cut at that seam.** `benchmarks/heavy/` now holds the two command surfaces, the
confined build boundary, the packaging and bundle smokes, the screening corpus
and the B-rep reads: 343 tests moved, 820 stayed, and 820 + 343 is the 1163 that
were there. Every moved class is byte-identical to the original apart from
`from . import x` becoming `from pipeline import x` and three constants that used
to be found through a `__file__` that has moved. Nothing was deleted and no
assertion was weakened; the subtest counts add up the same way, 458 + 190 = 648.

* L0 — `uv run pytest`, 838 tests, **43 s**, every push.
* L0-heavy — `uv run pytest benchmarks/heavy`, 350 tests, ~16 min, pull requests.
* L1 — `uv run pytest benchmarks/replays`, 55 tests, 68 s, pull requests.

**Structural, and then measured.** Which tier collects a file is decided by where
the file is, the same lever that made L1 real: `testpaths` names
`skills/3d-modeling/scripts` and `tools`, and neither benchmark directory is in
either. Whether a file *belongs* there is not left to that, because a decorator
is one forgotten line away from a test silently leaving its tier: the root
`conftest.py` fails any L0 test that starts a child process — `git` excepted, one
name, measured at ~45 ms a call — or that exceeds five seconds, and names
`benchmarks/heavy/` in the message. The default is the gating tier, so forgetting
costs a red test rather than lost coverage. `tools/test_tiers.py` tests the
decision as a function and `benchmarks/heavy/test_tiers_heavy.py` shows it going
red in a real pytest session over a test that really starts an interpreter — and
that proof costs an interpreter, so it lives where its own rule puts it.

The guard found two things the profile had not: a class whose reparse-point
fixtures shell out to make a junction, and `ShippedSelftestTest`, which was 1 s
only because another class in the same file had already paid the build123d cold
import and became 12 s once that class left. Both moved.

**The five-second budget is amended to a minute**, in section 4.4, with the
argument: collection alone is 2.5 s, the cheapest confined job run is 1.6 s, and
the 838 tests that remain average 50 ms. Five was reachable only by protecting
nothing. What the heavy half costs is not forgiven by moving it — 16 minutes is a
real number and bringing it down is real work this does not do.

**CI matches the triggers section 5.1 states.** `on: push` no longer filters to
`main`, because a filter that only fires after merge gates nothing at the moment
a gate could have stopped something. The gate step carries a three-minute
timeout, so the budget is enforced rather than recorded. The heavy tier runs
before the replays in the pull-request job; `tools/test_tiers.py` goes red if CI
stops naming it, because a tier nobody runs reports all clear.

### Added — the three slices Release 3 shipped, replayed as jobs

The harness below landed with two cases, a `CUSTOM` job and a `MODIFY` job, and
neither exercised what Release 3 actually shipped: branching and sibling
isolation, derived status and `STALE`, superseded instructions and structured
findings. Section 4.3 was therefore met for that release by the lane the harness
was built on rather than by the release's own work, and 4.5 was partial for the
same reason. Two cases close it, and the harness gained exactly what they needed
and no more.

**The work directory, resolved instead of refused.** The harness used to refuse
any case declaring an `active_alternative`, because every path it joined was
relative to the project root while a branch keeps its receipts under
`alternatives/<id>/`. `tools/replay.py` now reads `project.json` before every
step and joins against the formulation that is active — `design-tool branch`
moves that answer mid-play, so a resolver that cached it would read one
formulation's receipts as another's. It is a second implementation of
`Project.work_dir` on purpose: a harness that asked the system under test where
to look could not catch the system looking in the wrong place, and
`tools/test_replay.py` asserts the two agree and that the two constants the copy
rests on are the pipeline's own. What it still refuses is an `active_alternative`
that is not a plain `[a-z0-9-]+` id — `branch` cannot write one, a hand-edited
project can, and resolving it to the root would compare the wrong directory and
report a pass.

* **`branch-knob-seat-fallback`** — three formulations of one job on the vendored
  `berlingo-knob` request, forked on that request's *own* recorded uncertainty:
  the base-plate height is a photo estimate its notes give as ±2 mm, so the
  shared root is the sleeve as drawn, `plate-seated` trusts the estimate and
  spends the whole 52 mm envelope on it, and `as-drawn` carries the ancestor
  forward unchanged as the fallback. Each freezes acceptance revision 1 and
  supersedes nothing, so neither sibling cuts a revision from the other; one
  builds a materially different solid and one builds a byte-identical one. That
  second pair is what makes the case say anything: their review envelopes differ
  in `alternative_id` and in the plan digest, the plans differ in
  `alternative_id` and nothing else, and stripping that one field makes the two
  reviews one review — so the PASS written for the ancestor settles the
  fallback's. Protocol 4 refuses it, and the suite shows the refusal end to end.
  Then the fallback's model is revised *after* its run concluded, and its stored
  `VERIFIED` derives `STALE` while both siblings stay current. 31 s including the
  adversarial replay.
* **`modify-ball-scope-refused`** — the same real `MODIFY` job as below, with the
  edit scope as somebody first wrote it: the region box's two y values
  transposed, and an `interface_ids` naming an interface nothing declares. Both
  commands stop at 2, nothing is frozen and nothing is built, and what is left is
  `next_action.json` kind `FIX_PROJECT` carrying slice C's structured findings —
  `SCHEMA_RANGE@edit_scopes[0].region_box.y` and
  `REF_UNDECLARED@edit_scopes[0].interface_ids[0]`, two codes from two groups,
  each with a `where` that is a position in the file rather than the noun the
  sentence uses. The refusal path had no L1 coverage at all, and it is half of
  the functional gate. Two seconds.

**Derived status is computed and is still binding.** Everything else a replay
compares is read off a file the run wrote; `status.derive` is computed on demand
from the bindings on disk, and `STALE` exists nowhere else. It goes in the
binding layer under the rule that was already there — it is an answer the system
gives, not prose, `design-tool status` returns a different exit code for each
value, and `derive` re-adjudicates nothing and reads no clock, so two replays of
one recording agree or something is wrong. The *reasons* under it are prose and
stay advisory; the `stale` map's keys are a shape and bind, and its sentences,
which quote two truncated digests, are recorded nowhere.

**What a case may now declare, and what it costs a case that does not.** A case
may list `formulations` and must say whether it `concludes` `BUILT` or `REFUSED`;
`inputs/` and a new `revisions/` mirror the project tree, and `judgements/` is
indexed by formulation and kind. A case that declares no formulations issues no
`branch` command and produces the recording it produced before any of this
existed — which is why `custom-knob-sleeve` and `modify-ball-flange-flat` are
still frozen at `4442921d` and did not move. `revisions/` exists for one property
nothing else reaches: an input revised *after* a formulation settles is the only
way a stored verdict can be read against evidence that has since moved, because
an input revised before it would simply be the input the run used.

L1 is now 68 s of a two-minute budget over four cases; the commit-gating suite is
unchanged at about 994 s. Seven mutations were run against the new protections —
each harness resolver, the pipeline's work directory, the alternative id on the
envelope *and* on the plan, `CLAIMS_SUCCESS`, the finding's axis-qualified field
path, the revision's ordering, and the copied constant — and every one turns a
green fixture red. The third is worth quoting: with `alternative_id` off both the
envelope and the plan, the fallback's run exits 0 instead of 1. The false pass is
reachable, and this is the fixture that says so.

### Added — a recorded job, replayed, with nothing asked of a model

`ROADMAP.md` section 5.1 defines three benchmark tiers and this repository
shipped three releases with two of them. L0 is the unit suite and
`tools/test_diagnosis_l0.py`. L2 is blind live evaluation, deliberately manual.
**L1 — a recorded engineering output replayed through the current system with no
live AI call — did not exist**, and section 4.3 asks for at least one of every
release. `test_diagnosis_l0.py` replays five artifacts through `diagnose`, which
is one component; `pipeline/test_frozen.py` calls `runner.run` on parameters a
test made up, which is the runner without the command surface, without a project,
without a proposal, without the confined build and without a review round trip.
Nothing replayed a *job*.

`tools/replay.py` does. It materialises a recorded case into a fresh directory,
runs `design-tool route` and then `design-tool run` until the job settles, and
compares what came out against `expected.json`. `benchmarks/replays/` held two
cases when this landed, which is the number two real lanes needed and not one
more:

* **`custom-knob-sleeve`** — an authored `CUSTOM` job against the vendored
  `berlingo-knob` request. Proposal, acceptance freeze at revision 1, the
  confined build, ten commissioning checks, the broad screen and the status
  decision. No review at all, so its dispatch count is zero by construction. Two
  seconds.
* **`modify-ball-flange-flat`** — a `MODIFY` job over `ball_male_17mm.stl`, the
  real 17 mm ball the `vent-ball-combine-r1` exercise consumed, resolved through
  `tools/fixtures.py` so its size and SHA-256 are checked before the job sees it.
  A declared edit scope, a preservation row inside the frozen contract, and a
  two-review round trip that pauses for safety, pauses for verification and
  finishes — preservation, the acceptance revision and the round trip being the
  three places a regression has actually landed. Thirteen seconds.

**What a replay asserts, and why it is not more.** Almost everything here is
hash-bound on purpose, so a replay that diffed receipts byte for byte would go
red on a new field, a protocol bump and a dependency upgrade — every one of them
legitimate — and would be deleted inside a month. The assertions are layered.
Binding: the exit codes in sequence; the final status and the verdicts under it;
the per-check verdicts, exactly, because coverage is a fraction and stays 1.0
when the declared set shrinks with the covered one; the measured values inside
the band the *contract itself* declares for them, falling back to the pipeline's
own 0.5% where a row declares zero; the receipt set by name; the reviews
answered; and four hashes that are equalities between two values from the same
run rather than literals in a file. Advisory, reported and never failing:
`reasons` and `allowed_claim`, which are prose. Not asserted at all: receipt
bytes, any pinned digest, findings text, timings, witness images.

**The recorded answer is re-bound, not replayed.** A stored review response
echoes an envelope binding the packet, the contract, the plan, the evidence
digests and the protocol version — which is why the real vent-ball run carries
two 164-byte reports whose whole content is `review envelope mismatch`. So a case
records the reviewer's *judgement* with no envelope, and the harness stamps the
one the current run just issued. That is what a human reviewer does; only the
judgement is recorded. It would be a hole if nothing checked the binding still
bit, so the suite asserts each report's envelope is the packet's, and an
adversarial case hands the run an answer bound to evidence that moved and
requires it to refuse, write no final status, and make the comparison go red.

**Zero live dispatches, asserted.** `materialise` creates no `reviews/`, so every
response on disk is one the harness wrote and it can only write a recorded one; a
review with no recording raises rather than leaving the job paused; and
`AGENT_COMMISSION` is fatal, because that instruction *is* the live dispatch on
the `CUSTOM` lane.

**The two suites are separated structurally.** `testpaths` names
`skills/3d-modeling/scripts` and `tools`; `benchmarks/replays` is in neither, so
a bare `uv run pytest` cannot collect a job replay. CI runs L0 on every push and
L1 on pull requests as its own job. The harness's own guards are L0 —
`tools/test_replay.py`, 47 tests in 3 s, with every guard shown red under a
mutation that disables it — because a check nobody checks
reports all clear just as convincingly when it is broken.

**Where the expectations came from.** Not from the two completed real runs on
disk. `oneplus8t-magnet-drawer` has no `project.json`, no execution plan and no
review packets: it was built by hand-rolled scripts and there is nothing to
replay it *through*. `vent-ball-combine-r1-exercise-2` is a full recording and is
still not the source, for four reasons: it costs ~876 s and 24 GB of RAM against
a two-minute budget for the whole tier and died in the allocator once in eleven
runs; it ran at `2721ffe`, before two later slices; its root `final_status.json`
was deleted by its own revision-2 bump; and two of the three defects behind its
terminal `FAILED` are *instrument* failures this repository intends to fix, so
pinning them would build a fixture that goes red the day the bug is repaired.
What is taken from it is what survives a change of scale and is real: the
recorded request, the `MODIFY`-with-an-edit-scope shape, and the source artifact
itself. Both `expected.json` files are recorded at the current commit
deliberately; re-record with `--record` when a change legitimately moves one, and
put the diff in the review.

### Changed — a project problem is data, not a sentence

Release 3 slice C, and the half of the derived-status work that was left owed.
Once `design-tool status` answers per alternative, "why is this one not
`COMMISSIONED`" is a question asked of N formulations at once — and
`Project.validate()` answered it with a `list[str]` of English. No code to branch
on, no field path to jump to, no severity, and nothing an instruction written
today could be compared against one written last week. With one formulation that
list is readable. With several it is a search.

**A move, not a design.** The type already existed and was complete:
`team_tools.common.Issue` — severity, code, field path, message, and a stable
`CODE@where` id — has carried every contract-validation finding since it was
written. It now lives in `pipeline/findings.py`, and `team_tools.common`
re-exports it from there, so both packages report through one type rather than
two that drift. The dependency points from `team_tools` to `pipeline` and never
back: `team_tools` is the older layer and `pipeline` is the one being built, and
a shared module owned the other way round would make everything built next depend
on what it replaces. `pipeline/test_findings.py` holds that direction with an AST
check over every production module in the package, because the import that
reverses it is a one-line change nobody would notice in review.

One thing changed on the way. `Issue.message` was always `f"{where}: {detail}"`;
it can now be supplied instead, and `pipeline` supplies it. Those sentences were
written before the type existed, they already name their own field
(`"source_mode is NEW but source artifacts are declared; ..."`), and the suite
asserts on several of them — so prefixing a path onto them would have changed
what a user reads to gain nothing a caller could not read off `where` directly.
The default is untouched, which is what keeps every existing `team_tools` receipt
byte-identical.

**The codes are grouped by what clears them.** `SCHEMA_` means one field is wrong
in itself — correct the field. `REF_` means a well-formed id that no row
declares, or two rows for one id — add, remove or rename a row. `ARTIFACT_` means
the declaration is fine and a file disagrees: it escapes the project, is not
there, or was read and refused — fix the file. `INTENT_` means every field and
every reference is fine and the declarations still describe no one job — make a
decision. The shape follows `analysis.py`'s existing `BOOLEAN_ENGINE_*` /
`SECTION_INSTRUMENT_*` codes, and the vocabulary is deliberately small: `id` is
`CODE@where`, so `SCHEMA_ENUM@source_mode` already names exactly one rule and a
code per check would be a lookup table rather than something to match on.

**`where` is a position, not a name.** `edit_scopes[1].region_box`, not
`edit_scope 'drawer'`. With two scopes over two artifacts, the sentence quotes an
id and a caller still has to search the list for it; the path is the field. The
box checks name the axis too (`region_box.x`), because a box can be empty on two
axes at once and an id two findings share is an id nothing can be keyed on.

**Nothing that read the old answer reads a different one.** The terminal prints
the same sentences in the same order — the skeleton project's six lines are
pinned literally in a fixture. `next_action.unresolved` is still a list of
sentences, because four unrelated stages fill it (a validator, a status
derivation, a stage message, the project's open questions) and a field whose
element type depends on which of them wrote it is a field no reader can parse.
The structure arrives beside it under `findings`, one entry per line and in the
same order, in the refusal instruction and in `design-tool status --json` alike.
The four stage refusals that reported bare sentences through the same
function — a missing envelope, a plan that does not validate, a refused proposal
or build, a model contradicting its proposal — are findings now too, so
`_report_problems` has one element type whichever stage called it.

Zero-cost is unaffected: `next_action.json` is hashed into nothing, and the five
pinned contract goldens and `test_frozen.py` are untouched.

### Changed — the status is computed from the evidence, and invalidation is scoped to it

Release 3 slice B. Three separate ways for a receipt to say something that is no
longer so, and one mechanism that answers all three.

**The status was stored.** `status.decide` ran once, mid-run, its answer went
into `final_status.json`, and every reader afterwards repeated it verbatim —
`design-tool status` recomputed the project's `problems` and took the verdict as
given. A `VERIFIED` receipt beside a candidate somebody had rebuilt, an evidence
file somebody had corrected, or a plan that had since moved all read as current,
and nothing on disk could tell.

`final_status` in the `status` report is now derived. `pipeline/bindings.py`
reads each receipt's own record of what it was issued against — the artifact
manifest's digests, the commissioning report's contract hash, a review report's
whole envelope down to the witness images and evidence files it was shown, the
final status's artifact hashes and plan digest — and compares it against what is
on disk. A stored `COMMISSIONED` or `VERIFIED` whose receipts no longer bind
derives `STALE`; a directory where no run concluded derives `NOT_RUN`. The stored
verdict is still reported under its own name, because it remains the record of
what that run concluded; what changed is that a reader no longer trusts it
without checking.

It is deliberately **not a second gate**. Nothing is re-run and no threshold is
re-applied, so a job whose bindings all hold derives exactly what it stored, and
the only move available is downward. A `FAILED` or `NEEDS_MORE_EVIDENCE` whose
bindings broke keeps its own name and carries the breakage alongside — the same
choice the lane cap makes, and for the same reason: a finding replaced by "this
is out of date" is a defect nobody is looking at any more.

**Invalidation was all-or-nothing.** A changed acceptance body deleted a fixed
six-name tuple, whatever had actually moved. That rule can express "something
changed, therefore everything is stale" and nothing else — not "this changed,
therefore that is", and not "this is still true, leave it alone". The tuple is
gone and the rule is derived from the bindings each receipt carries. An
acceptance revision still reaches the same six files, because every receipt binds
the model contract's hash and the model contract binds the acceptance contract's,
so one broken edge takes the chain. What is new is everything else: a rebuilt
candidate takes the artifact manifest and the commissioning report measured
beside it; a corrected caliper sheet takes only the reviews that were shown it
and the status that rested on them, and the measurements of a candidate that did
not move stay on disk. `model_contract.json` is reported stale and never removed —
it is the contract the others are checked against, and deleting it would turn
"issued against a contract that has moved" into "there is no contract here".

`design-tool run` performs that sweep immediately before executing, which is what
keeps ADR 0002 §4's promise on a run that does not finish: a job that stops for a
review no longer leaves the previous run's success sitting beside it.

**`project.json` no longer mirrors either.** The `status` and `bindings` blocks
copied one run's stage, verdict, claim and artifact digests into the one file
that has to stay shared, so the project said the job was whatever had finished
last — and slice A had already had to stop a branch stamping them, which left a
mirror that was true of the root and silently wrong while a branch was active.
They are dropped rather than made per-alternative: two authorities over one fact
is the shape this codebase removes, and it is the same argument that deleted
`project_hash()`. A project file written under the old mirror still loads, since
what is dropped is a copy of something that is on disk in its own right; the one
value in there that was a declaration rather than an outcome —
`external_geometry`, recorded by the `job.json` adapter and read by `route.decide`
and `to_job_request_fields` — is carried across into its own field.

### Fixed — a successful `route` no longer instructs toward a state the project has left (D17)

`next_action.json` carried no identity: no run id, no sequence, no self-digest.
Staleness was handled entirely by overwriting or unlinking the file, so any path
that changed the project without reaching one of those two calls left an
instruction pointing at work already done, and nothing could detect it. A
successful `route` was exactly such a path — it wrote "this project cannot be
routed" while the project was incomplete, and left the sentence there once the
project was completed and routed.

Every instruction now carries `state` (the acceptance contract, the model
contract, the execution plan, the artifact digests, and which formulation it is)
and `state_sha256` over it — the same map the derived status checks receipts
against, because an instruction and a receipt go stale for the same reasons.
`status` reports `waiting_for_superseded` and stops counting a superseded
instruction as something to do. `route` recomputes the instruction against the
state after routing: nothing, when the receipts still support a current success,
and `RUN` otherwise.

### Fixed — a STEP can be read, by the kernel that was already here (D13, D14)

`preservation.audit` handed every source path to `trimesh.load`, which dispatches
STEP to `cascadio`. `cascadio` is not in this runtime and is not in `uv.lock`, so
**every** audit against a STEP source returned `UNMEASURABLE:
ModuleNotFoundError: cascadio` — most CAD anybody supplies, the base of every
`MODIFY` and `COMBINE` on one, and the primary source of the repository's only
`PHYSICALLY_PROVEN` fixture.

**`cascadio` was not added.** It was measured first, which is what settled it.
`build123d` is already a core dependency and `diagnose` already reads STEP
through it, so the choice was between one STEP reader and two — and the second
one disagrees with the first about the file. On `vent_mount.step`, `cascadio`
returns the part in **metres** where `build123d` returns millimetres, in 324
disconnected bodies with 8,284 boundary edges against 10 and 1,854, and it still
produces no triangles for the cone faces. A silent unit substitution is the first
thing `ARCHITECTURE.md` §12 forbids of a backend swap, so 16 MiB of second OCC
build would have bought a units defect and no capability.

`mesh_io` gained the reading instead: `tessellate_brep` probes every face through
the public tessellation API and **returns** what it could not read rather than
throwing it away, and `read_step` is the one place a supplied B-rep becomes
triangles. `validate_brep_tessellation` — which already existed and already named
the faces OCC refuses — is now that function with a raise on the end, so there is
one probe and not two. The deflection it reads at is a declared constant
(`BREP_READ_LINEAR_DEFLECTION`, 0.01 mm) and travels onto the preservation
receipt under `tessellation`, because two deflections are two meshes of one solid
and therefore two measurements; a mesh file's read is a parse and records nothing,
so no evidence digest moves for a job that never touched a B-rep.

`diagnose` runs the same probe (D14). `vent_mount.step` was `USABLE_EXACT` with
no findings and then killed the first operation that needed geometry with
`'NoneType' object has no attribute 'NbNodes'`. The old test was face *area*, and
area is not tessellability: all 329 faces have finite positive area — one of them
is 1.75e-14 mm², which is small and is not zero — so `invalid_faces` was 0 and
would have stayed 0 however the check was tightened. It now reports
`untessellatable_faces`, names each one with its surface type and centre, and
classifies `REPAIR_REQUIRED`.

The file itself is still untessellatable, and that is now [D22](docs/defects.md)
rather than a clean verdict: **six** cone faces, not the four D14 recorded, plus
a seventh face that fails when the shape has not been meshed as a whole first.
The audit refuses on it and names them, rather than measuring a surface with six
holes in it and reporting a distance to geometry that is missing rather than
moved.

A source that parses to zero triangles is refused the same way. `trimesh.load`
turns a file that is not an STL at all into an empty mesh rather than raising, and
an empty mesh reached the distance query as an r-tree over nothing —
`ValueError: Bounds must be (n, dimension * 2)`, raised out of the audit, out of
the check and out of the run as a stage failure with no row and no receipt.

### Fixed — the preservation audit runs under a declared ceiling (D16, D19)

Measured on the vent-ball pair, unbatched, on this machine: **23.24 GiB peak
working set, 91.18 GiB peak page file, and it does not finish** — 334 s in,
`MemoryError: Unable to allocate 2.47 GiB for an array with shape
(331606963,)`. The reported field failure was the same shape at
`(210081703,)`, and it killed one invocation in eleven while the other ten
completed. Determinism of the *answer* was achieved in the previous release;
determinism of *completing* was not, and Release 1 exists so that an unchanged
job can be rerun and resumed.

The 210 million was never mysterious. `trimesh.proximity.nearby_faces` uses the
distance to the nearest *vertex* as its query radius, so a sample 60 mm from a
20 mm part asks the r-tree for everything inside a 60 mm box: all 7,056 faces came
back for all 20,000 points in one direction, and a mean of 16,583 of 19,522 in the
other. At a measured 350 bytes of working set per (point, face) pair — flat to
four significant figures across a 70x range of query sizes and two meshes — that
is the whole of the 23 GiB.

`audit` now takes `memory_ceiling_bytes`, declared at 2 GiB, and derives the
query batch from it: `ceiling / (faces x WORKING_BYTES_PER_CANDIDATE)`, with the
per-candidate cost declared above the measurement at 384 bytes because a ceiling
computed from an optimistic cost is not a ceiling. Both directions' batches are
settled before either runs, so a job too big for its ceiling is refused with the
arithmetic in the reason and nothing allocated — not discovered halfway through
with one direction's numbers already written.

**The ceiling bounds execution and does not touch the measurement.** Splitting
the query is exact: `closest_point` computes every point independently — the
candidate lookup, the per-row triangle distance and the two-best tie-break are all
per query point — so a batched run returns the same float64 values as an
unbatched one. `signed_distance` is still the call being made, even though the
sign is discarded one line later, so that "byte-identical to today" is a fact
rather than an argument about when `np.sign` returns zero. The ceiling is
deliberately **not** in the sample plan or the evidence: binding a review answer
to a machine's memory budget would expire that answer when the job was rerun
somewhere smaller, having measured the same thing.

Same fixture, same region, under the 2 GiB ceiling: **2.16 GiB peak working set,
3.61 GiB page file, 200 s, and it completes.** 10.8x less resident, 25x less page
file, 1.7x faster than the run that died.

### Fixed — an unreadable source no longer zeroes the allowance for the readable one (D18)

`cli._inherited_overhang` returned `None` — the generated zero — if *any*
declared source could not be measured. On the vent-ball run one source was the
STEP above, so the allowance the candidate was entitled to inherit from the
readable source went to zero with it, and the job failed
`feature-plan-support-00` on 4,582.055 mm² of overhang **it had inherited from the
part it was told to preserve**. A contract failure caused entirely by a missing
importer, reading like a design defect.

The old argument was that a partial sum is a ceiling nobody measured. A zero is
not more measured than a partial sum — it is less measured, and it is wrong in
the direction that fails a correct part. The sum over the sources that read is a
strict lower bound on what the candidate legitimately inherits, so it cannot
excuse an overhang the edit added; what it cannot cover is the unread source's own
share, and the provenance note now says which sources were measured, which were
not, why not, and that the ceiling is therefore partial. `None` still means the
generated zero and now means only what it says: not one declared source could be
measured.

### Fixed — the verdict a user reads names the check that never ran (D20)

`commission_report.json` kept the distinction perfectly — `ran: false`,
`status: UNAVAILABLE`, `measured: null`, `result: ESCALATE`,
`error_code: PRESERVATION_UNMEASURABLE`, the exception as its reason, beside a
sibling row reading `ran: true / MEASURED` — and carried it nowhere.
`final_status.json` said "rejected by independent verification" and the CLI
summary line said the same, so a user who did not open the commission report
learned that a reviewer had refused their part rather than that the tool had never
read their primary source. Those call for different actions and only one of them
is the user's fault.

`status.decide` now collects every `UNAVAILABLE` check into `unavailable_checks`
and appends them to `allowed_claim`, after the lane cap, because a rejection, a
failure and a capped success can each sit beside an instrument that never
measured. `design-tool status` and the end-of-run summary both print
`allowed_claim`, so the sentence cannot drift from the receipt. A run with nothing
unavailable is unchanged, and the frozen `DIRECT` claims are untouched.

### Added — a second formulation of the same job, isolated on disk and in the receipts

`design-tool branch <project> --from <alt|.> --id <name> --reason "<text>"` is one
deterministic verb with no dispatch. It appends an `{alternative_id, parents,
reason, disposition}` row to `project.json`, points `active_alternative` at it,
and **copies nothing**: the brief, the requirements, the source artifacts and the
evidence stay shared and are read by reference. `--activate <alt|.>` switches,
`.` being the shared root the siblings were branched from. `parents` is a list
from this first release, because a merge is a revision with several contributing
parents and widening a scalar later is not additive; nothing here writes more
than one entry.

When an alternative is active, every file that means something about *one*
formulation is written under `alternatives/<id>/`. With one shared directory the
collisions ran worst-first, and none of them announced itself:

* two siblings froze into one `acceptance_contract.json`. The second's `freeze`
  read the first's contract as `previous`, cut a revision, and `_invalidate`
  deleted the first's `final_status.json`, `commission_report.json`,
  `artifact_manifest.json`, `manufacturing_report.json` and both review reports.
  Re-running the first did it back. Two alternatives destroyed each other on
  every alternating run, and `acceptance_history.json` recorded the fork as one
  linear chain of corrections;
* `_run_authored` skips the designer commission when `design_proposal.json` and
  `model.py` both exist, so a second alternative was **never commissioned**: it
  rebuilt the first's geometry and filed the receipts under its own name;
* `candidate.stl` and `candidate.step` are fixed literals, so the second build
  overwrote the first;
* a review is answered by the *presence* of `reviews/<kind>_response.json`, so a
  sibling picked up the answer written next door and then failed closed on the
  envelope while reporting the wrong diagnosis.

**Path isolation is necessary and provably not sufficient**, so `alternative_id`
joins exactly two hashed payloads: `execution_plan.json` and the review envelope
(`REVIEW_PROTOCOL_VERSION` 3 → 4, so a stored protocol-3 answer is refused by
name rather than by an unexplained digest mismatch). `ExecutionPlan.as_payload`
carries no parameters and deliberately omits `candidates`, so two authored
formulations of one job compile to the same plan hash; the envelope's `revision`
is `updated_utc`, a timestamp rather than a graph node; and at the instant a
branch is created its sibling is a copy, so `contract_sha256`, `artifact_hashes`
and `witness_hashes` are all equal. A safety `PASS` written for one sibling was
therefore `is_bound` for the other — a false pass of exactly the class the
authority gate forbids, reachable with nobody doing anything wrong. It does
**not** join `contract_sha256`: two formulations requiring identical geometry
legitimately share an acceptance contract.

Invalidation is one rule. A change to the shared half of `project.json`
invalidates every alternative; a change inside an alternative invalidates that
one only. Both follow from freezing per alternative root, and
`acceptance_history.json` now records the alternative on each entry and inside
`supersedes`, so a correction and a fork are distinguishable rather than
identical.

**Zero cost when unused, exactly rather than approximately.** A project that has
never branched serializes, compiles and hashes to the bytes it did before: every
new field is absent when there is nothing to say and never `null` — the
`execution_plan_sha256: None` precedent in `review.py` is deliberately not
followed — no subdirectory appears, and the five pinned certified contract hashes
and every `test_frozen` golden are unchanged and were not re-pinned.

`pipeline/test_alternatives.py` carries the fixtures; each was verified to fail
under a targeted mutation of the protection it covers, including the two that
matter most — remove `alternative_id` from the envelope and one sibling's PASS
binds the other; emit it as `null` instead of omitting it and the zero-cost
proof fails.

### Removed — `candidate_strategy`, and `Project.project_hash()`

`candidate_strategy: "PARALLEL"` was validated, stored in `project.json`, carried
into `intent_manifest.json` and hashed, and its entire behavioural effect was
appending one sentence to the route escalation list. Nothing generated a second
candidate, isolated one, or compared two — a schema field that let a document
claim a capability with nothing behind it. A project or `job.json` carrying it is
now refused **by name** and pointed at `design-tool branch`; `"SINGLE"` is read
and dropped, because it claimed nothing and sits in every `project.json` this
build has written.

`Project.project_hash()` hashed the whole payload including the mutable `status`
and `bindings` blocks, so it moved on every finished run, and it was read by
nothing. Its one appearance — `next_action.json`'s `bound.project_sha256` — is
replaced by `requirement_sha256`, the digest of the half of the job nobody on the
design side owns, which is what the frozen acceptance contract already carries and
what shared-half invalidation already keys on. A digest that always differs is one
its readers learn to ignore, and two digests over one declaration is one authority
and one bug.

### Fixed — a shared source artifact is found from a branch

`commission` resolved a declared preservation source beside the candidate, which
stopped being beside the project once the candidate moved under
`alternatives/<id>`. It takes the shared root explicitly now and defaults to the
candidate's own directory for every caller that has none, so a `MODIFY` job on a
branch measures against the artifact where the project declared it rather than
reporting `SOURCE_MISSING` for a file that is already there.

### Fixed — the candidate was writing to the party that decides the run (D10)

`model.py` declares `PROVENANCE`. The child returned it in
`build_manifest.json`, `isolation.py` adopted it verbatim, `acceptance.py` put it
in `contract.source`, and `runner.py` handed that contract to the safety reviewer
and the verification reviewer, whose PASS or REJECT decides acceptance. Free text
the candidate composed reached the grader. No process confinement closes this,
because the data is supposed to cross — and read access to the frozen contract
(D9 row 3) does not create the channel, it aims it: a candidate that knows the
tolerance bands and the design id can write in the gate's own vocabulary.

Three more channels were found beside it, all in `artifact_manifest.json`, which
both packets embed whole: `backend_version`, `tessellation` and `boolean_engine`
were candidate-supplied strings copied straight onto the receipt. And the
manifest is written by a process the candidate's module-level code already runs
in, so *every* field of it is candidate-authored whatever `build_child` intends.

The repair is a type, not a filter — a sanitiser that stripped suspicious words
would be one more removable check, and this branch has had two of those fail:

* the engine strings are a **closed vocabulary the parent owns**. The child
  returns a `kernel` token; `isolation.KERNELS` maps it to the words on the
  receipt, and the version comes from the parent's own `importlib.metadata`. A
  token the table does not hold selects `unrecorded` — it is never passed
  through. Nothing about the receipt's wording changed;
* `PARAMS` and `PROVENANCE` are quarantined in an
  `isolation.CandidateDeclaration`. `BuiltCandidate` — the only object that
  leaves the boundary — otherwise holds paths, digests, numbers and that one
  token. `AcceptanceSource` has no `provenance` field at all now, so
  `as_source()` cannot carry one;
* `PROVENANCE` is written to `candidate_declaration.json` and read by nothing.
  That is the cost, stated plainly: a reviewer that was using the designer's
  account of how the part was made no longer gets it. It was never evidence — it
  is the assertion of the party being judged — and the reviewer keeps the brief,
  the frozen contract, the measurements and the witnesses, all of which are
  written by someone else.

`test_isolation.NoCandidateProseReachesAReviewerTest` is permanent and attacks it
twice: a `PROVENANCE` addressed to the reviewer, and a model that replaces
`schemas.canonical_json` in its own process and rewrites the entire manifest on
its way out. Both assert one marker absent from every receipt, from the real
`reviews/safety_packet.json` the run produced, and from a verification packet
built from the same evidence. Two more assert the shape rather than a run: the
field set of `BuiltCandidate`, and that not one of the fourteen modules on the
path to a reviewer packet imports the boundary or reads `.declared`.

`CHILD_SCHEMA` is 3. `model.name` and `BuiltCandidate.kernel` were read by
nothing and are gone with the strings.

### Fixed — the network probe was measuring NordVPN, not the boundary (D11)

`test_isolation`'s network row asserted refusal by connecting to `1.1.1.1:53`.
That port is filtered on this machine by NordVPN Threat Protection, identically
with no confinement at all, so the row was green everywhere and had never
measured the confinement. Re-measured under the real restricted low-integrity
token: `1.1.1.1:443` connects, `1.1.1.1:80` connects, `93.184.215.14:80`
connects. All three firewall profiles are `DefaultOutboundAction=NotConfigured`.

The probe aims at 443 now and the row is `ALLOWED`, because it is. The
expectation that this boundary denies outbound TCP is kept as a *failing* test,
`test_the_boundary_denies_outbound_tcp`, marked `expectedFailure`: the suite
stays green while the gap is open, and closing it produces an unexpected success,
which unittest reports as a failure. A limitation that goes off is worth more
than a paragraph that does not. `confine.py`'s docstring said the restricted
token refused `socket.connect`; it does not, and it now says so, as does
`docs/defects.md` D9 row 1 — the network is open, not closed-except-DNS.

### Fixed — the confined child could still create processes (D12)

Measured: a candidate under the full boundary launched `cmd.exe`. Every
counter-measure was downstream of the process already existing — the job object
caught it, the survivor sweep counted it, the drain killed it before anything was
read. `PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY` with
`PROCESS_CREATION_CHILD_PROCESS_RESTRICTED` moves the refusal to `CreateProcess`:
measured `WinError 367`, at zero geometry cost (1.77 s trimesh, 5.86 s build123d
including its cold import).

It has one prerequisite. A virtual environment's `python.exe` is a launcher that
spawns the base interpreter as a child, so under this policy the boundary could
not start its own child. `isolation.base_executable()` launches
`sys._base_executable` directly and `PYTHONPATH` gains the environment's
`site-packages`; both paths are read-only to the restricted token, and outside a
virtual environment the two answers coincide.

Two attacks had to be rewritten to keep measuring what they were written for:
`mklink /J` is `cmd.exe`, so the junction attack and the probe's reparse-point
row now go straight at `FSCTL_SET_REPARSE_POINT` with no subprocess at all —
strictly stronger, since it needs no privilege and no helper program, and it
turns a row that used to be denied because `cmd.exe` said `Access is denied.`
into one denied by the kernel: `ERROR_ACCESS_DENIED` on the control itself,
measured, from inside the one directory the candidate can write. The
`DETACHED_PROCESS` and `CREATE_BREAKAWAY_FROM_JOB` grandchild attacks now fail at
process creation instead of inside the job; both are kept, because the job object
is what makes a failure of this policy survivable and it is the mechanism that
has already been walked through once.

### Fixed — seven declared fields that a reviewer's answer did not depend on (D5, D6)

An edit scope declared twelve things about a modification. Five of them reached
the acceptance contract or the sampling plan; seven did not reach anything at
all. `alignment_transform`, `preserve`, `may_remove`, `add`,
`expected_body_delta`, `preserve_metadata` and `interface_ids` were parsed,
validated, written into `project.json`, covered by `Project.project_hash()` — and
read by no consumer, and `project_hash()` appears on no receipt. Demonstrated: a
finished `MODIFY` job given a 5 mm x-translation on its edit scope, saved and
rerun, produced every evidence digest unchanged, had its stored `PASS` accepted,
and wrote a final status. (`preserve_metadata` was the seventh; the defect entry
named six, and it has the same shape.)

* `cli._preservation_feature` now carries all seven into the contract's
  preservation row, so all seven reach the frozen acceptance revision and
  therefore `contract_sha256` in the review envelope;
* `preservation._seed_material` takes `alignment_transform` as well, because it
  is the one of the seven that says which geometry the plan is a plan *of*: a
  region box is written in the job's frame, so moving the source under it makes
  the same box select different surface. It is *bound* there, not applied — the
  audit is not frame-aware, and coordinated multi-source preservation is out of
  scope for this release. `SAMPLE_PLAN_VERSION` is 2 accordingly;
* the other six are contract-only on purpose. They are promises about the edit,
  not statements about where the geometry is, and none of them changes which
  points are sampled. Putting them in the seed would move a sample-plan digest to
  advertise a measurement that was not rerun.

### Fixed — the execution plan bound nothing a reviewer answered

`ExecutionPlan.plan_hash()` reached `final_status.json` and nothing else, and
that file is written *after* the review it should have bound. So `builder`,
`source_mode`, `lane_status`, `lane_note` and `preserved_artifact_ids` — the
lane cap included — could change under a stored answer and keep it.
`ReviewEnvelope` carries `execution_plan_sha256` now, supplied at all three review
boundaries — safety, verification, and the `FITTED` specification recovery, which
is only asked for because the plan routed `FITTED`.
`REVIEW_PROTOCOL_VERSION` is 3: the envelope's
shape changed, so a stored protocol-2 answer is refused by name rather than by an
unexplained digest mismatch. No fixture or benchmark carried one.

### Added — the Release 1 rerun-rejection proofs, run end to end

`ROADMAP.md` Release 1 asks for five rerun-rejection proofs. The nearest tests
compared two digests computed in-process without running a job, or fabricated a
digest rather than changing an input; none offered a review a stored response or
checked whether a final status was written anyway. `test_phase3.py` now runs the
whole loop — run to the review pause, store the answer, change exactly one thing,
rerun — over changed source, changed candidate, changed algorithm version and
every edit-intent field, and requires both a `ReviewError` and no
`final_status.json`. Seven of the eleven cases failed before this change. A
twelfth case covers the protocol bump: a stored protocol-2 answer is refused by
version, not reinterpreted.

Two more shapes had been demonstrated and never tested: a two-scope job, where
changing one scope must leave the other artifact's evidence byte-identical and
must still refuse the answer; and clean-clone reproduction for the `MODIFY` lane,
where the two existing two-directory tests are certified-template `DIRECT` jobs
with no edit scope, no preservation audit and no sample plan. `module_sha256` is
excluded from the clone comparison, and the exclusion is asserted rather than
assumed: the confined build stages `model.py` alone into a sandbox and runs it
there, so a `MODIFY` model must name its source artifact by absolute path.

### Changed — Release 1 no longer claims evidence reuse

Its scope said "reuse valid evidence for unchanged inputs". The code has never
done that and should not: only the build is cached, a preservation audit is about
two seconds, and a cache key for one would have to name exactly the bindings this
release exists to get right. A wrong key serves a stale audit under a fresh
receipt. `ROADMAP.md` now says what the code does — identical inputs re-derive
byte-identical evidence, which is idempotence and is what makes the round trip
resumable.

### Fixed — the candidate is built with less authority, not just in another interpreter

The previous entry moved the builder into its own process. An adversarial review
then walked through it three ways, and none of them needed an import, a race, or
anything to persist:

* `pipeline/backends/authored.py` is first imported by the parent **after**
  `isolation.build` returns, on the path of every authored job. The candidate
  rewrote it while building and the parent executed its module-level code
  seconds later, in the interpreter holding the frozen contract. Exit 0,
  `final_status VERIFIED`, `feature-pad-section PASS expected 432.0 measured
  80.002`, contract untouched at revision 1, history `changed: []` — the
  pre-change reproduction, verbatim, on the post-change code;
* a stealth variant compiled the same patch into
  `__pycache__/authored.cpython-313.pyc`, stamped with the real file's mtime and
  size, leaving the `.py` byte-identical. Hashing the source finds nothing;
* a `DETACHED_PROCESS` grandchild outlived `subprocess.run`'s timeout: the run
  reported exit 1 `FAILED`, and 25 s later `design-tool status` reported
  `VERIFIED` with nothing outstanding.

The root cause is one sentence. Separation was implemented as a different
*interpreter* and the claim ADR 0002 needs is about *privilege*. Same user, same
filesystem, no lifetime bound.

`pipeline/confine.py` replaces it with an OS-enforced confinement, built with
`ctypes` against `advapi32`/`kernel32` rather than by adding `pywin32` to a
security boundary:

* a **restricted token** whose restricting-SID list omits
  `NT AUTHORITY\Authenticated Users`, with every other group deny-only. On this
  machine `C:\` grants `Authenticated Users: Modify` by inheritance and nothing
  else the token carries grants write, so the repository, the virtual
  environment and this package's source cap at `BUILTIN\Users: Read & Execute`.
  Measured: it also refuses `socket.connect` with `WSAEACCES`;
* **low integrity**, which is what refuses the project directory, the parent's
  `%TEMP%`, the Startup folder, the sandbox's own inputs, and
  `OpenProcess(PROCESS_VM_WRITE)` against the parent. Each of those was measured
  by running the probe at *medium* integrity and watching it succeed;
* a **job object** with `KILL_ON_JOB_CLOSE` and breakaway not permitted.
  `DETACHED_PROCESS` never left a job; the attack worked because there was no
  job. `CREATE_BREAKAWAY_FROM_JOB` is the flag whose purpose *is* to leave one,
  and a grandchild that passes it is measured not to. The parent drains the job
  to zero live processes before it reads one byte out of the build directory;
  the count is taken by process id after a short settle, because a job keeps
  counting a process until its last handle closes and because Windows puts its
  own transient `conhost.exe` in there for under 100 ms of every run;
* exactly **two inherited handles**, named in a
  `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`: a `NUL` and one pipe for the transcript;
* a **constructed environment**. Three of the attacks found the tree they
  rewrote by reading `PYTHONPATH` out of an inherited one.

Every privilege is deleted except `SeChangeNotifyPrivilege` — bypass traverse
checking, which `Everyone` holds by default and which grants access to no object.

The workspace is two directories with protected DACLs that inherit nothing:
`in\` holds **copies** of `model.py` and every `*.py` beside it and is sealed
read-only after staging, and `out\` is labelled Low and is the only object on
the machine the child can write. The child is no longer told where the project
is; it gets a directory and a file name.

Ordering, which is most of the repair: every input is hashed **before** the
child exists, so `module_sha256` names what ran rather than what survived; and
nothing is read out of the build directory until the job is dead. Each output is
then checked by exact byte compare against the name asked for, refused if it is
a reparse point, refused if it carries an alternate data stream, refused if its
real path resolves outside the sandbox, and hashed by the parent.

Staging every `*.py` beside `model.py` also closed a gap nobody had named: the
old boundary put the whole *project directory* on the child's `sys.path` and the
receipt recorded one digest, so a part built from a model and a helper was
described by a contract naming half of it. `model_contract.json`'s `source`
block now carries `sources_sha256`, a digest per staged file.

**Source-integrity hashing is not the gate.** The `.pyc` attack is the reason:
it left the source byte-identical, and a check that fires after the authority has
been exercised is detection, not confinement. One narrow canary is kept over
`acceptance_contract.json`, and a failure of it is reported as a failure of the
boundary rather than as a finding about the model.

**Named limitations, measured and asserted still open** (`docs/defects.md` D9):
DNS resolution still succeeds through the DNS Client service, which is a
low-bandwidth outbound channel; `AppData\LocalLow` and `%TEMP%\Low` carry an
explicit Low label from Windows and are therefore writable; and the candidate
can still *read* what `BUILTIN\Users` can read, including the contract it is
measured against. `AppContainer` is the mechanism that closes the first and the
third; an Untrusted integrity level closes the second and does not start
(`STATUS_DLL_INIT_FAILED`, measured), as does a `NULL`-SID lockdown token used as
a primary token.

Deleted rather than layered: `PARENT_OWNED`, `PARENT_OWNED_DIRS`, `_guarded`,
`_snapshot` and `_restore` — an eighteen-name list that had to be kept in step
with `acceptance.INVALIDATED_BY_A_NEW_REVISION` and whose failure mode was a
silent gap, replaced by an operating system that does not let the write happen;
`_child_env`, which handed over `os.environ`; and `subprocess` from the boundary
entirely, which means the D8 mutation "launch the child with `shell=True`" has no
expression left to mutate.

Tests: `pipeline/test_isolation.py` grew from 16 to 58. It carries the three
attacks that broke `0a8e464`, a write into the virtual environment, a grandchild
that asks the kernel to leave the job, an escape through a junction, one probe
model that measures fourteen confinement properties from inside the confinement
and asserts the three named limitations still open, and the first tests
`pipeline/build_child.py` has ever had. Every one of the ported attacks fails
against `893c9cc` and passes here; 27 of the 53 tests that can run against the
old boundary fail on it.

`DIRECT` creating no process is now proven with `sys.addaudithook` over a
`pipeline.confine.spawn` audit event rather than by replacing two module
attributes, because a hook catches a process created through a name nobody
thought to replace.

Mutation kill rate, same method both sides (apply one weakening to a clean copy
of the tree, run `test_isolation.py`): **5 of 15 before, 25 of 25 after.** The
before figure is the review's own fifteen against `893c9cc`, reproduced exactly.
The after figure is those fifteen mapped onto the new code — three have no target
left, because `PARENT_OWNED` and `_restore` are gone — plus thirteen for the
mechanisms this boundary added: `Authenticated Users` back in the restricting
set, medium integrity, every privilege kept, the job never terminated, survivors
never counted, the sweep removed, alternate data streams and reparse points
unchecked, every inheritable handle inherited, the environment inherited, the
confinement made optional, the parent reading before the job drains, and sibling
sources not staged.

Four survived the first pass and each one was a real gap, now closed: the
timeout was asserted as a constant and not as `build`'s default; nothing built a
manifest declaring another protocol, so the schema check was extracted into
`_sections` and unit-tested; nothing asserted the sandbox is deleted; and
nothing asserted the child's transcript is captured rather than inherited, which
also turned up a genuine hole — a model that printed a measurement and then
raised had the print discarded, and the manifest-error path now carries it.

Suite: 964 passed / 4 skipped / 379 subtests to 1006 passed / 4 skipped / 419
subtests, 673 s to 794 s. `design-tool selftest` 11/11, `gen_harness --check`
11/11, no frozen contract hash moved, ruff and the internal link check clean.

Cost: a whole authored `design-tool run` goes 1.674 s to 1.668 s, and the
confinement's own share of it is about 0.14 s — free next to the cold geometry
import it wraps. `DIRECT` is untouched: 0.191 s to 0.186 s on `c_clip`, inside
the run-to-run spread, dispatch 0 to 0.

### Fixed — the candidate is built in a process that cannot reach its own gate

Freezing the acceptance contract before the builder was necessary and was not
sufficient. `cli._run_authored` froze the contract and then imported the
candidate's `model.py` with `spec.loader.exec_module` **in the CLI's own
interpreter**, and an import is an execution: `runner.status is pipeline.status`,
`status.decide` resolves at call time, `commission._tol` and
`contract.area_tolerance` are module globals, `AcceptanceSource.expectations` is
one assignment, and the live frozen contract sat in the calling frame one
`sys._getframe()` away. Reproduced to a `VERIFIED` final status on the same
352 mm2 miss, with the on-disk contract still at revision 1 and an empty
`changed` list.

`model.py` now runs in a **one-shot child process** — `sys.executable -m
pipeline.build_child`, an argument vector and never a shell string, so it works
on Windows without `fork` and a path with a space in it survives.
`pipeline/isolation.py` is the parent half: it hands the child a model path, a
scratch directory, two output names and whether a STEP is wanted, and *nothing*
about acceptance. Results come back as JSON and files. The parent re-reads and
re-hashes the geometry itself, copies only the two artifacts it asked for by
name, and verifies that every pipeline-owned file in the project directory — the
frozen contract, its history, the proposal, the project, every receipt, and
`model.py` — is byte-identical to what it was before the child started. One that
moved is restored and the run is refused.

Consequences a designer will notice: `PARAMS` and `PROVENANCE` must be JSON, the
model's own directory is deterministically on `sys.path` rather than depending on
where the command was invoked from, and the candidate cannot write a receipt.

`DIRECT` executes no candidate code and does not enter the boundary; `runner.py`
does not import it. Measured unchanged at 0.191 s (`c_clip`) and 0.243 s
(`trim_ring`, warm).
A certified INCONSEQUENTIAL `DIRECT` job still makes zero dispatches: the
boundary is a process, not a round trip. An authored build pays one cold
interpreter, of which 0.16 s is the boundary and the rest is the geometry kernel
the candidate itself imports.

Deleted as redundant rather than left beside it: the builder callable no longer
crosses into the parent at all (`JobRequest.authored_builder` and
`.authored_model` are gone, `backends/authored.py` no longer imports a geometry
kernel or calls anything), and `cli.py` no longer imports the module that
executes model files.

### Added — a deterministic pipeline with certified INCONSEQUENTIAL DIRECT zero dispatches

Six iterations of the approved redesign. The entry below describing `DIRECT` as
"two dispatches" is what this replaced: on a certified template inside its
domain, certified `INCONSEQUENTIAL` `DIRECT` now costs **zero specialist calls**, and
the whole job — contract, build, commission, screening, witness, status — measures
well under a second for the certified trimesh path on the reference workstation.
A build123d cold import or a static interface check can cost more; these are
environment measurements, not guarantees. A certified `CONSEQUENTIAL` `DIRECT` job instead has one
bounded safety review and no normal geometric verifier.

The shape of it:

* **The contract is written before the geometry** and frozen at build start.
  `model_contract.json` names every mandatory feature with five properties:
  where its number came from, what it should measure, the tolerance, which check
  proves it, and what to do when that check cannot run. `preflight` refuses a
  contract missing any of them.
* **Expectations share no code path with the backends.** `expectations.py`
  imports `math` and nothing else, so geometry and expectation cannot fail
  together. Asserted by an import-graph test, not by a naming convention.
* **Fail-closed.** A check that cannot run escalates or fails per the contract.
  There is no `SKIP`, deliberately.
* **Broad screening**, measured against a mutation corpus over every certified
  template and scored on defects fused to the part — the ones the component
  detector does not catch for free. `python -m pipeline.corpus` is the gate, and
  it moves the final status rather than editing a claim string.
* **Routes**: certified `INCONSEQUENTIAL DIRECT` has no review callback; certified
  `CONSEQUENTIAL DIRECT` has exactly one bounded safety review and no normal
  geometric verifier; `FITTED` requires one bounded specification review; and
  `FULL` requires specification plus independent verification. `VERIFIED` is
  reachable only through independent verification that never saw the designer's
  reasoning.
* **Five certified templates**, `c_clip`, `box_shell`, `l_bracket`, `trim_ring`
  and `vented_enclosure`, each with parameter bounds that route an
  out-of-domain job away from `DIRECT` rather than building it anyway.
* **Content-addressed caching**, keyed on the contract hash, template,
  `domain_id`, backend version, lockfile, schema version and tessellation
  settings. Off unless asked for.

Measured cold on the reference workstation for certified `INCONSEQUENTIAL` `DIRECT`
jobs: zero specialist calls; a 12-vent enclosure in 0.42 s, 72 vents in 0.53 s,
and 300 vents in 0.78 s on the trimesh path. These measurements do not cover every
template or environment.

### Changed — consequence is two levels, everywhere

An earlier revision classified jobs with four risk-tier names and then wrote a
two-value enum into `job.json`, with nothing mapping between them: a highest-tier
job became `CONSEQUENTIAL` and every finer-grained guarantee evaporated at the
file boundary. Four names that decay to two on write are worse than two names,
because they read like protection that is not there.

`INCONSEQUENTIAL` and `CONSEQUENTIAL` are now the only levels in the charters as
well as the code. No legacy risk-tier field survives at the file boundary.
The prohibited applications did not become a third level — they are
`safety.MANDATORY_CONCERNS`, which the mandatory safety review must address
explicitly. `team-contracts-v4.md` documents the two-value consequence field and
the review obligations instead of leaving a discarded risk mapping to be guessed.


### Changed — the pipeline runs the phases a job actually has

`profile: COMPACT | FULL` decided how verbose the record was and nothing else —
the contract said outright that "both profiles run the same gates" — so a job
whose every dimension the user stated still paid all seven dispatches. It also
contradicted itself: `COMPACT` was defined as having "no recreated mating
geometry", while `REFERENCE_BUILD` exists to reconstruct exactly that.

The profile is now decided by one question, what must be recovered from
evidence, and it decides which phases run. Certified `INCONSEQUENTIAL` `DIRECT`
(dimensions stated, nothing recreated) has no review callback; certified
`CONSEQUENTIAL` `DIRECT` has exactly one bounded safety review and no normal
geometric verifier. `FITTED` retains its required bounded specification review,
with independent verification when configured; `FULL` retains specification and
independent-verification review. `PRINT_PREP` became conditional on what
`commission.json` reports rather than on the profile.

Two rules survive every profile because the archive shows what happens without
them: the plan is never authored by whoever builds the geometry — with no plan
bound, all four archived runs set their own support ceiling *after* reading
their own measurement — and verification is never folded into the build.

So `DIRECT` needs a plan it did not write. `designer_toolkit.plan` supplies one,
with conservative numbers fixed ahead of any part and stamped
`threshold_source: builtin-default`, and `plan check` rejects an unbuildable
plan at authoring time instead of after a 39-minute build.

### Removed — the tool surface that taught designers to hand-roll the gate

Three measured runs, and none executed `commission`; each hand-wrote a
verification script. They were following the documentation, whose headline
section documented `finalize` and offered a menu of seven individual
subcommands. A tool surface that offers the pieces gets the pieces assembled by
hand.

`measure`, `overhang`, `datums`, `interference`, `sweep`, `export` and
`finalize` are gone from the CLI; `commission` and `coupon` remain. Every
library function stays importable. The verifier now recomputes with the same one
command against the delivered STL — independence is a property of which inputs
you consult, and it never reads the designer's `commission.json`.

### Added — checks that cost no build, and templates that can be asked

`commission` runs a pre-build stage over a module-level `PARAMS` dict and
returns before the first CAD call when the declared numbers already settle the
question: a wall under two extrusion widths, an edge treatment at half the wall
or more, a declared size that disagrees with the plan, and a cavity mouth fillet
larger than its clearance. That last one is closed form — a fillet pulls the
wall in by its own radius at the mouth, so clearance must be ≥ radius. One
archived run bisected four full build/export/measure cycles toward it.

`designer_toolkit.templates` (`box_shell`, `panel`, `bolt_boss`, `stack`)
returns geometry together with the `PARAMS` describing it, computed from the
same arithmetic that built the solid, so the two cannot drift. `panel` reports
the narrowest material left between its openings — a plate whose holes leave a
0.6 mm rib is watertight, the right size, and unprintable, and every other gate
passes it.

`artifact_manifest.json` and `candidate_readiness.md` are now derived from those
measurements rather than retyped, with `visual_accept` and `fit_band_ok` left
blank on purpose.

### Fixed — gate defects that passed bad parts

The fit check compared a boolean intersection *volume* against the plan's
per-side *millimetres*, so a part built exactly to a declared `[0.15, 0.30]`
band failed; nothing caught it because every fixture set `interfaces: []`. The
support screen used the best orientation it could find rather than the plan's
declared `model_to_printer_matrix`. Only `support_rules[0]` was checked. Every
edge check was silently skipped on any contract-conformant plan, because the
loop required a `corner_xy` field that appears nowhere in the contract. And
`metrics.overhang_area` disagreed with the authoritative gate by 2× on a real
candidate — returning 0.0 mm² for a part the gate scored at 10,507 — because it
excluded faces by an arbitrary centroid height rather than the gate's
three-vertex bed test.

Also: `status` answered the reference-freshness question from whichever
reference happened to be listed first, so a multi-part job could change its lid
and read as clean; and all five agent definitions requested skills
(`3d-designer` and friends) that stopped existing at the single-skill
restructure, which fails silently and left every specialist starting with no
charter loaded.

### Removed — the per-harness packaging layer

The OpenCode and generic/OpenAI outputs, their generators, their tests, and
`docs/harness-matrix.md` are gone (−1,065 lines, 12 files). Once the pipeline
ships as one skill whose orchestrator dispatches by pointing a subagent at
`roles/<name>.md`, per-harness agent registration buys nothing a file read does
not: any runtime that can spawn a subagent and read a file runs the pipeline
unchanged. `PyYAML` went with them — nothing imports `yaml` any more.

`.claude/agents/` is still generated, because it is what makes
`claude --agent 3d-verifier` and `@`-mentioning a specialist work; the role file
and the agent definition remain two renderings of one source in `skills/roles/`.

### Changed — one skill, not five

The five role slices shipped as five installable skills that reached each other
by relative path. Installing them proved that broken: each archive carried the
shared assets at its own root while every `SKILL.md` still said
`../3d-modeling/references/...`, so **36 links across the five roles resolved one
directory above the install** — the files were all present, the build was green,
and an agent following its own required reading found nothing.

The orchestrator is now the skill and the four specialists are files it hands to
subagents:

```
3d-modeling.skill
  SKILL.md          <- the orchestrator; the only invocable entry point
  roles/{metrologist,designer,print-engineer,verifier}.md
  references/  scripts/
```

`skills/3d-modeling/` on disk *is* the shipped tree, so every relative link in the
archive is the same link that resolves in the repo. The roles were never
independently useful anyway — a designer with no commission refuses to start, by
design.

Dispatch is harness-neutral: the orchestrator points a subagent at
`roles/<name>.md` and gives it a dispatch id and a project directory, nothing
about the expected answer. Where a host registers named specialist agents
(generated from the same role sources into `.claude/agents/`), dispatching by
name is equivalent — the role file and the agent definition are two renderings
of one source. A host with no such registry loses nothing: a plain subagent
pointed at the role file is the whole mechanism.

`test_every_internal_link_resolves_inside_the_archive` now fails the build if any
link escapes the archive or names a missing member. It caught one leftover
immediately: `team-contracts-v4.md` still pointed at the deleted
`3d-orchestrator/SKILL.md`.

### Added — test coverage where a promise was unverified

Coverage audit found 85% over the statements the suite imported, but 2,670 lines
across 11 modules touched by no test at all.

- **`check_internal_links.py`** was a CI gate with zero tests — the same shape as
  the drift gate that turned out to pass unconditionally. 7 tests; it also gained
  a `root` parameter (it hardcoded the repo root, so it could not be pointed at a
  fixture) and `.venv`/`dist`/`temp` exclusions, since a local virtualenv's package
  READMEs are not ours to validate and can fail a run CI passes.
- **`make_3mf.py`** writes a deliverable — a malformed 3MF is not a caught error
  but a broken hand-off found at the printer. 5 tests over the OPC members a slicer
  needs, the per-part component structure multi-colour depends on, geometry
  round-tripping, and the non-watertight warning.
- **`run_cadquery_model.py`**: 236 lines, no tests, and its published exit codes
  (3 on timeout) were the least verified promises in the repo. 6 tests, all on the
  core stack since the runner's logic is not CadQuery's.
- **`python -m designer_toolkit`**: 7 smoke tests. The designer is told to call this
  CLI rather than re-author the measurement patterns, so a broken subcommand sends
  the role back to hand-rolling what the toolkit exists to prevent.
- Coverage now reads 74% over 2,159 statements — a truer figure over a bigger base.
  What remains uncovered needs a live GL context or a real Bambu Studio install.

### Changed — one plan file can serve both gates

`print_plan_checks.json` (team_preflight) and `print_plan.json` (team_tools) carried
field-for-field identical edges and support rules, differing only in whether the
version key was `schema_version` or `contract_version`. The contract asked the print
engineer to maintain both and nothing compared them. `team_preflight` now accepts
either name, verified by pointing it at team_tools' own example plan unmodified.

### Fixed — benchmark-driven role corrections

Roles were run blind against parts whose ground truth was withheld, then re-run with
identical inputs after a single change (see AGENTS.md → *Changing a role*).

- **Metrologist, rounded-edge envelopes.** It read a phone's width at "a flat region"
  — but the widest section of a rounded part is at mid-thickness, so jaws on the
  curved shoulder under-read width while the same curvature inflates thickness. The
  delivered width error fell 1.66 mm → 0.36 and length 0.61 mm → 0.01, using 15%
  fewer tokens. The re-run diagnosed the bias by name and resolved to the true
  envelope instead of shipping the biased read.
- **Metrologist, conflicts must ask.** The first run logged three caliper-vs-spec
  conflicts as open questions and stalled at DRAFT without asking anyone. Both
  sources are fallible, so neither wins on principle; a fit-critical conflict now
  goes to the user with both values and the downstream effect. The re-run withheld
  two ambiguous readings entirely rather than shipping one wrong by 2.84 mm.
- **`fdm-design.md`, part-class wall thickness.** The "4 walls" structural default was
  applied to a snap-on case, giving 2.03 mm walls where the real printed case uses
  1.02 — +1.2 mm on width and thickness and ~46% material. That default is for a part
  meant to be stiff and wrong for one meant to flex, and on a part that wraps a
  mating object the wall is a dimension entering the envelope twice.

  Measured at n=3 (one run before the change, two after). The two post-change runs
  agree to 0.05 mm on wall and 0.1 mm on both plan dimensions — 2.03 → 1.57 and
  1.52 mm/side, with material down 17% — so the effect is the change and not
  run-to-run variance. It closes about half the gap to the oracle's 1.02: both
  runs chose 1.2 mm nominal, within the guidance, then added material elsewhere.
  Thickness moved the *wrong* way in both (12.5 → 14.0 and 14.1 against an oracle
  10.74) because each independently added a camera-relief boss and retention ribs
  — a choice the wall guidance neither caused nor prevents, and one that is now
  clearly systematic rather than a fluke. Accuracy cost about a third more tokens.

### Changed — the gates enforce what the contract claims

- Mandatory safety concerns are now addressed by the bounded safety review rather
  than by a discarded R-tier contract. The two-value consequence field
  remains the only classification at the file boundary, and the safety reviewer
  must explicitly address any listed concern and its required physical evidence.
- **`contracts status` is now part of the orchestrator's readiness gate.** It is the
  only check that compares each contract's `revision` against what downstream
  contracts bound to — a `dimensions.md` revised after the plan cited it surfaces as
  `STALE` there and nowhere else — and no role invoked it.
- **Evidence binding stated honestly.** Rule 15 ("hashes bind agents to files") now
  says where binding is real: `artifact_manifest.json`, whose artifacts have their
  SHA-256 recomputed and bbox/component count re-checked. An evidence path written
  only as a Markdown table cell is not resolved by anything — a report citing a file
  that does not exist validates clean — so evidence a gate rests on must also appear
  as a manifest row.

### Changed — contracts are validated where they are actually written

`team_tools` validated JSON exclusively, but v4 defines four of the five contracts
as Markdown and no role is told anywhere to author a JSON mirror. So 393 lines of
validator schema-checked files the pipeline never creates, `validate` reported
four `MISSING_CONTRACT_FILE` warnings on every correct run, and `--require all`
rejected a project built exactly to the contract.

The binding fields were in the Markdown all along: `revision`,
`dimensions_revision`, `print_plan_revision`, `reference_sha256`,
`candidate_stl_sha256` all live in the frontmatter. Each contract is now looked up
as Markdown first, then a JSON mirror if one exists, and:

- **Markdown** gets `validate_contract_header` — identity, version, owner, `job_id`,
  and the integer `revision` the staleness and binding checks compare. Its body is
  provenance, uncertainty and open questions written for the next agent to read;
  a validator walking those rows could only ever confirm that prose is prose.
- **JSON** (`artifact_manifest.json`, a machine-authored `print_plan.json`)
  additionally gets its full structural validator, unchanged.
- `validate_job_state`, `validate_dimensions` and `validate_verification_report`
  are deleted (−393 lines, plus their tests).
- `MISSING_CONTRACT_FILE` is gone. It fired on every correct run, on the same
  `warning_ids` channel that carries `POSSIBLE_UNIT_SCALE_MISMATCH` — which the
  verifier is required to act on. A benchmark designer run called those warnings
  "expected", which is precisely the habit worth not teaching. `validated_paths`
  already records what was read.

Verified against a real agent-produced project: `validate` now reads
`dimensions.md`, `job_state.md` and `artifact_manifest.json` with zero warnings,
`status` reports revisions from the Markdown, and `--require all` passes a
five-contract Markdown project. The verifier role is back to `--require all`.

### Removed — streamlining pass (net −1,534 lines, 16,767 → 15,237)

A six-axis review (docs prose, skill/role text, Python, gate value, repo hygiene,
FDM domain content) looking for duplication, dead weight, and instructions that
cost tokens without changing an outcome.

- `skills/3d-modeling/scripts/backends/` — a `ModelBackend` ABC with cadquery /
  build123d / freecad adapters and a test-only `FakeBackend`. Zero importers: the
  real export path is `designer_toolkit.exporter._write_solid`, which does its own
  dispatch and never knew the package existed.
- `team_tools` `render` and `agent-summary` subcommands (`render.py`, `summary.py`).
  No role, agent definition or reference ever invoked them, and no rendered output
  is committed anywhere. `render` generated Markdown *from* JSON, inverting a
  pipeline whose Markdown is the authored side.
- `references/preflight-checklist.md` — 135 lines with zero inbound references,
  contradicting `fdm-design.md` on chamfer size and `troubleshooting.md` on
  calibration order. Its correct thread number and its six-step calibration order
  (which included the max-volumetric-speed step the live file omitted) were
  harvested into the files that are actually loaded.
- Half of `references/build123d-patterns.md` (192 → 84): unreferenced, and the
  backend-neutral half was a verbatim clone of `cadquery-patterns.md`. Its sample
  called a `finalize(strict=True)` signature that does not exist.
- Dead Python: `verify_visual.footprint_iou` (superseded by `pose_score`),
  `MeshIntegrity.non_manifold_edge_count` (computed on every export, read by
  nothing), an `engine=` parameter no caller passes, a `team_tools/__init__`
  re-export nothing imports, and three copies of the same `_as_mesh` coercion.
- Repeated exit-code blocks, harness invocation stated in three files, a hand-run
  OpenCode checklist duplicating what `test_gen_harness.py` asserts, and per-extra
  `pyproject` comments duplicating the README table.
- `.skill` bundles no longer ship the test suite and fixtures — 412 KB → 141 KB per
  artifact, across six artifacts. Nothing in a shipped skill ran them.

### Fixed

- Connected-component counts are now computed in pure numpy (label propagation over
  face adjacency) instead of `trimesh.Trimesh.split`. `split` needs scipy to label
  components and networkx to close any component with a hole; on a core-only install
  it raises, and both call sites swallowed that into "1 component" — so a two-body
  export could pass `is_single_watertight_solid()` and the artifact manifest's
  `expected_components` check silently observed nothing. Verified to match `split`
  exactly on 50 meshes (welded, unwelded, holey, corner-touching, multi-body).
  Affects `mesh_io.compute_integrity`, `designer_toolkit.exporter` /`metrics`, and
  `team_tools` `COMPONENT_COUNT_MISMATCH`.
- `designer_toolkit.metrics.datum_features` now raises a single `ImportError` naming
  the `section` extra when its stack is absent, instead of surfacing trimesh's
  deferred `ModuleNotFoundError` from several frames down, one missing package at a time.
- The `visual` extra was missing `networkx` and `rtree`, which `verify_visual.slice_union`
  reaches through `Path2D.polygons_full`. Its catch-all turned the resulting ImportError
  into `None` — read downstream as "empty slice", so a part sliced against itself scored
  IoU 0.0 instead of 1.0 and every overlay/alignment number silently collapsed. The extra
  is now complete and `slice_union` checks the stack before the catch-all, which keeps
  doing its real job (genuinely degenerate sections).
- Repository URLs in `pyproject.toml` and `CHANGELOG.md` pointed at a `github.com/Idan/…`
  org that does not exist; they 404'd.
- The generated-harness drift gate never fired. CI ran `pytest` before
  `gen_harness.py --check`, and a test shelled out to the generator *without*
  `--check`, rewriting the working tree — so the check compared regenerated files
  against themselves and passed unconditionally. Reproduced by drifting a role
  source: `--check` alone exited 1, after `pytest` it exited 0. The test now
  compares in memory and writes nothing, and `--check` runs before `pytest`.
- `manifest_checks._compare_extents` used `elif`, so a near-25.4× scale flag on any
  one axis suppressed `BBOX_MISMATCH` on every axis — a declared bbox 5× wrong on
  another axis was reported as a warning, not an error. The 25.4× promotion also
  swept all axes, so an unrelated axis landing near 25.4× could promote a warning
  to a hard error. Both fixed, with regression tests in both directions.
- `mesh_io._components` swallowed every failure into "1 component", the exact
  silent multi-body pass `connected_component_count` was written to prevent. It now
  raises a `ValueError` naming the vertex/face counts; the CLI callers already
  surface `ValueError` cleanly.
- `designer_toolkit`'s overhang self-check could report clean where the authoritative
  gate FAILs — measured at 0.00 mm² vs 1873.15 mm² on a 46° face — while a comment
  claimed lockstep with a `team_preflight` default that does not exist (the field is
  required per-rule). `finalize` now records whether the threshold came from the
  caller or the toolkit default, and re-screens at the bare 45° value to announce
  the gap when they differ.
- FDM guidance corrected against the source corpus, all five independently
  re-confirmed: printed threads floored at `M8 (≥1/8")` — 8 mm glossed as 3.175 mm,
  which forced heat-set inserts onto every M4–M6 boss the sources say prints fine;
  30–40% infill against a documented 15–20%; warp-relief cuts specified at 1 mm deep
  where deeper *increases* warp (0.5 mm); bottom chamfer stated three
  incompatible ways across two files; and a 0.8 mm wall rule where 0.8 mm is the
  geometric floor and 1 mm is the design rule.
- `team_tools.contracts` now exits `2` on a project directory that does not exist. Every
  canonical contract is "absent" either way, so a typo'd path was indistinguishable from a
  clean early-phase project and validated `PASS` with exit `0`.
- The README framed the pipeline as Claude Code subagents, though the roles are generated
  from `skills/roles/` into three harnesses. Rewritten harness-neutral, with per-harness
  entry points and the setup prompt branching on the harness rather than assuming one.

### Added

- `team_tools.contracts validate --require <contract>[,…]|all` — names contracts whose
  absence is a `REQUIRED_CONTRACT_MISSING` **error** rather than a warning, so the exit
  code becomes a sound gate. Absence stays a warning by default because mid-pipeline a
  project legitimately holds only the contracts its phase has produced. The names are
  recorded in the receipt's new `required_contracts` field; an unknown name is a usage
  error (exit 2) rather than a silently dropped requirement. The verifier and designer
  role definitions now pass it.
- `section` optional extra (`scipy`, `networkx`, `shapely`, `rtree`) — the trimesh
  soft dependencies the cross-section path needs for `datum_features` and the datum
  blocks `bundle.finalize` derives from it. Kept separate from `visual` so the datum
  path does not pull in pyrender/PyOpenGL and a GL context.
- CI `section` job running the designer-toolkit suite with that extra installed. The
  main matrix stays core-only and now also proves the tooling degrades honestly there.

### Removed

- Deleted the retired historical `skills/team-design.md` design document after migrating live
  runtime contract language into `skills/3d-modeling/references/team-contracts-v4.md`.
- Retired the former single-entry `skills/3d-modeling/SKILL.md`; the invocable surface is now
  the five-role file-contract pipeline while `skills/3d-modeling/references/` and
  `skills/3d-modeling/scripts/` remain the shared library.

## [0.1.0] — 2026-07-25

Initial public import of the multi-agent 3D-modeling skill. This release is the
product of a real-part optimization program: agents ran **blind** (photos +
calipers + public specs only) against **held-out** ground truth (the user's final
3MFs / a downloaded reference model) on three physical parts — a Pixel 7 case, a
Garmin Fenix 7X charging dock, and a broom-holder clip. Each single pipeline step
was scored against its oracle; a fix was promoted only after re-test on a
different part with **no regression** (anti-overfit gate), with the scorer kept
separate from the editor.

### Added — five-role, file-contract pipeline

- A five-role Claude Code subagent pipeline that turns a request + reference
  photos/calipers into a verified, print-ready model. Roles communicate **only**
  through project contract files and source evidence, never chat summaries:
  - **orchestrator** — routes solo-vs-team, owns job state and phase gates,
    dispatches specialists, never authors geometry.
  - **metrologist** — converts photos/calipers/specs into datum-based ground
    truth (`dimensions.md`); visually accepts the blind mating reference.
  - **print-engineer** — issues the pre-design manufacturing contract
    (`print_plan.md`) and the post-verification coupon / slicing / print-order /
    field-test plan.
  - **designer** — builds one blind reference or one candidate from the
    contracts, with mandatory FDM-aware design; may not accept its own work.
  - **verifier** — a fresh, independent context that re-imports the exported STL
    and runs all seven Phase-4 checks, including actual render + photo-overlay
    inspection.
- A **solo monolith** entry point (`skills/3d-modeling/SKILL.md` +
  `references/fdm-design.md`) for simple, single-part, non-fit-critical jobs. The
  solo skill was held byte-identical through the whole optimization program.
  (`SKILL.md` retired — see Unreleased; `references/fdm-design.md` remains.)
- Role charters and design rationale in `skills/team-design.md` (historical; the file
  was deleted afterwards — see Unreleased — and does not exist in any commit);
  the **normative** runtime contract and gate schema in
  `skills/3d-modeling/references/team-contracts-v4.md`.

### Added — deterministic tooling

- **`team_preflight.py`** — deterministic support/geometry predicate gate over
  the exported STL under a stated rigid transform.
- **`team_tools/`** — a contract-automation CLI (`validate` / `hash` / `status` /
  `render`) plus an `artifact_manifest`. It auto-computes **SHA-256** and binds
  artifacts to a contract **revision** (no agent-entered hashes), detects stale
  dependencies, and validates finite numbers, enums, IDs, foreign keys, and
  path-safety, including a 25.4× unit-scale (inch→mm) check.
- **`mesh_io.py`** — raw-vs-normalized mesh reporting so a genuine defect in an
  exported file is visible on the *raw* read before any repair runs (P-14).
- Backend runners and authoring helpers: `run_cadquery_model.py`, `preview.py`,
  `make_3mf.py`, `make_bambu_3mf.py`, and the shared visual tools
  `overlay_photo.py` / `verify_visual.py`.

### Added — `designer_toolkit` (Phase-4 tooling, agentic→code speedup)

- **`designer_toolkit/`** — the deterministic Phase-4 work the designer and
  verifier used to re-author (and re-debug) every job, now a tested library they
  **call**: `export_and_hash` (export + re-import + hash — measures the REAL
  delivered geometry on the normalized mesh, killing stale-hash and phantom-shell
  bugs), `measure` / `datum_features` / `overhang_area` (bbox/volume/integrity;
  section holes in MODEL coordinates via `plane_transform`; overhang at the SAME
  −0.73 screen as the gate), `interference` (static seated boolean-overlap fit on
  the exported mesh — a single position at rest; no insertion/travel sweep is
  computed, and dynamic motion fit is deferred), `fit_coupon` (parametric
  multi-lane coupon from the plan's
  interfaces), `render` (ref-vs-candidate view grid + section, pyrender-gated),
  and a one-call `finalize` that assembles the whole evidence bundle. Also a CLI
  (`python -m designer_toolkit …`).
- **Why:** move the mechanical measuring out of per-job agent code to shorten the
  design step; the agent writes only the parametric geometry and the judgment
  calls (`finalize` leaves `visual_accept` / `fit_band_ok` unset on purpose — a
  green mechanical bundle is necessary, not sufficient).
- Mesh/fit/coupon paths are CI-safe (need `manifold3d` for booleans, no CAD
  kernel); the CadQuery export path is lazy and `render` is deferred. 14 tests;
  full suite **139** as of this release. Surfaced in the designer/verifier slices and
  `cadquery-patterns.md` via `references/designer-toolkit.md`.

### Hardened — preflight gate (Sprint 1)

- Reject **non-finite / NaN / ±Inf / None / bool / malformed** numeric samples
  that previously *false-passed* the gate (confirmed reproduction, now rejected).
- Fix a `float(None)` crash on a null read-cap (S-03); it now raises a clean,
  field-named error only inside `SELF_SUPPORT_REQUIRED`.
- Validate finite, rigid transforms and **contain evidence paths** (reject `..`,
  absolute, and symlink escapes).
- **Honestly relabel** the support audit as a "downward-facing-surface screen":
  it is a crude downward-normal test, *not* a supportability proof (see
  meta-finding). No functional-correctness claim is made by passing it.

### Changed — H-03: fit-strategy ownership

- Moved fit/clearance ownership from the metrologist to the **print engineer**.
  The metrologist reports as-observed geometry + uncertainty only; the print plan
  now declares fit through a structured **per-interface `fit_type` enum**,
  enforced by a `validate-interfaces` gate. Backward-compatible: `interfaces` is
  optional (absent → skipped).

### Fixed — two validated design-step spec fixes

- **Fillet / OCC robustness fallback ladder** (design-step optimization #1): a
  graduated retry strategy for fillet/chamfer operations that otherwise abort the
  OCC kernel, so a single fragile edge no longer sinks an otherwise-valid model.
- **45° self-support screen margin** (design-step optimization #2): the
  downward-facing-surface screen threshold was corrected to **-0.73**
  (= -sin 47°), giving a ~2° margin past the 45° self-support limit. This stops
  the screen from false-flagging legitimate 45° chamfer faces while still
  catching genuinely unsupported overhangs. Value validated, not guessed.

Both fixes were re-tested across 3 parts / 3 fit types with **zero regression**;
the bounded-fit-band principle propagated to real Pixel-case geometry at
0.20 mm/side (in-band).

### Notes / meta-finding

- **Executable gates ≠ functional correctness.** Passing a deterministic gate
  (schema, finite-number, hash/revision-binding, path-safety, `team_preflight`)
  is *necessary evidence, not proof* that a part will fit, print, or survive its
  load — that remains an agent judgment call. This was corroborated
  independently by an external review and by the design step (④) remaining the
  quality frontier: a real contact/motion model is deferred.
- Deferred (out of the v0.1.0 scope): a `cad_runner` resource governor, a
  contact/motion engine, a fail-closed 3MF writer, a Bambu adapter, camera
  calibration, and a golden-fixture regression suite.

[0.1.0]: https://github.com/ghsi011/3d-modeling-skill/releases/tag/v0.1.0
