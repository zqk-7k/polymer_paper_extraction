---
name: polymer-identity-naming
description: Task-specific guidance for polymer material scope, supplied constitution, and unresolved identity or naming gaps.
---

The application host loads this bundle explicitly for GLM. This is not an
ambient Codex installation, a new agent, or a workflow. The host freezes this
entry and its three references into a plan; context uses only that snapshot.
Older plans that do not call this module keep their existing behavior.

Select the relevant module; there are no mandatory sequential phases:
- [Scope](references/scope.md): decide which material or component is being named.
- [Constitution](references/constitution.md): reason about a supplied graph.
- [Gaps](references/gaps.md): preserve uncertainty and select useful evidence.

Use the same existing Kernel and NamingService. Existing tools read_source,
read_image and check_structure remain host-dispatched; this bundle only advises
their names and never executes them. The host supplies their normal arguments,
source bindings and budgets. No extra reviewer or exact-name verification is
introduced. There is no implemented fragment assembly here.

Guidance is not a source fact or an identity certification. Preserve explicit
roles, evidence references, assumptions, partial names and unresolved fields.
Unknown stays unknown. No automatic sample merge or automatic update is allowed.

freeze(skill_dir) reads SKILL.md and the three fixed references. The bundle has
contract, entry (text), modules (scope/constitution/gaps text), and sha256 over
the other three fields using canonical UTF-8 JSON. validate returns a copy.
context(bundle, task, facts) returns one reference and a tool-name suggestion
or retain_partial_identity, plus an independent preserve copy of facts.
Supported hints are structure_supplied (boolean), source_refs (list of up to
64 nonempty strings), image_src (nonempty string), evidence_status (string;
only not_read enables reading), and gap_kind (see Gaps). Empty source_refs
means no provided references. Omit unknown hints; other keys remain opaque.
