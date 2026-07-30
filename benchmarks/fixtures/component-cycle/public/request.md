# component-cycle — the request

Diagnose a 3MF whose two objects are component wrappers referring to each other.

Nothing in it dangles: every `objectid` a component names is present in the
archive, the XML parses, and the build item resolves. There is still no mesh
anywhere, and following the components is an infinite walk.

What is asked: report that there is no geometry, report the cycle, classify it
`RECONSTRUCTION_REQUIRED`, and invent neither a bounding box nor a volume.

`evidence_class: PARSER_SPECIMEN`, `license: synthetic`. This one is built in
the test with `zipfile`; there is no external file to hash and it is the only
fixture in the set that may be redistributed.
