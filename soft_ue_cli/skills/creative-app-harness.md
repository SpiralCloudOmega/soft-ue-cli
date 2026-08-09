---
name: creative-app-harness
description: Plan and verify durable multi-application creative work with structured MCP adapters first and computer use only as fallback.
version: 1.0.0
---

# Creative app harness

Use this workflow for long-running work across DCC, CAD, and game-engine applications.
The harness is an inventory and readiness layer; it does not run an agent or install external
servers.

## Operating rules

1. Run `soft-ue-cli harness status` and inspect every enabled adapter before planning work.
2. Prefer a structured, application-specific MCP tool whenever it can express the operation.
   Structured calls provide inspectable inputs, results, and stable object identifiers.
3. Use Cua Driver computer use only when the structured adapter lacks the required UI action.
   Cua Driver exposes those visual computer-use tools through its `cua-driver mcp` transport.
   Bound each visual action, record what was clicked or typed, and return to structured
   inspection as soon as possible.
4. Never infer success from a click, a lack of errors, or an agent's narrative. Capture evidence.
5. Do not put credentials in a manifest. Configure secrets through the external server's secure
   mechanism and avoid printing environment values.

## Manager / Executor / Auditor

- **Manager:** decomposes the goal into application-scoped steps, names required adapters,
  defines evidence and acceptance criteria, and records durable checkpoints.
- **Executor:** performs one bounded step with the preferred structured adapter, using Cua only
  for a documented gap. It records tool results, artifact paths, object identifiers, and captures.
- **Auditor:** independently inspects the resulting application state and artifacts. It compares
  them with the acceptance criteria and returns pass, revise, or blocked with evidence.

Do not let the Executor self-certify the final result. On restart, resume from the last audited
checkpoint rather than replaying unverified actions.

## Application routing

| Application | Preferred route | Fallback and verification |
|---|---|---|
| Unreal Engine | Built-in soft-ue-cli MCP and Unreal-native structured tools | Use viewport/PIE capture only where necessary; verify with queries, asset inspection, logs, tests, and captures. |
| Blender | A separately installed and configured Blender MCP | Use Cua for unsupported panels only; verify scene objects, transforms, modifiers, render settings, and a saved/rendered artifact. |
| Unity | A separately installed Unity MCP with its server path or URL supplied in the manifest | Keep disabled until configured; verify hierarchy, components, console state, saved scenes/assets, and test results. |
| 3ds Max | A user-supplied structured adapter or existing project automation | This package provides no native 3ds Max bridge. If none is configured, use bounded Cua actions and verify through saved exports, scene inspection, and screenshots. |
| AutoCAD | A user-supplied structured adapter or existing project automation | This package provides no native AutoCAD bridge. If none is configured, use bounded Cua actions and verify layers, dimensions, drawing exports, and screenshots. |

Do not describe an external/community adapter as built in. Record its provenance URL and pin its
configuration outside the default inventory before enabling it.

## Evidence contract

For every durable checkpoint retain:

- task and application;
- adapter/tool used and sanitized inputs;
- before/after object identifiers or state summaries;
- saved artifact path and, where practical, a digest or timestamp;
- structured validation result;
- visual capture when appearance matters;
- Auditor decision and remaining gaps.

Generate client configuration with `soft-ue-cli harness mcp-config`. It contains every enabled
MCP transport, including Cua Driver when enabled. Orchestrators are intentionally excluded.
