# Supplied constitution and explicit residue connections

Use check_structure for a concrete question about an existing graph, not as a
prerequisite for submitting a useful polymer identity. It shares the workbench's
Kernel/NamingService and frozen scope. A graph result is not proof of synthesis,
actual material identity or a preferred IUPAC name.

Use compare_to for a second supplied graph, with its own smiles, src,
assumptions and optional owner_ref. Different port cuts or repeated cells can
encode the same constitution, but do not merge samples, end groups, salts,
stereo or finite-chain properties. Unsupported scope remains unknown.

When site_preparation is advertised, derive_structure can accept
site_preparation:{smiles}, with outer src and assumptions, to assign missing atom
maps and list local sites. Select only explicitly supported or hypothetical
site_ids using the returned expected_graph_sha256. Never choose every site by
default. No supported site means an implementation limit, not chemical inertness.
The operation reuses mapped_residue; source qualification and ions are retained.

When fragment_assembly is advertised, join already supplied residue fragments
only at selected mapped dummy ports and explicit single-bond links. Each fragment
and link needs source IDs. It removes only selected dummies, retains real-atom
correspondence, and reports unused ports and local ester/amide/Si-O motifs.
It does not predict products from reagent names, remove water, determine an
unknown polymerization site or certify a complete name. Explicit stereo outside
the supported class is preserved as unsupported, never stripped.

Absent structure or connection evidence, read a targeted source/image only when
it can resolve the identity gap; otherwise retain the partial identity. Local
motifs do not establish reaction, rate, selectivity or actual sample composition.
These helpers are optional, not extra review stages.
