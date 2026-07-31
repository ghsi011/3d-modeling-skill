# Mission

Create a fast, accurate, reliable, and versatile 3D-modeling capability that
transforms natural-language requirements—together with any available CAD files,
photos, measurements, specifications, and user feedback—into editable,
manufacturable designs and usable production deliverables.

## Required capabilities

The capability must support:

* original designs using supplied or appropriately chosen dimensions;
* modification, repair, and adaptation of existing STEP, STL, and 3MF models;
* combination of two or more existing CAD artifacts;
* parts that mate accurately with real objects;
* reconstruction of relevant geometry from photos, measurements, descriptions,
  and specifications;
* multi-part, moving, retained, compliant, or otherwise interacting assemblies;
* preparation for ordinary FDM manufacturing, including fit, material,
  orientation, support, tolerance, and printer constraints.

## Quality objectives

The resulting design should:

* satisfy the user's functional and dimensional requirements;
* preserve supplied geometry where preservation is required;
* alter only the geometry necessary to achieve the requested result;
* maintain correct alignment, clearances, interfaces, motion, and component
  relationships;
* be geometrically robust, editable, exportable, and practical to manufacture;
* communicate unresolved uncertainty, limitations, and required physical testing
  honestly;
* provide the source files, production artifacts, and information needed for
  continued iteration.

## Efficiency objectives

The capability should use effort proportional to the difficulty and consequence
of the job:

* simple work should remain fast and lightweight;
* complex or uncertain work should receive the additional analysis it genuinely
  requires;
* unnecessary user questions, repeated work, context consumption, execution
  time, and AI API usage should be minimized;
* existing information and completed work should be reused whenever it remains
  valid.

## Success criterion

Success means producing the simplest reliable design that fulfills the
real-world task, is practical to manufacture and iterate, and is supported by
evidence appropriate to the uncertainty and consequences involved—without
imposing unnecessary process or computational cost.
