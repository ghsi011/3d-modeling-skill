# AGENTS.md

This repository packages a portable 3D modeling skill for FDM printed parts. It turns a plain-language commission, reference photos, and measurements into verified, print-ready model artifacts through role-specific agents and deterministic checks.

## Pipeline contract

Use the five-role pipeline for production work:

1. `3d-orchestrator`, owns intake, routing, job state, phase gates, and delivery.
2. `3d-metrologist`, owns datums, measurements, source confidence, and reference acceptance.
3. `3d-print-engineer`, owns print plan, fit strategy, material and orientation choices, coupons, and prep checks.
4. `3d-designer`, owns reference and candidate CAD from the accepted contracts.
5. `3d-verifier`, owns independent STL re-import checks, renders, and accept or reject evidence.

This is file-contract only communication: roles write and read project files, not chat summaries. Bind each role to the project contract files, source evidence, revisions, and hashes. The designer and verifier must stay independent, and verification must inspect exported artifacts, not only in-memory CAD state.

## Invocation by harness

### Claude Code

- Agent definitions live in `.claude/agents/`.
- Skill folders live under `skills/` and can be copied or linked into a discovered Claude skills directory.
- Keep the `skills/` tree intact so role files can resolve shared references and scripts by relative path.
- Start with the orchestrator role for a commission, then let it dispatch the other four roles through file contracts.

### OpenCode

- Agent definitions live in `.opencode/agents/`. Use the plural `agents` directory.
- `opencode.json` is the harness entry point for generated OpenCode wiring, including agents, skills, and local MCP tooling when present.
- Start with the orchestrator agent and pass the commission plus the project workspace path. Require all follow-up work to happen through contract files.

### Generic OpenAI style YAML

- Generated YAML agents live in `dist/openai/`.
- Load the five role YAML files as separate agents in the host harness.
- Provide the same project directory to every role, and require the orchestrator to issue commissions that name the authorized input files, required outputs, backend, and gate expected for that phase.

## Tooling paths

- `skills/3d-modeling/scripts`, deterministic model, mesh, preflight, preview, 3MF, and contract tooling.
- `skills/3d-modeling/scripts/backends`, the common CAD interface and its `cadquery`, `build123d`, and `freecad` adapters.
- `tools/gen_harness.py`, harness generator for Claude, OpenCode, and generic YAML outputs.
- `tools/mcp_server.py`, local MCP server for contract and preflight tools, wired into `opencode.json`.
- `tools/build_skill.py`, deterministic per-role and aggregate `.skill` bundle builder. CI step.
- `tools/check_internal_links.py`, relative-markdown-link resolver over the whole tree. CI step.

See also:

- [`docs/tooling.md`](docs/tooling.md)
- [`docs/harness-matrix.md`](docs/harness-matrix.md)

## Runtime contracts

The normative file-contract schema is [`skills/3d-modeling/references/team-contracts-v4.md`](skills/3d-modeling/references/team-contracts-v4.md). It defines the required project files, revisions, hashes, gates, and role ownership rules. Don't replace it with chat instructions or harness-specific memory.

Every commission should state:

- role and task,
- authorized input files,
- required output files,
- contract revision or hash expectations,
- phase gate to satisfy,
- backend choice: `cadquery` | `build123d` | `freecad`.

## Backend selection

Treat the backend as an explicit commission input, not an agent preference. Use one backend per part unless the orchestrator records a new revision that changes the route.

- `cadquery`, Python-first parametric CAD for headless generation and repeatable checks.
- `build123d`, Python-first parametric CAD for hosts that standardize on build123d scripts.
- `freecad`, desktop-backed parametric CAD when a FreeCAD document or MCP-connected workstation is required.

Record the selected backend in the project contract files so downstream roles and tools can verify the same artifact chain.
