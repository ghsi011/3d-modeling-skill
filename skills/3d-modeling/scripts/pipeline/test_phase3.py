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

The half of this file the commit gate will not carry is in
`benchmarks/heavy/test_phase3_heavy.py`, and runs before merge instead of on
every push: `DeterministicEvidenceTest`, `MemoryCeilingTest`,
`ModifyCleanCloneTest`, `ModifyLaneTest`, `ModifyRerunRejectionTest`,
`ModifyReviewRoundTripTest`, `PreservationTest`, `StepSourceTest`,
`TwoScopeModifyTest`, `UnreadableSourceIsNamedInTheVerdictTest`. Same tests,
moved rather than weakened; `conftest.py` carries the rule and
`benchmarks/heavy/README.md` the measurement behind it.
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path

import numpy as np
import trimesh

from . import acceptance as ACC
from . import cli
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
# change nothing else. What it must measure is the proposal beside it, frozen
# before this file is executed -- the closed form of what it added and of what it
# inherited.
MODIFIER = '''
import trimesh

PARAMS = {{"ball_d": {ball_d}, "socket_x": {bx}, "socket_y": {by}}}


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

# The plate as supplied, less its two screw shanks. The closed form, and the one
# thing this edit inherits rather than adds.
_PLATE_SECTION = 50.0 * 30.0 - 2 * 3.14159265 * 2.5 ** 2

MODIFIER_PROPOSAL = {
    "schema_version": 1,
    "job_id": "vent-mount",
    "design_id": "vent-mount-ball-socket",
    "rationale": "a 17 mm seat bored into the supplied bracket's boss face",
    "params": {"ball_d": BALL_D, "socket_x": VENT_MOUNT_BOSS[0],
               "socket_y": VENT_MOUNT_BOSS[1]},
    "bbox_mm": {"x": 50.0, "y": 30.0, "z": 20.0},
    "bodies": 1,
    "profile_marks": {"z": [8.0]},
    "features": [
        {"feature_id": "plate-section", "kind": "section_area",
         "at": {"z": 4.0}, "value_mm2": _PLATE_SECTION},
    ],
}

# What the redrawer proposed, which is a plate 0.6 mm thicker than the one they
# were given. The proposal is internally consistent; the preservation audit is
# what notices that it is not the supplied artifact.
REDRAWN_PROPOSAL = {
    **MODIFIER_PROPOSAL,
    "design_id": "vent-mount-ball-socket-redrawn",
    "params": {"ball_d": BALL_D},
    "bbox_mm": {"x": 50.0, "y": 30.0, "z": 20.6},
    "profile_marks": {"z": [8.6]},
}


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
        edit_scopes=(_edit_scope(),),
    )
    base.update(over)
    return P.Project(**base)


def _laid_out(root: Path, source_template: str | None, project: P.Project,
              proposal: dict | None = None) -> Path:
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
        (directory / ACC.PROPOSAL_FILE).write_text(
            json.dumps(proposal or MODIFIER_PROPOSAL, indent=2, sort_keys=True),
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
            project = _modify_project(edit_scopes=(P.EditScope(
                artifact_id="bracket", region="the boss face"),))
            directory = _laid_out(Path(raw), None, project)
            problems = P.load(directory).validate(directory)
            self.assertTrue(any("region_box" in p.message for p in problems), problems)


def _store_passing_answer(directory: Path) -> dict:
    """Write the answer the run just asked for, echoing its envelope unchanged."""
    packet = json.loads((directory / "reviews" / "verification_packet.json")
                        .read_text(encoding="utf-8"))
    (directory / "reviews" / "verification_response.json").write_text(
        json.dumps({
            "decision": "PASS", "defects": [], "unmet_requirements": [],
            "missing_evidence": [],
            "summary": "everything outside the declared region is as supplied",
            "review_envelope": packet["review_envelope"],
        }, indent=2), encoding="utf-8")
    return packet


# --- the two-artifact case --------------------------------------------------
# Two supplied plates, one magnet pocket cut into each, declared as two edit
# scopes over one interface. Every multi-scope test in `test_phase1.py` is
# schema and validation only; no multi-scope job has ever been run.

TWO_PLATE_MODEL = '''
import trimesh

PARAMS = {{"seat_d": 8.0}}


def build():
    left = trimesh.load(r"{left}", force="mesh")
    right = trimesh.load(r"{right}", force="mesh")
    body = trimesh.boolean.union([left, right], engine="manifold")
    for x in (10.0, 50.0):
        cut = trimesh.creation.cylinder(radius=4.0, height=20.0, sections=64)
        cut.apply_translation((x, 10.0, 10.0))
        body = trimesh.boolean.difference([body, cut], engine="manifold")
    return body
'''

TWO_PLATE_PROPOSAL = {
    "schema_version": 1, "job_id": "two-scopes", "design_id": "two-plates",
    "rationale": "one magnet pocket in each of two supplied plates",
    "params": {"seat_d": 8.0},
    "bbox_mm": {"x": 60.0, "y": 20.0, "z": 12.0}, "bodies": 2,
    "profile_marks": {"z": [6.0]},
    "features": [
        {"feature_id": "plate-section", "kind": "section_area",
         "at": {"z": 6.0}, "value_mm2": 2 * (400.0 - 3.14159265 * 16.0)},
    ],
}

TWO_PLATE_INTERFACE = P.Interface(
    interface_id="magnet-pockets", kind="magnet pocket", external=False,
    owner="this job", note="one feature cut in two places")

LEFT_BOX = {"min": [4.0, 4.0, 4.0], "max": [16.0, 16.0, 14.0]}
RIGHT_BOX = {"min": [44.0, 4.0, 4.0], "max": [56.0, 16.0, 14.0]}


def _plate(x0: float) -> trimesh.Trimesh:
    plate = trimesh.creation.box(extents=(20.0, 20.0, 12.0))
    plate.apply_translation((x0 + 10.0, 10.0, 6.0))
    return plate


def _two_scope_project() -> P.Project:
    return P.Project(
        job_id="two-scopes", updated_utc=UTC, source_mode="MODIFY",
        consequence="INCONSEQUENTIAL",
        consequence_rationale="a bench fixture; failure drops nothing",
        printer="Test Printer", material={"process": "FDM", "material": "PETG"},
        nozzle={"diameter_mm": 0.4},
        orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
        model="model.py", envelope_mm={"x": 60.0, "y": 20.0, "z": 12.0},
        verification_requested=True,
        reviewer={"model_snapshot": "test", "fresh_context": True},
        interfaces=(TWO_PLATE_INTERFACE,),
        source_artifacts=(
            P.SourceArtifact(artifact_id="left", path="left.stl", format="STL",
                             classification="USABLE_MESH"),
            P.SourceArtifact(artifact_id="right", path="right.stl", format="STL",
                             classification="USABLE_MESH")),
        edit_scopes=(
            P.EditScope(artifact_id="left", region="the left pocket",
                        region_box=dict(LEFT_BOX),
                        interface_ids=("magnet-pockets",)),
            P.EditScope(artifact_id="right", region="the right pocket",
                        region_box=dict(RIGHT_BOX),
                        interface_ids=("magnet-pockets",))))


def _two_scopes_laid_out(root: Path) -> Path:
    directory = root / "project"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "brief.md").write_text("cut a magnet pocket into each plate",
                                        encoding="utf-8")
    left, right = directory / "left.stl", directory / "right.stl"
    _plate(0.0).export(left)
    _plate(40.0).export(right)
    (directory / "model.py").write_text(
        textwrap.dedent(TWO_PLATE_MODEL).format(
            left=str(left).replace("\\", "\\\\"),
            right=str(right).replace("\\", "\\\\")),
        encoding="utf-8")
    (directory / ACC.PROPOSAL_FILE).write_text(
        json.dumps(TWO_PLATE_PROPOSAL, indent=2, sort_keys=True), encoding="utf-8")
    _two_scope_project().save(directory)
    return directory


if __name__ == "__main__":
    unittest.main()


class EdgeManifoldCountsTest(unittest.TestCase):
    """docs/defects.md D1: one number was carrying three conditions.

    `len(edges_unique) - len(face_adjacency)` counts every edge that is not
    two-manifold -- open edges and edges shared by three or more faces alike --
    and reported the total under a name that means only the first. A real source
    artifact reported `boundary_edges: 332` whose actual condition was 322 open
    edges, 9 edges shared by three faces and 1 shared by four. The number is what
    a reader acts on, and "332 boundary edges" points a repairer at hole-filling,
    which cannot close either of the other two.
    """

    @staticmethod
    def _three_conditions() -> trimesh.Trimesh:
        """One edge used by three faces, one by four, and open edges elsewhere.

        Two fans that share no vertex, so the arithmetic is checkable by hand:
        the three-fan contributes edge (0,1) used three times plus six edges used
        once; the four-fan contributes edge (5,6) used four times plus eight used
        once. 16 unique edges, none of them two-manifold.
        """
        vertices = np.array(
            [[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, -10, 0], [5, 0, 9],
             [50, 0, 0], [60, 0, 0], [50, 10, 0], [50, -10, 0], [55, 0, 9],
             [55, 0, -9]], dtype=float)
        faces = np.array([[0, 1, 2], [0, 1, 3], [0, 1, 4],
                          [5, 6, 7], [5, 6, 8], [5, 6, 9], [5, 6, 10]],
                         dtype=np.int64)
        return trimesh.Trimesh(vertices=vertices, faces=faces, process=True)

    def test_the_three_conditions_are_counted_separately(self) -> None:
        mesh = self._three_conditions()
        counts = D.edge_manifold_counts(mesh)

        self.assertEqual(14, counts["boundary_edges"],
                         "edges used by exactly one face")
        self.assertEqual(2, counts["nonmanifold_edges"],
                         "edges used by three or more faces")
        self.assertEqual(4, counts["max_faces_per_edge"])
        self.assertEqual({"1": 14, "3": 1, "4": 1}, counts["faces_per_edge"])

        # The number the old expression produced, kept as the arithmetic that
        # makes the defect legible: it is the sum of two different conditions.
        self.assertEqual(
            counts["boundary_edges"] + counts["nonmanifold_edges"],
            len(mesh.edges_unique) - len(mesh.face_adjacency))

    def test_a_sound_mesh_reports_no_edges_of_either_kind(self) -> None:
        """The counter must be able to say zero, or it says nothing."""
        counts = D.edge_manifold_counts(trimesh.creation.box(extents=(10, 10, 10)))
        self.assertEqual(0, counts["boundary_edges"])
        self.assertEqual(0, counts["nonmanifold_edges"])
        self.assertEqual(2, counts["max_faces_per_edge"])

    def test_an_open_mesh_reports_only_boundary_edges(self) -> None:
        """A hole is a hole, and must not be inflated by the other condition."""
        box = trimesh.creation.box(extents=(10, 10, 10))
        box.update_faces(np.arange(len(box.faces)) != 0)
        counts = D.edge_manifold_counts(box)
        self.assertEqual(3, counts["boundary_edges"])
        self.assertEqual(0, counts["nonmanifold_edges"])

    def test_diagnose_reports_the_two_conditions_and_names_the_second(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "three-conditions.stl"
            self._three_conditions().export(path)

            report = D.diagnose(path)
            self.assertEqual("REPAIR_REQUIRED", report["classification"])
            self.assertEqual(14, report["boundary_edges"])
            self.assertEqual(2, report["nonmanifold_edges"])
            # A repairer told only about holes would reach for hole-filling,
            # which cannot close an edge shared by three faces.
            self.assertTrue(
                any("3 or more face" in finding for finding in report["findings"]),
                f"no finding named the non-manifold edges: {report['findings']}")


class DerivedSampleDensityTest(unittest.TestCase):
    """Release 6: a density derived from what the audit undertook to find.

    The preservation lane has never been allowed to report a part COMMISSIONED
    or VERIFIED, and the reason recorded on every one of its runs is this one:
    the sample count was a fixed 20,000 rather than a density derived from a
    declared minimum detectable defect size, "so a small undeclared addition
    outside the edit region can still be missed, and is now missed identically
    on every run."

    Determinism was the previous slice and it is not sensitivity. This is
    sensitivity: the count is now a function of the surface it is spread over
    and the defect size the job declared, and the receipt can say what the plan
    could find rather than how many points it used.
    """

    def test_the_count_inverts_to_the_size_it_was_derived_from(self) -> None:
        """The two directions are one relation, so they must agree."""
        for area in (100.0, 1027.8, 50_000.0):
            for defect in (2.0, 1.0, 0.5, 0.25):
                with self.subTest(area=area, defect=defect):
                    count = PR.derive_sample_count(area, defect)
                    back = PR.detectable_defect_mm(area, count)
                    # Rounding up the count can only make the plan finer, never
                    # coarser -- a detector that found *less* than it promised
                    # would be the failure this whole slice exists to remove.
                    self.assertLessEqual(back, defect + 1e-9,
                                         f"{count} samples finds {back} mm, "
                                         f"which is coarser than the declared "
                                         f"{defect} mm")

    def test_density_is_what_matters_not_the_count(self) -> None:
        """Ten times the area needs ten times the points for the same size.

        This is the property that makes the derivation legitimate at all:
        `_plan_points` is area-weighted, so density is uniform over the surface
        and the detectable size does not depend on which region a point landed
        in. A count that did not scale with area would be a detector whose
        sensitivity silently depended on how big the part was.
        """
        small = PR.derive_sample_count(1_000.0, 0.5)
        large = PR.derive_sample_count(10_000.0, 0.5)
        self.assertAlmostEqual(10.0, large / small, places=2)

    def test_halving_the_defect_size_quadruples_the_samples(self) -> None:
        """A defect presents an area, so the relation is quadratic, not linear."""
        coarse = PR.derive_sample_count(1_000.0, 1.0)
        fine = PR.derive_sample_count(1_000.0, 0.5)
        self.assertAlmostEqual(4.0, fine / coarse, places=2)

    def test_a_demand_over_the_ceiling_is_refused_and_names_what_it_could_find(self) -> None:
        """A controlled failure, not a clamp, and not an allocation attempt.

        Clamping would answer a question the job did not ask: "is this preserved
        to 0.01 mm" answered by a plan that can only see 0.03 mm, and the answer
        would look identical to one that could.
        """
        with self.assertRaises(PR.SampleBudgetExceeded) as caught:
            PR.derive_sample_count(1027.8, 0.01)
        message = str(caught.exception)
        self.assertIn("0.01", message)
        self.assertIn("ceiling", message)
        # And it names the size that *is* reachable, so the refusal is
        # actionable rather than only a refusal.
        reachable = PR.detectable_defect_mm(1027.8, PR.MAX_DERIVED_SAMPLES)
        self.assertIn(f"{reachable:.4f}", message)

    def test_the_fixed_default_is_a_measurable_sensitivity_not_a_mystery(self) -> None:
        """What 20,000 points actually bought, stated as a size.

        The old constant was not wrong, it was unquantified -- 20,000 points is
        dense on a 20 mm clip and sparse on a build plate. Now the same number
        can be reported as the size it can find, which is what a reader of a
        preservation claim needs.
        """
        clip = PR.detectable_defect_mm(1027.8, PR.DEFAULT_SAMPLES)
        plate = PR.detectable_defect_mm(250_000.0, PR.DEFAULT_SAMPLES)
        self.assertLess(clip, 0.6)
        self.assertGreater(plate, 7.0)
        self.assertGreater(plate, clip * 10,
                           "the same fixed count is a very different detector "
                           "on a small part and a large one, which is why a "
                           "count alone cannot support a sensitivity claim")

    def test_nonsense_inputs_are_refused_rather_than_producing_a_plan(self) -> None:
        for area, defect in ((0.0, 1.0), (-5.0, 1.0), (100.0, 0.0),
                             (100.0, -1.0), (float("nan"), 1.0)):
            with self.subTest(area=area, defect=defect):
                with self.assertRaises(ValueError):
                    PR.derive_sample_count(area, defect)
        with self.assertRaises(ValueError):
            PR.derive_sample_count(100.0, 1.0, confidence=1.0)
        with self.assertRaises(ValueError):
            PR.derive_sample_count(100.0, 1.0, confidence=0.0)

    def test_a_finer_declared_size_never_buys_fewer_samples(self) -> None:
        """Monotonicity, which a rounding bug is exactly how you lose."""
        counts = [PR.derive_sample_count(2_000.0, d)
                  for d in (4.0, 2.0, 1.0, 0.8, 0.5, 0.3)]
        self.assertEqual(counts, sorted(counts),
                         "asking for a smaller defect must never reduce the plan")


class ADeclaredDefectSizeReachesThePlanTest(unittest.TestCase):
    """The declaration end of the derivation, and the silence at the other end.

    `derive_sample_count` is arithmetic; this is the part that decides whether a
    job can reach it. Two properties matter and they pull opposite ways: a job
    that declares a size must get a plan derived from it, and a job that declares
    nothing must produce byte-identical bytes to the ones it produced before this
    field existed -- otherwise every frozen contract hash in the repository moves
    for jobs that gained nothing.
    """

    def test_a_declared_size_reaches_the_contract_row(self) -> None:
        scope = P.EditScope(artifact_id="ball", region="the flange",
                            minimum_detectable_defect_mm=0.3)
        self.assertEqual(0.3, scope.minimum_detectable_defect_mm)
        self.assertEqual([], [i for i in scope.problems(0)
                              if "minimum_detectable" in i.where])

    def test_a_size_that_cannot_be_a_length_is_refused(self) -> None:
        """The refusal side, which the accept side cannot stand in for.

        Written because a mutation that deleted the whole validation branch went
        uncaught: every other test here declares a *valid* size, so removing the
        check that rejects an invalid one changed nothing any of them could see.
        """
        for value in (0.0, -1.0, "0.3", True, float("nan"), float("inf")):
            with self.subTest(value=value):
                scope = P.EditScope(artifact_id="ball", region="r",
                                    minimum_detectable_defect_mm=value)
                codes = [i.code for i in scope.problems(0)
                         if "minimum_detectable" in i.where]
                self.assertEqual(["SCHEMA_RANGE"], codes,
                                 f"{value!r} is not a length this audit can "
                                 "undertake to find, and must be refused before "
                                 "a plan is derived from it")

    def test_an_undeclared_size_puts_no_key_in_the_row(self) -> None:
        """Absent, not null. A key that is always there moves every old hash."""
        from . import cli
        project = P.Project(
            job_id="j", updated_utc=UTC, source_mode="MODIFY",
            consequence="INCONSEQUENTIAL", consequence_rationale="a test",
            printer="p", material={"process": "FDM", "material": "PLA"},
            nozzle={"diameter_mm": 0.4},
            orientation={"model_to_printer_matrix": "identity", "bed_z_mm": 0.0},
            template=None, parameters={}, model="model.py",
            envelope_mm={"x": 50.0, "y": 50.0, "z": 50.0},
            reviewer={"model_snapshot": "t"},
            source_artifacts=(P.SourceArtifact(artifact_id="ball",
                                               path="ball.stl"),),
            edit_scopes=(P.EditScope(artifact_id="ball", region="the flange"),))
        rows = cli._preservation_feature(project)
        self.assertEqual(1, len(rows))
        self.assertNotIn("minimum_detectable_defect_mm", rows[0],
                         "an undeclared size must leave the contract row exactly "
                         "as it was, or every frozen hash moves for nothing")

        declared = dataclasses.replace(project.edit_scopes[0],
                                       minimum_detectable_defect_mm=0.25)
        project.edit_scopes = (declared,)
        rows = cli._preservation_feature(project)
        self.assertEqual(0.25, rows[0]["minimum_detectable_defect_mm"])

    def test_the_planner_prefers_declared_size_over_the_fixed_fallback(self) -> None:
        from . import commission
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "ball.stl"
            trimesh.creation.icosphere(radius=8.5).export(source)
            area = float(trimesh.load(str(source), force="mesh",
                                      process=True).area)

            # Nothing declared: the fixed fallback, unchanged.
            self.assertEqual(PR.DEFAULT_SAMPLES,
                             commission._preservation_samples({}, source))
            # An explicit count still wins -- the frozen fixtures set one.
            self.assertEqual(4242,
                             commission._preservation_samples({"samples": 4242},
                                                              source))
            # Declared: derived from this part's own surface.
            planned = commission._preservation_samples(
                {"minimum_detectable_defect_mm": 0.3}, source)
            self.assertEqual(PR.derive_sample_count(area, 0.3), planned)
            self.assertGreater(planned, PR.DEFAULT_SAMPLES,
                               "0.3 mm on a 17 mm ball is finer than the fixed "
                               "count, so the declaration must cost something")
            self.assertLessEqual(PR.detectable_defect_mm(area, planned), 0.3)

    def test_an_unreachable_declared_size_is_a_finding_not_a_crash(self) -> None:
        from . import commission
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "ball.stl"
            trimesh.creation.icosphere(radius=8.5).export(source)
            with self.assertRaises(PR.SampleBudgetExceeded):
                commission._preservation_samples(
                    {"minimum_detectable_defect_mm": 0.0005}, source)


class TheSamplePlanActuallyFindsWhatItPromisesTest(unittest.TestCase):
    """The one property the whole derivation claims, measured on the planner.

    Written after an independent review refuted the claim by measurement. Every
    other test of `derive_sample_count` checks the *arithmetic* -- inversion,
    area scaling, quadratic scaling in d, monotonicity, refusals -- and all of
    them passed while the instrument missed a d-sized patch 13% of the time at
    the default count and 22% at the count the recorded golden used.

    The cause was the sample sequence, not the arithmetic. An additive-recurrence
    (Kronecker) sequence was chosen because low discrepancy sounds strictly
    better than random; it is not, for this question. Discrepancy bounds how far
    a box's sample count strays from its volume. Finding a defect needs bounded
    *dispersion* -- no empty patch anywhere -- which low discrepancy does not
    bound, and a Kronecker sequence's 2-D projections are striated, so it misses
    thin patches far more often than area implies.

    So this test measures the thing the docstring promises rather than the
    algebra behind it, and it is the test that would have caught it.
    """

    @staticmethod
    def _miss_rate(count: int, seed: str, trials: int = 1500) -> float:
        """Fraction of d-sized patches containing no sample, d from the count."""
        side = PR.detectable_defect_mm(1.0, count)
        points = PR._stream(seed, count)[:, :2]
        # Patch corners on their own deterministic grid, so this test does not
        # itself depend on a random draw.
        corners = PR._stream(f"{seed}-probes", trials)[:, :2] * (1.0 - side)
        missed = 0
        for x, y in corners:
            if not ((points[:, 0] >= x) & (points[:, 0] < x + side)
                    & (points[:, 1] >= y) & (points[:, 1] < y + side)).any():
                missed += 1
        return missed / trials

    def test_a_derived_plan_misses_at_about_the_declared_rate(self) -> None:
        """1% promised, so the measured miss must be near 1% and not 13%."""
        for count in (20_000, 38_014):
            with self.subTest(samples=count):
                missed = self._miss_rate(count, f"plan-{count}")
                self.assertLess(
                    missed, 0.04,
                    f"{count} samples missed {missed:.2%} of patches of the size "
                    f"the derivation says they find at "
                    f"{PR.DEFAULT_DETECTION_CONFIDENCE:.0%}. The plan does not "
                    "deliver the sensitivity the receipt reports.")

    def test_the_stream_is_deterministic_and_pinned(self) -> None:
        """Same seed, same bytes -- the property the sequence was chosen for."""
        first = PR._stream("a-seed", 64)
        again = PR._stream("a-seed", 64)
        self.assertTrue((first == again).all())
        self.assertFalse((first == PR._stream("another-seed", 64)).all())
        self.assertEqual((64, 3), first.shape)
        self.assertTrue(((first >= 0.0) & (first < 1.0)).all())

    def test_the_stream_is_not_striated_in_its_projections(self) -> None:
        """The specific failure of the sequence this replaced.

        Every 2-D projection is checked, because the planner uses coordinate 0
        for the face choice and 1 and 2 for the position inside the triangle --
        so a projection with holes puts holes on the surface.
        """
        points = PR._stream("striation-probe", 20_000)
        for a, b in ((0, 1), (1, 2), (0, 2)):
            with self.subTest(projection=(a, b)):
                cells = 40
                grid = np.zeros((cells, cells), dtype=np.int64)
                xs = (points[:, a] * cells).astype(int)
                ys = (points[:, b] * cells).astype(int)
                np.add.at(grid, (xs, ys), 1)
                self.assertEqual(0, int((grid == 0).sum()),
                                 f"projection {(a, b)} leaves empty cells, which "
                                 "is how a sequence misses a defect that is "
                                 "thinner than its stripe spacing")


class ADeclarationMustNotBreakOrBeIgnoredTest(unittest.TestCase):
    """Two ways a declared sensitivity went wrong, both found by review.

    Declaring something the pipeline supports must never be the thing that
    breaks a job, and must never be silently dropped. Both happened.
    """

    def test_a_source_whose_area_cannot_be_read_is_a_finding_not_a_crash(self) -> None:
        """A STEP source: `analysis.load` refuses it, `PR.audit` handles it.

        So *declaring* a sensitivity turned a working audit into an uncaught
        stage crash, on the one source class the module was extended to support.
        """
        from . import commission
        step = (Path(__file__).resolve().parents[4] / "benchmarks" / "fixtures"
                / "vent-ball-combine" / "public" / "sources" / "vent_mount.step")
        if not step.is_file():                       # pragma: no cover
            self.skipTest("the vendored STEP fixture is not on this machine")
        with self.assertRaises(commission.SampleAreaUnreadable) as caught:
            commission._preservation_samples(
                {"minimum_detectable_defect_mm": 0.3}, step)
        self.assertIn("0.3", str(caught.exception))
        self.assertIn(step.name, str(caught.exception))
        # And it is not the other refusal: the two mean different things.
        self.assertNotIsInstance(caught.exception, PR.SampleBudgetExceeded)

    def test_a_row_naming_both_a_count_and_a_size_is_refused(self) -> None:
        """Previously the count won and the declaration vanished silently.

        A job could ask for 0.3 mm, be handed a 0.8 mm plan, and read PRESERVED
        with nothing on the receipt saying it had not got what it asked for.
        """
        from . import commission
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "ball.stl"
            trimesh.creation.icosphere(radius=8.5).export(source)
            with self.assertRaises(commission.SampleAreaUnreadable) as caught:
                commission._preservation_samples(
                    {"samples": 20000, "minimum_detectable_defect_mm": 0.3},
                    source)
            self.assertIn("two different instructions", str(caught.exception))
            # Each alone still works.
            self.assertEqual(20000, commission._preservation_samples(
                {"samples": 20000}, source))
            self.assertGreater(commission._preservation_samples(
                {"minimum_detectable_defect_mm": 0.3}, source), 20000)
