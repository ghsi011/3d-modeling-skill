# Harness matrix

This matrix records how the portable 3D modeling team is packaged for each
supported harness. Status words are scoped to this repository:

Supported means the harness has a concrete artifact path in this repo.
Documented means the repo names the setup surface a user should wire into that
harness. Verified means tests or source artifacts confirm the generated shape.

<table>
  <thead>
    <tr>
      <th>Harness</th>
      <th>Agents</th>
      <th>Tools via MCP</th>
      <th>Tools via CLI</th>
      <th>AGENTS.md</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Claude Code</td>
      <td>Supported and verified. Role agents are generated into <code>.claude/agents/3d-*.md</code>, with <code>3d-orchestrator</code> exposing the specialist dispatch set.</td>
      <td>Documented. FreeCAD and future tool bridges can be attached through the host MCP config rather than the generated Claude agent files.</td>
      <td>Supported. Agents call the shared Python CLIs under <code>skills/3d-modeling/scripts/</code>, including contract validation, mesh IO, previews, visual checks, and package builders.</td>
      <td>Documented. Root <code>AGENTS.md</code> is the harness neutral rule surface for repository wide pipeline, tool, and contract guidance.</td>
    </tr>
    <tr>
      <td>OpenCode</td>
      <td>Supported and verified. Role agents live in <code>.opencode/agents/</code>. <code>3d-orchestrator.md</code> is <code>mode: primary</code>; specialists such as <code>3d-verifier.md</code> are <code>mode: subagent</code>.</td>
      <td>Supported and documented. <code>opencode.json</code> carries the <code>mcp</code> key as the OpenCode MCP attachment point.</td>
      <td>Supported. OpenCode agents can run the same shared Python CLIs from <code>skills/3d-modeling/scripts/</code> when their permission frontmatter allows <code>bash</code>.</td>
      <td>Documented. OpenCode reads project guidance from root <code>AGENTS.md</code> while agent definitions stay in <code>.opencode/agents/</code>.</td>
    </tr>
    <tr>
      <td>generic/OpenAI</td>
      <td>Supported and verified. Portable role manifests are generated as <code>dist/openai/3d-*.yaml</code>, with role metadata and spawn capability fields.</td>
      <td>Documented. Generic harnesses should bind MCP tools through their own runtime config and point them at the same project tool surfaces.</td>
      <td>Supported. The YAML package names capabilities only; the runtime still calls repository CLIs such as <code>team_preflight.py</code>, <code>team_tools.contracts</code>, and <code>designer_toolkit</code>.</td>
      <td>Documented. A generic host should load root <code>AGENTS.md</code> as repository policy before invoking the role YAML.</td>
    </tr>
  </tbody>
</table>

## OpenCode verification

Regenerate with <code>python tools/gen_harness.py</code>; CI is the check. The
repository test <code>tools/test_gen_harness.py</code> covers the plural agent path,
OpenCode primary and subagent modes, specialist task denial, and the <code>mcp</code>
config key — <code>opencode.json</code> must declare the local deterministic-tool
server <code>3d-modeling-tools</code> with <code>"type": "local"</code>, command
<code>["python", "tools/mcp_server.py"]</code>, and <code>"enabled": true</code>.
