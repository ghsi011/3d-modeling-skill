# oneplus-drawer-dropin — the request

Diagnose an 18 KB Bambu Studio export carrying one object: a TPU drop-in drawer
for a phone case.

It is here for one reason. The single build item carries a pure translation, so
the authored mesh coordinates and the placed scene coordinates differ by a known
offset — and a reader that reports the authored numbers as the placed ones
answers "where is this part" with the wrong answer while every extent still
looks right.

`evidence_class: PARSER_SPECIMEN`. This fixture says nothing about design
quality. It is the cheapest real file that still exercises the assembled-scene
path.
