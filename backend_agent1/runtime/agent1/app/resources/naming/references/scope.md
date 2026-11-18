# Material scope

Identify the target as the whole material or an explicitly identified component.
Keep monomer, reactant, precursor, bound residue and counterion roles distinct.
Retain the explicit current role and known source references; do not silently
promote a precursor or a named component to the whole material. Unknown roles
remain unknown. Amounts or ratios alone do not establish a name or identity.

Not every member needs a graph. Preserve source-supported partial descriptions
and names when constitution is unavailable. Do not force all members through
structure naming or decide in code that a material identity is true.

When source_refs are provided and evidence_status is explicitly not_read,
suggest read_source. Otherwise retain_partial_identity. Tool results still
need their source and material binding; the suggestion itself is not evidence.

With current owner_ref and optional material_ref in facts, the host can return an explicit-reference relationship view of the current records. Direct precursors, prior-route sources, bound residues, reagents and components remain separate. A resolved reference is not reaction proof; definition context is not material-specific evidence. Missing or conflicting links remain visible rather than guessed.
