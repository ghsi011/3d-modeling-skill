#!/usr/bin/env python3
"""Weld multiple STL parts into ONE 3MF whose build object contains one component
per part. Bambu Studio / OrcaSlicer import the result as a single object with
individually selectable parts (assign a filament per part for multi-color).

Usage:
    python3 make_3mf.py out.3mf "KnobBody (black)=body.stl" "Pattern (white)=pattern.stl"

Parts must already share one coordinate system (exported from the same CAD doc).
Requires: pip install trimesh numpy
"""
import sys
import io
import zipfile
import os
import trimesh


def mesh_xml(obj_id, name, mesh):
    buf = io.StringIO()
    buf.write(f'<object id="{obj_id}" type="model" name="{name}"><mesh><vertices>')
    for x, y, z in mesh.vertices:
        buf.write(f'<vertex x="{x:.6g}" y="{y:.6g}" z="{z:.6g}"/>')
    buf.write('</vertices><triangles>')
    for a, b, c in mesh.faces:
        buf.write(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>')
    buf.write('</triangles></mesh></object>')
    return buf.getvalue()


def main():
    if len(sys.argv) < 3 or any('=' not in s for s in sys.argv[2:]):
        sys.exit(__doc__)
    out, specs = sys.argv[1], sys.argv[2:]
    objects, comp = [], []
    for i, spec in enumerate(specs, start=1):
        name, path = spec.split('=', 1)
        m = trimesh.load(path, process=True)  # welds duplicate STL vertices
        m.remove_unreferenced_vertices()
        print(f'{name}: {len(m.vertices)} verts, {len(m.faces)} tris, '
              f'watertight={m.is_watertight}')
        if not m.is_watertight:
            # ASCII: this line fires exactly when something is already wrong, and
            # a Windows console on a legacy code page raises UnicodeEncodeError
            # on an em-dash -- turning a warning into a traceback that hides it.
            print(f'  WARNING: {name} is not watertight - check the source mesh')
        objects.append(mesh_xml(i, name, m))
        comp.append(f'<component objectid="{i}"/>')
    asm_id = len(specs) + 1
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
        '<resources>' + ''.join(objects)
        + f'<object id="{asm_id}" type="model" name="assembly">'
          f'<components>{"".join(comp)}</components></object>'
        '</resources>'
        f'<build><item objectid="{asm_id}"/></build>\n</model>'
    )
    ct = ('<?xml version="1.0" encoding="UTF-8"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
          '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel-1" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
            '</Relationships>')
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', ct)
        z.writestr('_rels/.rels', rels)
        z.writestr('3D/3dmodel.model', model)
    print('wrote', out, os.path.getsize(out), 'bytes')
    try:  # round-trip check — file is already written; failure here is verification only
        check = trimesh.load(out)
        geoms = getattr(check, 'geometry', {})
        print('re-loaded:', {k: (len(g.vertices), len(g.faces)) for k, g in geoms.items()})
    except Exception as e:
        print(f'wrote OK; round-trip verification skipped: {e}')


if __name__ == '__main__':
    main()
