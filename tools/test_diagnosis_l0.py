#!/usr/bin/env python3
"""L0 — the five artifacts the Stage 2-5 rewrite is not allowed to break.

This is a regression net for [ADR 0002](../docs/adr/0002-route-and-contract-authority.md),
not a benchmark product. Stages 2 to 5 move acceptance-contract authority, state
lifecycle, the gate matrix and preservation; every one of them reads what
`pipeline.diagnose` says a supplied artifact is. 821 passing tests hid two HIGH
defects, so the property this file is built for is the one the general suite does
not have: **the facts are asserted, not the verdict.**

A test that says `pixel9 -> USABLE_MESH` and stops passes for the wrong reasons.
It passes when the root part was picked by luck, when `p:path` never resolved and
the objects were found some other way, when the build transform was ignored, and
it would keep passing through a classification-policy change that quietly hid a
parser regression. So each fixture asserts the chain that produced the verdict:
which part the package relationship named, where the unit came from, which ids
resolved through which part, what the transform did to the numbers, and whether
the placed bounding box is actually the placed geometry.

Where a fact is a number that could have been copied out of a previous run, it is
re-derived here from a second, independent read of the archive -- the
relationship XML, the raw vertex coordinates -- so that agreeing with the parser
means agreeing with the file.

Cost: three external files back the whole set, and both the hash verification and
the diagnosis of each are cached for the module. Six cases ask different questions
of the same 2.2 MB Pixel 9 export; re-reading it once per case would multiply the
most expensive item here by six for nothing.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "skills" / "3d-modeling" / "scripts"))

import fixtures as FX                                              # noqa: E402
from pipeline import diagnose as D                                 # noqa: E402

_CACHE: dict[str, dict] = {}
_PATHS: dict[str, Path] = {}
_CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"

# A closed, consistently wound 4 mm cube, written by hand so the synthetic
# fixtures below carry real geometry without a mesh library in the loop.
_BOX_MESH = ('<mesh><vertices>'
             '<vertex x="0" y="0" z="0"/><vertex x="4" y="0" z="0"/>'
             '<vertex x="4" y="4" z="0"/><vertex x="0" y="4" z="0"/>'
             '<vertex x="0" y="0" z="4"/><vertex x="4" y="0" z="4"/>'
             '<vertex x="4" y="4" z="4"/><vertex x="0" y="4" z="4"/>'
             '</vertices><triangles>'
             '<triangle v1="0" v2="2" v3="1"/><triangle v1="0" v2="3" v3="2"/>'
             '<triangle v1="4" v2="5" v3="6"/><triangle v1="4" v2="6" v3="7"/>'
             '<triangle v1="0" v2="1" v3="5"/><triangle v1="0" v2="5" v3="4"/>'
             '<triangle v1="1" v2="2" v3="6"/><triangle v1="1" v2="6" v3="5"/>'
             '<triangle v1="2" v2="3" v3="7"/><triangle v1="2" v2="7" v3="6"/>'
             '<triangle v1="3" v2="0" v3="4"/><triangle v1="3" v2="4" v3="7"/>'
             '</triangles></mesh>')
_BOX_OBJECT = f'<object id="1" name="mesh" type="model">{_BOX_MESH}</object>'
_RELS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_ROOT_REL = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"


def _fixture_path(case: unittest.TestCase, fixture_id: str) -> Path:
    """The verified file, or a skipped test with the reason in it.

    Absent is a skip: none of this geometry is in the repository -- it is
    licensed or user-owned and is referenced by path and hash -- so a checkout on
    a machine that never had it must still run the rest of the suite. A hash that
    moved is not a skip and `fixtures.resolve` raises; see its docstring.
    """
    if fixture_id not in _PATHS:
        try:
            # Cached because `source_path` re-hashes the file on every call, and
            # the Pixel 9 fixture is 2.2 MB reached from six cases.
            _PATHS[fixture_id] = FX.source_path(fixture_id)
        except FX.FixtureUnavailable as exc:
            case.skipTest(str(exc))
    return _PATHS[fixture_id]


def _report(case: unittest.TestCase, fixture_id: str) -> dict:
    if fixture_id not in _CACHE:
        _CACHE[fixture_id] = D.diagnose(_fixture_path(case, fixture_id))
    return _CACHE[fixture_id]


def _declared_root(path: Path) -> str:
    """The root part as the *package* names it, read without the diagnoser.

    Asserting `report["root_part"] == "3d/3dmodel.model"` asserts a string
    somebody typed. Asserting it against the relationship this archive actually
    carries asserts that the relationship was followed.
    """
    with zipfile.ZipFile(path) as archive:
        rels = ET.fromstring(archive.read("_rels/.rels"))
    targets = [r.attrib["Target"] for r in rels.findall(f"{_RELS}Relationship")
               if r.attrib.get("Type") == _ROOT_REL]
    if len(targets) != 1:
        raise AssertionError(f"{path.name}: expected exactly one 3dmodel "
                             f"relationship, found {targets}")
    return targets[0].replace("\\", "/").lstrip("/").lower()


def _declared_unit(path: Path, part: str) -> str:
    with zipfile.ZipFile(path) as archive:
        name = next(n for n in archive.namelist()
                    if n.replace("\\", "/").lstrip("/").lower() == part)
        return ET.fromstring(archive.read(name)).attrib["unit"]


def _authored_bounds(path: Path, part: str, object_id: str):
    """The raw vertex extremes of one object, straight out of the XML.

    Nothing here goes through the diagnoser, which is the point: it is the
    number a reader who ignored the build item would have reported.
    """
    with zipfile.ZipFile(path) as archive:
        name = next(n for n in archive.namelist()
                    if n.replace("\\", "/").lstrip("/").lower() == part)
        root = ET.fromstring(archive.read(name))
    obj = next(o for o in root.iter(f"{_CORE}object")
               if o.attrib.get("id") == object_id)
    points = [(float(v.attrib["x"]), float(v.attrib["y"]), float(v.attrib["z"]))
              for v in obj.iter(f"{_CORE}vertex")]
    low = [min(p[i] for p in points) for i in range(3)]
    high = [max(p[i] for p in points) for i in range(3)]
    return low, high


class L0CleanProductionExtension(unittest.TestCase):
    """1 — the Pixel 9 case: a Bambu production-extension export that is fine.

    The file this branch's `diagnose` was written for. A reader that opens one
    `.model` part and resolves component ids against it alone finds three
    components pointing at ids it cannot see, and tells the user an intact,
    watertight, four-object scene needs repair.
    """

    FIXTURE = "pixel9-card-case"

    def test_the_root_part_is_the_one_the_package_relationship_names(self) -> None:
        path = _fixture_path(self, self.FIXTURE)
        report = _report(self, self.FIXTURE)
        self.assertEqual(_declared_root(path), report["root_part"])
        self.assertEqual(4, len(report["model_parts"]),
                         "the scene part and three object parts were all read")
        self.assertNotIn(report["root_part"],
                         [o["part"] for o in report["objects"]
                          if o["geometry"] is not None],
                         "every mesh in this file lives outside the root part; "
                         "a reader that only opened the root would find none")

    def test_the_unit_comes_from_the_root_model_part(self) -> None:
        path = _fixture_path(self, self.FIXTURE)
        report = _report(self, self.FIXTURE)
        self.assertEqual(_declared_unit(path, report["root_part"]),
                         report["units"])
        self.assertEqual("millimeter", report["units"])

    def test_a_unit_that_is_not_the_default_is_read_rather_than_assumed(self) -> None:
        """The half the real file cannot supply.

        Every Bambu export in this set declares `millimeter`, which is also the
        value a reader that never opened the attribute would report. Agreeing
        with the file is therefore not evidence that the file was read, so the
        discriminating case is synthetic: a root part declaring `inch` has to come
        back as `inch`, and as a finding rather than a conversion.
        """
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "inch.3mf"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "3D/3dmodel.model",
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<model unit="inch" xmlns="http://schemas.microsoft.com/'
                    '3dmanufacturing/core/2015/02"><resources>'
                    '<object id="1" type="model"><mesh/></object>'
                    '</resources><build><item objectid="1"/></build></model>')
            report = D.diagnose(path)
            self.assertEqual("inch", report["units"])
            self.assertTrue(any("unit='inch'" in f for f in report["findings"]),
                            report["findings"])
            self.assertNotEqual("USABLE_MESH", report["classification"])

    def test_every_p_path_component_resolves_into_the_part_it_names(self) -> None:
        report = _report(self, self.FIXTURE)
        wrappers = [o for o in report["objects"] if o["components"]]
        self.assertEqual(["2", "5", "7"], sorted(o["id"] for o in wrappers))
        self.assertEqual([1, 2, 1], [len(o["components"]) for o in
                                     sorted(wrappers, key=lambda o: o["id"])])

        parts = {(o["part"], o["id"]) for o in report["objects"]}
        for wrapper in wrappers:
            for component in wrapper["components"]:
                self.assertIsNotNone(component["path"],
                                     "this export reaches every mesh through "
                                     "p:path; a component without one would mean "
                                     "the fixture changed shape")
                key = component["path"].replace("\\", "/").lstrip("/").lower()
                self.assertIn((key, component["objectid"]), parts)
                self.assertNotEqual(report["root_part"], key)
        self.assertFalse([f for f in report["findings"] if "not in the file" in f])

    def test_four_geometry_objects_three_build_items_and_the_counts_behind_them(self) -> None:
        report = _report(self, self.FIXTURE)
        self.assertEqual(7, len(report["objects"]),
                         "three wrappers in the scene part and four meshes "
                         "outside it")
        geometry = {o["id"]: o["geometry"] for o in report["objects"]
                    if o["geometry"] is not None}
        self.assertEqual(["1", "3", "4", "6"], sorted(geometry))
        self.assertEqual(4, report["bodies"])
        self.assertEqual({"1": 19276, "3": 2644, "4": 2644, "6": 89182},
                         {k: v["triangles"] for k, v in geometry.items()})
        self.assertEqual(113746, report["triangles"])

        self.assertEqual(3, len(report["build_items"]))
        self.assertTrue(all(item["resolved"] for item in report["build_items"]))
        self.assertEqual(["2", "5", "7"],
                         sorted(i["objectid"] for i in report["build_items"]))
        self.assertEqual(4, len(report["placed"]),
                         "three items, one of which places two meshes")

    def test_all_four_meshes_are_watertight_and_consistently_wound(self) -> None:
        report = _report(self, self.FIXTURE)
        for obj in report["objects"]:
            if obj["geometry"] is None:
                continue
            with self.subTest(object=obj["id"]):
                self.assertTrue(obj["geometry"]["watertight"])
                self.assertTrue(obj["geometry"]["winding_consistent"])
                self.assertEqual(0, obj["geometry"]["boundary_edges"])
                self.assertEqual(1, obj["geometry"]["bodies"])
                self.assertIsNotNone(obj["geometry"]["volume_mm3"])
        self.assertTrue(report["watertight"])
        self.assertTrue(report["winding_consistent"])

    def test_the_1_07_build_scale_reaches_the_placed_dimensions(self) -> None:
        """The number the whole fixture is here for.

        One build item carries `1.07 0 0 0 1.07 0 0 0 1`, and the two card
        retainers it places also come through a component transform that permutes
        the axes. Reporting the authored extents measures both parts 7% small on
        two axes and calls the third the wrong axis, which is exactly the class of
        error that only surfaces after the print.
        """
        report = _report(self, self.FIXTURE)
        scaled = next(i for i in report["build_items"] if i["objectid"] == "5")
        self.assertTrue(scaled["transform"].startswith("1.07 0 0 0 1.07 0 0 0 1"),
                        scaled["transform"])

        authored = {o["id"]: o["geometry"]["bbox_mm"] for o in report["objects"]
                    if o["geometry"] is not None}
        self.assertEqual([3.1, 4.1287, 23.1287], authored["3"])
        self.assertEqual([3.1, 4.1287, 13.1112], authored["4"])

        placed = {p["objectid"]: p for p in report["placed"]
                  if p["via_item"] == "5"}
        self.assertEqual(["3", "4"], sorted(placed))
        for object_id in ("3", "4"):
            with self.subTest(object=object_id):
                x, y, z = authored[object_id]
                # x -> z, y -> x, z -> y from the component transform; then 1.07
                # on the two horizontal axes from the build item.
                self.assertEqual([round(y * 1.07, 4), round(z * 1.07, 4), x],
                                 placed[object_id]["bbox_mm"])
        self.assertEqual([4.4177, 24.7477, 3.1], placed["3"]["bbox_mm"])
        self.assertEqual([4.4177, 14.029, 3.1], placed["4"]["bbox_mm"])

        # And the unscaled item stayed unscaled, so the 1.07 is being read off
        # one build item rather than applied to the scene. This one carries a
        # quarter turn about x, so its extents are permuted and not resized.
        case = next(p for p in report["placed"] if p["via_item"] == "7")
        self.assertEqual([82.6, 15.3, 169.1], authored["6"])
        self.assertEqual([82.6, 169.1, 15.3], case["bbox_mm"])
        self.assertEqual(sorted(authored["6"]), sorted(case["bbox_mm"]),
                         "a rotation permutes extents; it does not scale them")

    def test_the_scene_bbox_is_the_span_of_the_placed_geometry(self) -> None:
        """Not the largest authored object, and not their sum."""
        report = _report(self, self.FIXTURE)
        lows = [min(p["min_mm"][i] for p in report["placed"]) for i in range(3)]
        highs = [max(p["max_mm"][i] for p in report["placed"]) for i in range(3)]
        self.assertEqual([round(highs[i] - lows[i], 4) for i in range(3)],
                         report["bbox_mm"])
        self.assertEqual([226.4681, 223.5054, 15.3], report["bbox_mm"])
        self.assertIn("build transform", report["bbox_note"])

    def test_and_only_then_is_it_usable(self) -> None:
        report = _report(self, self.FIXTURE)
        self.assertEqual("USABLE_MESH", report["classification"])
        self.assertEqual([], report["findings"])
        self.assertTrue(report["scene_is_functional"])


class L0BuildTransform(unittest.TestCase):
    """2 — the smallest real file whose placed coordinates are not its authored ones.

    18 KB, one object, one build item carrying a pure translation. It costs about
    ten milliseconds and it fails the moment somebody measures raw object
    coordinates and calls the answer the scene.
    """

    FIXTURE = "oneplus-drawer-dropin"

    def test_the_placed_position_is_the_authored_mesh_moved_by_the_build_item(self) -> None:
        path = _fixture_path(self, self.FIXTURE)
        report = _report(self, self.FIXTURE)

        item, = report["build_items"]
        # Parsed here rather than through the diagnoser: a 3MF transform is
        # twelve numbers and the last three are the translation under either
        # row- or column-vector reading, so this agrees with the file without
        # borrowing the convention from the code being tested.
        numbers = [float(v) for v in item["transform"].split()]
        self.assertEqual(12, len(numbers))
        translation = [round(v, 6) for v in numbers[9:]]
        self.assertEqual([-2.240005, 70.5, 0.0], translation)

        wrapper = next(o for o in report["objects"] if o["components"])
        component, = wrapper["components"]
        part = component["path"].replace("\\", "/").lstrip("/").lower()
        low, high = _authored_bounds(path, part, component["objectid"])

        placement, = report["placed"]
        self.assertEqual([round(low[i] + translation[i], 4) for i in range(3)],
                         placement["min_mm"])
        self.assertEqual([round(high[i] + translation[i], 4) for i in range(3)],
                         placement["max_mm"])
        self.assertNotEqual([round(v, 4) for v in low], placement["min_mm"],
                            "if these agree the fixture has stopped testing "
                            "anything: the build item no longer moves the part")

    def test_the_extents_survive_a_translation_and_the_position_does_not(self) -> None:
        report = _report(self, self.FIXTURE)
        authored = next(o["geometry"]["bbox_mm"] for o in report["objects"]
                        if o["geometry"] is not None)
        placement, = report["placed"]
        self.assertEqual([60.48, 95.0, 3.4], authored)
        self.assertEqual(authored, placement["bbox_mm"],
                         "a translation moves a part; it does not resize it")
        self.assertEqual([97.76, 80.5, 0.0], placement["min_mm"])
        self.assertEqual([158.24, 175.5, 3.4], placement["max_mm"])
        self.assertEqual("USABLE_MESH", report["classification"])
        self.assertEqual([], report["findings"])


class L0Damaged(unittest.TestCase):
    """3 — a real file with real damage, and a sound object beside it.

    The interesting failure is not "does it notice". It is whether the report
    stays specific: one object is open and inconsistently wound and the other is
    fine, so a diagnosis that condemns the archive is as useless as one that
    clears it.
    """

    FIXTURE = "oneplus-case-x2d-asa"

    def test_the_geometry_is_found_before_it_is_judged(self) -> None:
        report = _report(self, self.FIXTURE)
        geometry = {o["id"]: o["geometry"] for o in report["objects"]
                    if o["geometry"] is not None}
        self.assertEqual(["1", "2"], sorted(geometry))
        self.assertEqual({"1": 93879, "2": 568},
                         {k: v["triangles"] for k, v in geometry.items()})
        self.assertEqual(94447, report["triangles"])
        self.assertEqual(2, len(report["placed"]),
                         "both objects were placed; the damaged one is still a "
                         "part of the scene")

    def test_the_defects_are_reported_with_their_counts_and_their_object(self) -> None:
        report = _report(self, self.FIXTURE)
        geometry = {o["id"]: o["geometry"] for o in report["objects"]
                    if o["geometry"] is not None}
        self.assertFalse(geometry["1"]["watertight"])
        self.assertEqual(332, geometry["1"]["boundary_edges"])
        self.assertFalse(geometry["1"]["winding_consistent"])

        self.assertTrue(any("object '1'" in f and "332 boundary edge(s)" in f
                            for f in report["findings"]), report["findings"])
        self.assertTrue(any("object '1'" in f and "winding" in f
                            for f in report["findings"]), report["findings"])

    def test_the_sound_object_is_not_condemned_with_the_broken_one(self) -> None:
        report = _report(self, self.FIXTURE)
        geometry = {o["id"]: o["geometry"] for o in report["objects"]
                    if o["geometry"] is not None}
        self.assertTrue(geometry["2"]["watertight"])
        self.assertTrue(geometry["2"]["winding_consistent"])
        self.assertEqual(0, geometry["2"]["boundary_edges"])
        self.assertFalse(any("object '2'" in f for f in report["findings"]),
                         report["findings"])

    def test_it_is_never_usable_without_qualification(self) -> None:
        report = _report(self, self.FIXTURE)
        self.assertEqual("REPAIR_REQUIRED", report["classification"])
        self.assertFalse(report["watertight"])
        self.assertIsNone(report["volume_mm3"],
                          "a scene containing an open solid has no volume, and "
                          "summing the parts that do happen to close would "
                          "produce a number that reads like one")
        damaged = next(p for p in report["placed"] if p["objectid"] == "1")
        self.assertIsNone(damaged["volume_mm3"])


class L0ComponentCycle(unittest.TestCase):
    """4 — synthetic: two wrappers that refer to each other.

    Everything a resolution check looks for is satisfied. Both ids exist, both
    parts parse, the build item resolves, nothing dangles. There is no mesh
    anywhere and following the components never terminates.
    """

    def _cycle(self, root: Path) -> Path:
        path = root / "cycle.3mf"
        model = ('<?xml version="1.0" encoding="UTF-8"?>'
                 '<model unit="millimeter" xmlns="http://schemas.microsoft.com/'
                 '3dmanufacturing/core/2015/02"><resources>'
                 '<object id="1" type="model"><components>'
                 '<component objectid="2"/></components></object>'
                 '<object id="2" type="model"><components>'
                 '<component objectid="1"/></components></object>'
                 '</resources><build><item objectid="1"/></build></model>')
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("3D/3dmodel.model", model)
        return path

    def test_a_cycle_is_reported_rather_than_walked_into_quietly(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            report = D.diagnose(self._cycle(Path(raw)))
            cycle = [f for f in report["findings"] if "cycle" in f]
            self.assertEqual(1, len(cycle), report["findings"])
            self.assertIn("object '1'", cycle[0])
            self.assertIn("object '2'", cycle[0])
            self.assertNotIn("not in the file", " ".join(report["findings"]),
                             "both ids are present; a cycle is not a dangling "
                             "reference and saying so would send the reader "
                             "looking for a missing part")

    def test_no_terminal_geometry_is_reachable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            report = D.diagnose(self._cycle(Path(raw)))
            self.assertEqual(0, report["bodies"])
            self.assertEqual([], report["placed"])
            self.assertTrue(any("no mesh anywhere" in f
                                for f in report["findings"]), report["findings"])

    def test_a_cycle_around_real_geometry_is_rejected_rather_than_cleared(self) -> None:
        """Where the finding earns its keep.

        With a mesh in the loop the scene is watertight, consistently wound, has
        nothing dangling and places a body. Every existing check clears it. The
        component chain still does not terminate, and a `MODIFY` job built on the
        assumption that it does would be assembling a scene the file does not
        describe.
        """
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "cycle_with_mesh.3mf"
            model = ('<?xml version="1.0" encoding="UTF-8"?>'
                     '<model unit="millimeter" xmlns="http://schemas.microsoft.'
                     'com/3dmanufacturing/core/2015/02"><resources>'
                     f'<object id="1" type="model">{_BOX_MESH}<components>'
                     '<component objectid="2"/></components></object>'
                     '<object id="2" type="model"><components>'
                     '<component objectid="1"/></components></object>'
                     '</resources><build><item objectid="1"/></build></model>')
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("3D/3dmodel.model", model)

            report = D.diagnose(path)
            self.assertEqual(1, report["bodies"])
            self.assertTrue(report["watertight"])
            self.assertTrue(report["winding_consistent"])
            self.assertEqual(1, len(report["placed"]))
            self.assertTrue(any("cycle" in f for f in report["findings"]),
                            report["findings"])
            self.assertEqual("REPAIR_REQUIRED", report["classification"],
                             "sound geometry inside an unassemblable scene is "
                             "not a usable mesh")

    def test_a_cycle_the_build_never_reaches_is_found_anyway(self) -> None:
        """The blind spot a build-driven walk has.

        The scene places one sound mesh. Two other objects, referenced by no
        build item at all, point at each other. A reader that looks for cycles
        only along the placement walk never visits them and reports a clean file
        -- which is the same mistake the dangling sweep was already written to
        avoid, one level down.
        """
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "unreferenced_cycle.3mf"
            model = ('<?xml version="1.0" encoding="UTF-8"?>'
                     '<model unit="millimeter" xmlns="http://schemas.microsoft.'
                     f'com/3dmanufacturing/core/2015/02"><resources>{_BOX_OBJECT}'
                     '<object id="8" type="model"><components>'
                     '<component objectid="9"/></components></object>'
                     '<object id="9" type="model"><components>'
                     '<component objectid="8"/></components></object>'
                     '</resources><build><item objectid="1"/></build></model>')
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("3D/3dmodel.model", model)

            report = D.diagnose(path)
            self.assertEqual(1, len(report["placed"]),
                             "the build still places the one real mesh")
            cycle = [f for f in report["findings"] if "cycle" in f]
            self.assertEqual(1, len(cycle), report["findings"])
            self.assertIn("object '8'", cycle[0])
            self.assertIn("object '9'", cycle[0])
            self.assertEqual("REPAIR_REQUIRED", report["classification"])

    def test_nothing_is_invented_to_fill_the_report_out(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            report = D.diagnose(self._cycle(Path(raw)))
            self.assertEqual("RECONSTRUCTION_REQUIRED", report["classification"])
            self.assertEqual([], report["bbox_mm"])
            self.assertIsNone(report["volume_mm3"])
            self.assertEqual(0, report["triangles"])
            self.assertEqual([], report["scale_suspicions"],
                             "a suspicion about a bounding box nobody has is a "
                             "measurement of nothing")


class L0RootSelection(unittest.TestCase):
    """5 — which `.model` is the scene.

    Reading whichever part comes first gets a Bambu export diagnosed from one of
    its mesh parts: no build, no materials, one anonymous object, and the placed
    size of nothing.

    The real fixture pins the relationship being followed. It does not, on its
    own, discriminate -- in every Bambu export here the root also happens to be
    the conventional path and to sort first, so a reader using either fallback
    would land on the right part by luck. The synthetic pair below removes the
    luck: the root sits at a non-conventional path that sorts *after* the mesh
    part, so only the relationship can find it.
    """

    def test_the_real_export_names_its_root_through_the_package_relationship(self) -> None:
        path = _fixture_path(self, "pixel9-card-case")
        report = _report(self, "pixel9-card-case")
        self.assertEqual(_declared_root(path), report["root_part"])
        others = [k for k in report["model_parts"] if k != report["root_part"]]
        self.assertEqual(3, len(others),
                         "three other .model parts any of which a reader could "
                         "have opened instead")

    def _awkward(self, root: Path, *, with_rels: bool) -> Path:
        """A scene part that neither convention nor ordering would choose.

        `3d/objects/mesh.model` sorts before `3d/scene.model` and is written into
        the archive first, and there is no `3d/3dmodel.model` for the
        conventional fallback to find.
        """
        core = 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'
        prod = ('xmlns:p="http://schemas.microsoft.com/3dmanufacturing/'
                'production/2015/06"')
        mesh_part = (f'<?xml version="1.0" encoding="UTF-8"?>'
                     f'<model unit="millimeter" {core} {prod}><resources>'
                     f'{_BOX_OBJECT}</resources><build/></model>')
        scene_part = (f'<?xml version="1.0" encoding="UTF-8"?>'
                      f'<model unit="millimeter" {core} {prod}><resources>'
                      f'<object id="9" name="scene" type="model"><components>'
                      f'<component p:path="/3D/Objects/mesh.model" objectid="1" '
                      f'transform="1 0 0 0 1 0 0 0 1 100 200 0"/>'
                      f'</components></object></resources>'
                      f'<build><item objectid="9"/></build></model>')
        rels = ('<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/'
                'package/2006/relationships"><Relationship '
                'Target="/3D/scene.model" Id="rel-1" '
                'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/'
                '3dmodel"/></Relationships>')
        path = root / ("with_rels.3mf" if with_rels else "without_rels.3mf")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("3D/Objects/mesh.model", mesh_part)
            archive.writestr("3D/scene.model", scene_part)
            if with_rels:
                archive.writestr("_rels/.rels", rels)
        return path

    def test_the_relationship_beats_both_the_convention_and_the_ordering(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = self._awkward(Path(raw), with_rels=True)
            with zipfile.ZipFile(path) as archive:
                models = [n for n in archive.namelist() if n.endswith(".model")]
            self.assertEqual("3D/Objects/mesh.model", models[0],
                             "the mesh part is first in the archive")
            self.assertEqual("3d/objects/mesh.model",
                             sorted(n.lower() for n in models)[0],
                             "and first in sorted order too, so neither ordering "
                             "could pick the scene")

            report = D.diagnose(path)
            self.assertEqual("3d/scene.model", report["root_part"])
            self.assertEqual(1, len(report["build_items"]))
            self.assertEqual([100.0, 200.0, 0.0],
                             report["placed"][0]["min_mm"],
                             "reading the scene means the component transform "
                             "was applied")
            self.assertEqual("USABLE_MESH", report["classification"])

    def test_without_the_relationship_the_wrong_part_is_chosen(self) -> None:
        """The negative half, which is what makes the positive half mean something.

        Strip the relationship and the fallback picks the mesh part, which
        carries no build and places nothing. Asserting this is asserting that the
        relationship is load-bearing rather than decorative.
        """
        with tempfile.TemporaryDirectory() as raw:
            report = D.diagnose(self._awkward(Path(raw), with_rels=False))
            self.assertEqual("3d/objects/mesh.model", report["root_part"])
            self.assertEqual([], report["build_items"])
            self.assertEqual([], report["placed"])
            self.assertIn("authored extent", report["bbox_note"])


class L0UntessellatableStep(unittest.TestCase):
    """6 — the vent mount: an exact B-rep nothing can turn into triangles.

    D14. `vent_mount.step` was reported `USABLE_EXACT` with no findings, and then
    every operation that needed geometry died on
    ``'NoneType' object has no attribute 'NbNodes'`` -- OCC's way of saying a face
    has a null triangulation. That is the exact failure diagnosis exists to
    prevent: the file passed the stage whose job is to say whether it can be
    worked with, and the error surfaced at a stage with less context to explain
    it.

    Face area is what the old check measured, and area is not tessellability.
    Every one of this file's 329 faces has a finite positive area -- one of them
    is 1.75e-14 mm2, which is small and is not zero -- so `invalid_faces` was 0
    and stayed 0 whatever the mesher could do.

    The facts are asserted, not the verdict, as everywhere else in this file: the
    count of untessellatable faces, the surface type OCC named, and that the
    finding says what a reader has to do about it. A test asserting only
    `REPAIR_REQUIRED` would pass on any wrong reason at all.
    """

    FIXTURE = "vent-ball-combine"

    def _report(self) -> dict:
        return _report(self, self.FIXTURE)

    def test_the_faces_that_cannot_be_tessellated_are_counted(self) -> None:
        report = self._report()
        self.assertEqual("STEP", report["format"])
        self.assertEqual(329, report["faces"])
        self.assertGreater(report["untessellatable_faces"], 0,
                           "a file whose cone faces defeat every mesher this "
                           "runtime has must not be reported clean")
        self.assertEqual(report["untessellatable_faces"],
                         len(report["tessellation"]["failures"]))
        self.assertEqual(report["faces"],
                         report["tessellation"]["faces"])
        self.assertEqual(report["faces"] - report["untessellatable_faces"],
                         report["tessellation"]["tessellated_faces"])

    def test_the_area_test_alone_would_still_call_this_file_clean(self) -> None:
        """Why the new probe had to be added rather than the old one tightened."""
        report = self._report()
        self.assertEqual(0, report["invalid_faces"],
                         "every face has a finite positive area; if this ever "
                         "becomes non-zero the area test has started catching "
                         "this file and this fixture is measuring something else")

    def test_the_finding_names_the_faces_and_the_deflection(self) -> None:
        report = self._report()
        finding = next((f for f in report["findings"]
                        if "cannot be tessellated" in f), None)
        self.assertIsNotNone(finding, report["findings"])
        self.assertIn("CONE", finding,
                      "the surface type is what tells a repairer where to look")
        self.assertIn(str(report["tessellation"]["linear_deflection"]), finding,
                      "a tessellation failure is only a fact against a deflection")

    def test_it_is_not_usable_as_it_stands(self) -> None:
        self.assertEqual("REPAIR_REQUIRED", self._report()["classification"])


if __name__ == "__main__":
    unittest.main()
