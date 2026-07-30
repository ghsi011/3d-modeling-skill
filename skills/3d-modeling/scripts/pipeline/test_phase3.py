#!/usr/bin/env python3
"""Phase 3: modifying a supplied artifact, and proving the rest survived.

Two things had nothing measuring them before this phase.

**What the supplied file actually is.** `MODIFY` was advice -- "treat the file as
geometry to inspect" -- and inspecting by eye is how a model in inches gets
scaled by nobody. `design-tool diagnose` measures it and classifies what can be
built on it, without ever writing to it.

**That nothing outside the edit moved.** A model rebuilt from scratch to add one
boss passes every other check in the pipeline. The edit scope names a region
before the edit; the preservation audit measures everything outside it and
reports the method, because a sampled comparison cannot establish exact
preservation and must not say it did.
"""
from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path

import numpy as np
import trimesh

from . import cli
from . import commission as CM
from . import diagnose as D
from . import preservation as PR
from . import project as P
from . import route as RT

UTC = "1970-01-01T00:00:00Z"

# The vent-mount case, reduced to its geometry: a supplied bracket (a 50x30x8
# plate with a 20 mm boss) that has to gain a 17 mm ball socket on the boss face
# while the plate, its screw holes and its outline stay exactly as supplied.
VENT_MOUNT_BOSS = (35.0, 15.0)          # where the boss stands on the plate
BALL_D = 17.0


def _vent_mount() -> trimesh.Trimesh:
    plate = trimesh.creation.box(extents=(50.0, 30.0, 8.0))
    plate.apply_translation((25.0, 15.0, 4.0))
    boss = trimesh.creation.cylinder(radius=10.0, height=12.0, sections=96)
    boss.apply_translation((VENT_MOUNT_BOSS[0], VENT_MOUNT_BOSS[1], 14.0))
    holes = []
    for x in (8.0, 42.0):
        hole = trimesh.creation.cylinder(radius=2.5, height=20.0, sections=48)
        hole.apply_translation((x, 15.0, 4.0))
        holes.append(hole)
    body = trimesh.boolean.union([plate, boss], engine="manifold")
    return trimesh.boolean.difference([body, *holes], engine="manifold")


# The model the designer writes: import the supplied bracket, cut the socket,
# change nothing else. Its expectations are the closed form of what it added and
# of what it inherited.
MODIFIER = '''
import trimesh

PARAMS = {{"ball_d": {ball_d}, "socket_x": {bx}, "socket_y": {by}}}
BBOX_MM = {{"x": 50.0, "y": 30.0, "z": 20.0}}
BODIES = 1
PROFILE_MARKS = {{"z": [8.0]}}
EXPECTED = [
    {{"feature_id": "plate-section", "kind": "section_area",
     "at": {{"z": 4.0}}, "value_mm2": 50.0 * 30.0 - 2 * 3.14159265 * 2.5 ** 2}},
]


def build():
    source = trimesh.load(r"{source}", force="mesh")
    # A blind seat bored straight down into the boss: vertical walls and an
    # upward-facing floor, so it needs no support. A spherical socket of the same
    # diameter would leave an unsupported ceiling, which is a print-engineering
    # decision rather than a modelling one -- see the BALL_SOCKET fixture.
    seat = trimesh.creation.cylinder(radius={ball_d} / 2.0, height=16.0, sections=96)
    seat.apply_translation(({bx}, {by}, 16.0))
    return trimesh.boolean.difference([source, seat], engine="manifold")
'''

# The same edit written by somebody who redrew the bracket instead of importing
# it, and got the plate 0.6 mm thicker on the way.
REDRAWN = '''
import trimesh

PARAMS = {{"ball_d": {ball_d}}}
BBOX_MM = {{"x": 50.0, "y": 30.0, "z": 20.6}}
BODIES = 1
PROFILE_MARKS = {{"z": [8.6]}}
EXPECTED = [
    {{"feature_id": "plate-section", "kind": "section_area",
     "at": {{"z": 4.0}}, "value_mm2": 50.0 * 30.0 - 2 * 3.14159265 * 2.5 ** 2}},
]


def build():
    plate = trimesh.creation.box(extents=(50.0, 30.0, 8.6))
    plate.apply_translation((25.0, 15.0, 4.3))
    boss = trimesh.creation.cylinder(radius=10.0, height=12.0, sections=96)
    boss.apply_translation(({bx}, {by}, 14.3))
    holes = []
    for x in (8.0, 42.0):
        hole = trimesh.creation.cylinder(radius=2.5, height=20.0, sections=48)
        hole.apply_translation((x, 15.0, 4.3))
        holes.append(hole)
    body = trimesh.boolean.union([plate, boss], engine="manifold")
    body = trimesh.boolean.difference([body, *holes], engine="manifold")
    seat = trimesh.creation.cylinder(radius={ball_d} / 2.0, height=16.0, sections=96)
    seat.apply_translation(({bx}, {by}, 16.3))
    return trimesh.boolean.difference([body, seat], engine="manifold")
'''


# --- 3MF fixtures -----------------------------------------------------------
# Written here rather than read from a real slicer export: the real files are
# licensed third-party content living outside the repo, and a test that reads
# them is neither portable nor reproducible.
CORE_NS = 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'
PROD_NS = ('xmlns:p="http://schemas.microsoft.com/3dmanufacturing/'
           'production/2015/06"')
ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
    'relationships"><Relationship Target="/3D/3dmodel.model" Id="rel-1" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    '</Relationships>')


def _mesh_xml(mesh: trimesh.Trimesh) -> str:
    vertices = "".join(f'<vertex x="{x:.6g}" y="{y:.6g}" z="{z:.6g}"/>'
                       for x, y, z in mesh.vertices)
    triangles = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>'
                        for a, b, c in mesh.faces)
    return (f"<mesh><vertices>{vertices}</vertices>"
            f"<triangles>{triangles}</triangles></mesh>")


def _model_part(resources: str, build: str = "<build/>") -> str:
    return (f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<model unit="millimeter" {CORE_NS} {PROD_NS} '
            f'requiredextensions="p"><resources>{resources}</resources>'
            f'{build}</model>')


def _production_3mf(path: Path, *, button_transform: str = "1 0 0 0 1 0 0 0 1 0 0 0",
                    parts: dict[str, str] | None = None) -> Path:
    """A 3MF in the shape Bambu Studio writes it.

    The root part carries nothing but the scene; every mesh lives in its own
    `3D/Objects/object_NN.model` and is reached through a component's `p:path`.
    The mesh parts are written into the archive *first*, so a reader that takes
    whichever `.model` the zip lists first lands on a mesh part rather than the
    scene.
    """
    if parts is None:
        case = trimesh.creation.box(extents=(60.0, 10.0, 120.0))
        button = trimesh.creation.box(extents=(3.0, 4.0, 9.0))
        parts = {
            "3D/Objects/object_1.model": _model_part(
                f'<object id="1" type="model">{_mesh_xml(case)}</object>'),
            "3D/Objects/object_2.model": _model_part(
                f'<object id="2" type="model">{_mesh_xml(button)}</object>'
                f'<object id="3" type="model">{_mesh_xml(button)}</object>'),
            "3D/3dmodel.model": _model_part(
                '<object id="10" type="model" name="case"><components>'
                '<component p:path="/3D/Objects/object_1.model" objectid="1" '
                'transform="1 0 0 0 1 0 0 0 1 0 0 0"/></components></object>'
                '<object id="20" type="model" name="buttons"><components>'
                '<component p:path="/3D/Objects/object_2.model" objectid="2"/>'
                '<component p:path="/3D/Objects/object_2.model" objectid="3" '
                'transform="1 0 0 0 1 0 0 0 1 0 8 0"/>'
                '</components></object>',
                '<build><item objectid="10"/>'
                f'<item objectid="20" transform="{button_transform}"/></build>'),
        }
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in parts.items():
            archive.writestr(name, text)
        archive.writestr("_rels/.rels", ROOT_RELS)
    return path


def _edit_scope() -> P.EditScope:
    """The socket region, declared before the edit."""
    return P.EditScope(
        artifact_id="bracket", region="the boss face socket",
        region_box={"min": [VENT_MOUNT_BOSS[0] - 12.0, VENT_MOUNT_BOSS[1] - 12.0, 8.0],
                    "max": [VENT_MOUNT_BOSS[0] + 12.0, VENT_MOUNT_BOSS[1] + 12.0, 32.0]},
        preserve=("the plate, its outline and both screw holes",),
        add=("a 17 mm ball socket in the boss face",))


def _modify_project(**over) -> P.Project:
    base = dict(
        job_id="vent-mount", updated_utc=UTC, source_mode="MODIFY",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a phone mount arm; failure drops a phone, not a person",
        printer="Test Printer", material={"process": "FDM", "material": "PETG"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        model="model.py", envelope_mm={"x": 50.0, "y": 30.0, "z": 21.0},
        source_artifacts=(P.SourceArtifact(
            artifact_id="bracket", path="bracket.stl", format="STL",
            classification="USABLE_MESH"),),
        edit_scope=_edit_scope(),
    )
    base.update(over)
    return P.Project(**base)


def _laid_out(root: Path, source_template: str | None, project: P.Project) -> Path:
    directory = root / "project"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "brief.md").write_text(
        "add a 17 mm ball socket to the supplied vent bracket", encoding="utf-8")
    bracket = directory / "bracket.stl"
    _vent_mount().export(bracket)
    if source_template is not None:
        (directory / "model.py").write_text(
            textwrap.dedent(source_template).format(
                ball_d=BALL_D, bx=VENT_MOUNT_BOSS[0], by=VENT_MOUNT_BOSS[1],
                source=str(bracket).replace("\\", "\\\\")),
            encoding="utf-8")
    project.save(directory)
    return directory


class DiagnoseTest(unittest.TestCase):
    def test_a_sound_mesh_is_usable_and_nothing_is_written_to_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "bracket.stl"
            _vent_mount().export(path)
            before = path.read_bytes()

            report = D.diagnose(path)
            self.assertEqual("USABLE_MESH", report["classification"])
            self.assertEqual("STL", report["format"])
            self.assertTrue(report["watertight"])
            self.assertEqual(1, report["bodies"])
            self.assertEqual([], report["findings"])
            self.assertIsNone(report["units"],
                              "STL carries no units and the report must not "
                              "invent them")
            self.assertEqual(before, path.read_bytes(),
                             "diagnosis must never write to the only "
                             "authoritative copy")

    def test_a_mesh_with_holes_needs_repair_and_says_how_many(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            mesh = _vent_mount()
            mesh.update_faces(np.arange(len(mesh.faces)) > 20)
            path = Path(raw) / "damaged.stl"
            mesh.export(path)

            report = D.diagnose(path)
            self.assertEqual("REPAIR_REQUIRED", report["classification"])
            self.assertFalse(report["watertight"])
            self.assertGreater(report["boundary_edges"], 0)
            self.assertTrue(any("watertight" in f for f in report["findings"]))

    def test_an_empty_mesh_cannot_be_built_on(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "empty.stl"
            path.write_bytes(b"solid empty\nendsolid empty\n")
            self.assertEqual("RECONSTRUCTION_REQUIRED",
                             D.diagnose(path)["classification"])

    def test_an_inch_model_is_suspected_and_never_converted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            mesh = trimesh.creation.box(extents=(25.4, 50.8, 76.2))
            path = Path(raw) / "inches.stl"
            mesh.export(path)
            report = D.diagnose(path)
            self.assertTrue(any("25.4" in s for s in report["scale_suspicions"]))
            self.assertEqual([25.4, 50.8, 76.2], report["bbox_mm"],
                             "the bbox is reported as authored; a conversion "
                             "nobody asked for is a silent edit")

    def test_a_multi_component_3mf_reports_the_scene_not_a_merged_solid(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "two_up.3mf"
            body = _mesh_xml(trimesh.creation.box(extents=(20.0, 20.0, 10.0)))
            lid = _mesh_xml(trimesh.creation.box(extents=(20.0, 20.0, 3.0)))
            model = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<model unit="millimeter" '
                'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
                '<resources>'
                '<basematerials id="9">'
                '<base name="PETG Black" displaycolor="#101010FF"/>'
                '<base name="PETG Red" displaycolor="#C01010FF"/>'
                '</basematerials>'
                f'<object id="1" name="body" type="model" pid="9">{body}</object>'
                f'<object id="2" name="lid" type="model" pid="9">{lid}</object>'
                '</resources>'
                '<build>'
                '<item objectid="1"/>'
                '<item objectid="2" transform="1 0 0 0 1 0 0 0 1 60 0 0"/>'
                '</build></model>')
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("3D/3dmodel.model", model)

            report = D.diagnose(path)
            self.assertEqual("3MF", report["format"])
            self.assertEqual("millimeter", report["units"])
            self.assertEqual(2, report["bodies"])
            self.assertEqual(["body", "lid"], [o["name"] for o in report["objects"]])
            self.assertEqual(2, len(report["materials"]))
            self.assertTrue(report["scene_is_functional"])
            self.assertEqual("USABLE_MESH", report["classification"])
            self.assertEqual([], report["findings"])

    def test_a_production_extension_3mf_is_not_reported_as_broken(self) -> None:
        """The defect this branch exists to answer.

        Bambu Studio keeps every mesh in its own part and reaches it through a
        component's `p:path`. A reader that opens one part and resolves ids
        against it alone sees three components pointing at ids it cannot find,
        and tells the user an intact, watertight, winding-consistent file needs
        repair -- which is worse than saying nothing.
        """
        with tempfile.TemporaryDirectory() as raw:
            path = _production_3mf(Path(raw) / "production.3mf")
            before = path.read_bytes()

            report = D.diagnose(path)
            self.assertEqual("USABLE_MESH", report["classification"])
            self.assertEqual([], report["findings"])
            self.assertEqual("3d/3dmodel.model", report["root_part"],
                             "the scene is named by the package relationship, "
                             "not by whichever part the zip lists first")
            self.assertEqual(3, report["bodies"],
                             "one case and two buttons, each in a mesh part the "
                             "root only points at")
            self.assertEqual(3, len(report["model_parts"]),
                             "the scene part and both mesh parts were all read")
            self.assertTrue(report["watertight"])
            self.assertTrue(report["winding_consistent"])
            self.assertEqual(before, path.read_bytes(),
                             "diagnosis must never write to the only "
                             "authoritative copy")

    def test_a_component_that_resolves_nowhere_is_still_dangling(self) -> None:
        """The check is narrowed, not removed: a genuinely broken file still fails."""
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "dangling.3mf"
            box = _mesh_xml(trimesh.creation.box(extents=(10.0, 10.0, 10.0)))
            _production_3mf(path, parts={
                "3D/Objects/object_1.model": _model_part(
                    f'<object id="1" type="model">{box}</object>'),
                # id 2 is here; id 3 is in neither this part nor the root.
                "3D/Objects/object_2.model": _model_part(
                    f'<object id="2" type="model">{box}</object>'),
                "3D/3dmodel.model": _model_part(
                    '<object id="10" type="model" name="case"><components>'
                    '<component p:path="/3D/Objects/object_1.model" objectid="1"/>'
                    '</components></object>'
                    '<object id="20" type="model" name="buttons"><components>'
                    '<component p:path="/3D/Objects/object_2.model" objectid="2"/>'
                    '<component p:path="/3D/Objects/object_2.model" objectid="3"/>'
                    '</components></object>',
                    '<build><item objectid="10"/><item objectid="20"/></build>'),
            })

            report = D.diagnose(path)
            self.assertEqual("REPAIR_REQUIRED", report["classification"])
            finding = next(f for f in report["findings"] if "not in the file" in f)
            self.assertIn("'3'", finding)
            self.assertNotIn("'2'", finding,
                             "an id that resolves through p:path is not dangling")

    def test_a_build_transform_is_applied_to_the_placed_geometry(self) -> None:
        """A 1.07 on the build item makes the part 7% bigger than its mesh part.

        Reporting the authored numbers as if they were the placed ones measures
        every scaled part undersize, which is the sort of error that only shows
        up after the print.
        """
        with tempfile.TemporaryDirectory() as raw:
            path = _production_3mf(Path(raw) / "scaled.3mf",
                                   button_transform="1.07 0 0 0 1.07 0 0 0 1 0 0 0")
            report = D.diagnose(path)

            authored = {o["id"]: o["geometry"]["bbox_mm"]
                        for o in report["objects"] if o["geometry"]}
            self.assertEqual([3.0, 4.0, 9.0], authored["2"],
                             "the object's own mesh is reported as authored")

            buttons = [p for p in report["placed"] if p["via_item"] == "20"]
            self.assertEqual(2, len(buttons))
            for placement in buttons:
                self.assertEqual([round(3.0 * 1.07, 4), round(4.0 * 1.07, 4), 9.0],
                                 placement["bbox_mm"])
            # The unscaled item is untouched, so the transform is being read
            # rather than applied to everything.
            case = next(p for p in report["placed"] if p["via_item"] == "10")
            self.assertEqual([60.0, 10.0, 120.0], case["bbox_mm"])

    def test_a_3mf_answers_the_same_geometry_questions_a_mesh_does(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = _production_3mf(Path(raw) / "geometry.3mf")
            report = D.diagnose(path)

            case = next(o for o in report["objects"] if o["id"] == "1")
            self.assertEqual(12, case["geometry"]["triangles"])
            self.assertEqual(1, case["geometry"]["bodies"])
            self.assertTrue(case["geometry"]["watertight"])
            self.assertTrue(case["geometry"]["winding_consistent"])
            self.assertAlmostEqual(60.0 * 10.0 * 120.0,
                                   case["geometry"]["volume_mm3"], places=3)
            self.assertEqual(0, case["geometry"]["boundary_edges"])
            self.assertEqual(36, report["triangles"])
            self.assertIn("build transform", report["bbox_note"])
            # The case is 10 mm deep and centred; the second button's component
            # transform pushes it out to y=+10, so the assembled scene is 15 mm
            # deep. A report that only looked at the case would say 10.
            self.assertEqual([60.0, 15.0, 120.0], report["bbox_mm"])

    def test_an_open_mesh_inside_a_3mf_needs_repair_and_says_which_object(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            holed = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
            holed.update_faces(np.arange(len(holed.faces)) > 1)
            path = Path(raw) / "open.3mf"
            _production_3mf(path, parts={
                "3D/Objects/object_1.model": _model_part(
                    f'<object id="1" type="model">{_mesh_xml(holed)}</object>'),
                "3D/3dmodel.model": _model_part(
                    '<object id="10" type="model" name="case"><components>'
                    '<component p:path="/3D/Objects/object_1.model" objectid="1"/>'
                    '</components></object>',
                    '<build><item objectid="10"/></build>'),
            })

            report = D.diagnose(path)
            self.assertEqual("REPAIR_REQUIRED", report["classification"])
            self.assertFalse(report["watertight"])
            self.assertTrue(any("object '1'" in f and "not watertight" in f
                                for f in report["findings"]), report["findings"])
            self.assertIsNone(report["volume_mm3"])
            self.assertFalse(any("not in the file" in f
                                 for f in report["findings"]),
                             "an open mesh is an open mesh, not a dangling id")

    def test_a_3mf_in_the_wrong_unit_is_a_repair_finding_not_a_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "inch.3mf"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("3D/3dmodel.model",
                                 '<model unit="inch" xmlns="http://schemas.'
                                 'microsoft.com/3dmanufacturing/core/2015/02">'
                                 '<resources><object id="1"><mesh/></object>'
                                 '</resources><build/></model>')
            report = D.diagnose(path)
            self.assertEqual("inch", report["units"])
            self.assertEqual("REPAIR_REQUIRED", report["classification"])

    def test_a_scene_of_component_wrappers_carries_no_geometry_to_build_on(self) -> None:
        """Resolving is not the same as containing something.

        Two objects whose components point at each other parse cleanly and leave
        no dangling id -- and there is still no mesh anywhere in the archive.
        Fail closed rather than call an empty scene usable.
        """
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "wrappers.3mf"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("3D/3dmodel.model", _model_part(
                    '<object id="1" type="model"><components>'
                    '<component objectid="2"/></components></object>'
                    '<object id="2" type="model"><components>'
                    '<component objectid="1"/></components></object>',
                    '<build><item objectid="1"/></build>'))

            report = D.diagnose(path)
            self.assertEqual("RECONSTRUCTION_REQUIRED", report["classification"])
            self.assertEqual(0, report["bodies"])
            self.assertTrue(any("no mesh anywhere" in f
                                for f in report["findings"]), report["findings"])

    def test_the_cli_exits_nonzero_only_when_nothing_can_be_built_on_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            good = Path(raw) / "bracket.stl"
            _vent_mount().export(good)
            bad = Path(raw) / "empty.stl"
            bad.write_bytes(b"solid empty\nendsolid empty\n")
            self.assertEqual(0, cli.diagnose([str(good)]))
            self.assertEqual(1, cli.diagnose([str(bad)]))


class PreservationTest(unittest.TestCase):
    def test_an_edit_inside_its_region_preserves_everything_outside(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source_path = root / "bracket.stl"
            source = _vent_mount()
            source.export(source_path)

            ball = trimesh.creation.icosphere(radius=BALL_D / 2.0, subdivisions=3)
            ball.apply_translation((*VENT_MOUNT_BOSS, 20.0))
            edited = trimesh.boolean.difference([source, ball], engine="manifold")
            candidate_path = root / "candidate.stl"
            edited.export(candidate_path)

            region = PR.Region.from_declaration(_edit_scope().region_box)
            report = PR.audit(source_path=source_path,
                              candidate_path=candidate_path, region=region)
            self.assertEqual("PRESERVED_WITHIN_TOLERANCE", report["verdict"])
            self.assertIn("sampled", report["method"])
            self.assertIn("cannot establish exact preservation",
                          report["claim_note"])

    def test_a_redraw_that_moved_the_plate_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source_path = root / "bracket.stl"
            _vent_mount().export(source_path)

            thicker = trimesh.creation.box(extents=(50.0, 30.0, 8.6))
            thicker.apply_translation((25.0, 15.0, 4.3))
            candidate_path = root / "candidate.stl"
            thicker.export(candidate_path)

            region = PR.Region.from_declaration(_edit_scope().region_box)
            report = PR.audit(source_path=source_path,
                              candidate_path=candidate_path, region=region)
            self.assertEqual("CHANGED", report["verdict"])
            self.assertGreater(report["max_deviation_mm"], 0.05)
            self.assertIsNotNone(report["worst_point_mm"])

    def test_without_a_region_the_audit_says_unmeasurable_rather_than_passing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "bracket.stl"
            _vent_mount().export(path)
            report = PR.audit(source_path=path, candidate_path=path, region=None)
            self.assertEqual("UNMEASURABLE", report["verdict"])
            self.assertIn("no region box", report["reason"])

    def test_exact_is_a_claim_about_the_inputs_not_about_the_extension(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "bracket.stl"
            _vent_mount().export(path)
            region = PR.Region.from_declaration(_edit_scope().region_box)
            sampled = PR.audit(source_path=path, candidate_path=path, region=region)
            declared = PR.audit(source_path=path, candidate_path=path,
                                region=region, exact=True)
            self.assertEqual("PRESERVED_WITHIN_TOLERANCE", sampled["verdict"])
            self.assertEqual("PRESERVED_EXACTLY", declared["verdict"])
            self.assertEqual(sampled["method"], declared["method"],
                             "the measurement is the same; what `exact` buys is "
                             "the right to read it as a statement about geometry")


class ModifyRouteTest(unittest.TestCase):
    def test_a_trusted_artifact_with_an_edit_scope_routes_custom(self) -> None:
        decision = RT.decide(_modify_project())
        self.assertEqual("CUSTOM", decision.route)
        self.assertIn("modified", decision.condition)
        self.assertFalse(decision.requires_verification,
                         "a trusted artifact needing no repair is not, by itself, "
                         "a reason to spend a fresh context")

    def test_an_artifact_needing_repair_escalates(self) -> None:
        project = _modify_project(source_artifacts=(P.SourceArtifact(
            artifact_id="bracket", path="bracket.stl", format="STL",
            classification="REPAIR_REQUIRED"),))
        decision = RT.decide(project)
        self.assertEqual("CUSTOM", decision.route)
        self.assertTrue(decision.requires_verification)
        self.assertTrue(any("repair" in reason for reason in decision.escalations))

    def test_an_artifact_that_cannot_be_built_on_routes_fitted(self) -> None:
        project = _modify_project(source_artifacts=(P.SourceArtifact(
            artifact_id="bracket", path="bracket.stl", format="STL",
            classification="RECONSTRUCTION_REQUIRED"),))
        self.assertEqual("FITTED", RT.decide(project).route)

    def test_an_edit_scope_without_a_region_box_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = _modify_project(edit_scope=P.EditScope(
                artifact_id="bracket", region="the boss face"))
            directory = _laid_out(Path(raw), None, project)
            problems = P.load(directory).validate(directory)
            self.assertTrue(any("region_box" in p for p in problems), problems)


class ModifyLaneTest(unittest.TestCase):
    def _checks(self, directory: Path) -> dict:
        report = json.loads(
            (directory / "commission_report.json").read_text(encoding="utf-8"))
        return {c["check_id"]: c for c in report["checks"]} | {"_report": report}

    def test_an_edit_that_stays_in_its_region_passes_the_preservation_gate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), MODIFIER, _modify_project())
            cli.run([str(directory), "--no-render"])
            checks = self._checks(directory)
            self.assertIn("feature-preservation", checks,
                          "a MODIFY job with an edit scope must carry the row")
            check = checks["feature-preservation"]
            self.assertEqual("PASS", check["result"], check)
            self.assertEqual("PRESERVED_WITHIN_TOLERANCE",
                             check["measured"]["verdict"])
            self.assertEqual("PASS", checks["_report"]["verdict"],
                             checks["_report"]["checks"])

    def test_the_support_ceiling_is_inherited_from_the_supplied_artifact(self) -> None:
        """A modification did not choose the geometry it inherited.

        A generated zero-support ceiling fails a supplied part for overhangs
        that were in the file before anybody touched it, and the designer cannot
        chamfer them away without redrawing the part -- which is the one thing a
        modification must not do. So the ceiling is the source artifact's own
        measurement, taken from a file that was fixed before the job started.
        Any overhang the edit *adds* still fails.
        """
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), MODIFIER, _modify_project())
            cli.run([str(directory), "--no-render"])
            contract = json.loads(
                (directory / "model_contract.json").read_text(encoding="utf-8"))
            support = next(f for f in contract["features"]
                           if f["feature_id"].startswith("plan-support"))
            self.assertGreater(support["expectation"]["max_area_mm2"], 0.0,
                               "the inherited allowance was not measured")
            self.assertIn("inherited from bracket.stl", support["provenance"])
            self.assertIn("measured before the edit", support["provenance"])

    def test_a_redraw_fails_the_job_even_though_it_looks_right(self) -> None:
        """Every other check passes. This is the one that catches it."""
        with tempfile.TemporaryDirectory() as raw:
            directory = _laid_out(Path(raw), REDRAWN, _modify_project(
                envelope_mm={"x": 50.0, "y": 30.0, "z": 21.0}))
            code = cli.run([str(directory), "--no-render"])
            checks = self._checks(directory)
            self.assertEqual("FAIL", checks["feature-preservation"]["result"])
            self.assertEqual("CHANGED",
                             checks["feature-preservation"]["measured"]["verdict"])
            self.assertEqual("FAIL", checks["_report"]["verdict"])
            self.assertEqual(1, code)
            final = json.loads(
                (directory / "final_status.json").read_text(encoding="utf-8"))
            self.assertEqual("FAILED", final["final_status"])

    def test_a_missing_source_artifact_escalates_rather_than_passing(self) -> None:
        """No source, no comparison -- and silence is not a pass.

        Exercised at the check rather than through a run: a model that imports
        the artifact cannot build without it either, so a run would stop earlier
        and never reach the question this check answers.
        """
        from . import analysis
        from .contract import Feature

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            candidate = root / "candidate.stl"
            _vent_mount().export(candidate)
            ctx = analysis.load(candidate)
            feature = Feature(
                feature_id="preservation", kind="preservation",
                provenance="the edit scope", tolerance={"abs": 0.0},
                verified_by="preservation", on_unrunnable="ESCALATE",
                expectation={"source": "bracket.stl",
                             "region": _edit_scope().region_box,
                             "tolerance_mm": 0.05})
            check = CM._feature_check(ctx, feature, None)
            self.assertEqual("ESCALATE", check.result)
            self.assertEqual("SOURCE_MISSING", check.error_code)
            self.assertEqual("UNAVAILABLE", check.status)


if __name__ == "__main__":
    unittest.main()
