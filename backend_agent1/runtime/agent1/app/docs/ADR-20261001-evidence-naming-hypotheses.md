# Explicit names under evidence limits

Task: IDENTITY-PARITY-RERUN-20261001-01. Authorized by the user's request to rerun four papers, restore the old reading design, and provide useful IUPAC names under a wider valid scope or a clearly stated most-likely hypothesis.

Runtime stays 0.9.0. The frozen-name-candidate/0.9.0, iupac-supported-naming/1.0 and /1.1, and identity-evidence-nomenclature/1.0 namespaces retain their previous meanings. Saved versions remain immutable and readable. No gold, manual reference, catalog formula or expected-structure lookup is used as a solver.

New execution opts into iupac-name-required/1.0 and identity-evidence-nomenclature/1.1. Existing source, state, network and blend paths are reused. New declared paths are bounded to one polymeric graft source, simultaneous unspecified-site monovalent substituents, and explicitly selected finite alternatives. Hypotheses are sourced statements with a rationale and remain separate from source facts. They propagate into dependent blend names; unknown positions, lengths, sequence, composition basis and original conflicts remain recorded.

Names and evidence are different claims. Rule checks cover the declared source/assembly/substituent scope, not independent certification of a preferred IUPAC name or proof of a unique real material. Parser success alone is never that certification. Preferred names remain null and independent review remains NOT_REVIEWED.

Component names are prepared from the original text and current Registry through the same Kernel before actual OPSIN calls. The source spelling, alias, full query, origin, assumptions and real receipt are retained. Registry results are candidates, not new source facts. A failed source abbreviation must not be cached as evidence that its expanded chemical name is unsupported.

Monovalent substituent verification explicitly enables OPSIN radicals in a separate provider namespace. The frozen finite-molecule parser still rejects names consisting only of substituents. One dummy free valence is converted to one radical only for graph comparison, retaining stereo, isotope and charge; disconnected/multiple-free-valence targets are outside this profile. No tool predicts polymerization, graft distribution or a unique network topology.

IUPAC bases: [Brief Guide, §§3.1–3.3](https://iupac.qmul.ac.uk/BriefGuide/polymer.html), [chemical modification, MP-2.5](https://doi.org/10.1515/pac-2014-0610), [source-based graft naming](https://doi.org/10.1515/pac-2015-0702). Unspecified positions permit a family name for point substituents; they do not justify applying -mod- to a proven polymeric branch or using -graft- for a single incorporated residue. Feed quantities stay separate from incorporated mass/mole fractions.

Validation: new generic tests use ethanol/ethyl and synthetic polyethylene cases, unrelated to the evaluation papers. Those fixtures are developer-generated, not independently reviewed chemical truth. Existing tests and frozen data are unchanged. The four paper outputs are sealed before comparison against previous results or human references.

Remaining scientific limits: source-based names are often useful before full structural nomenclature is available; general preferred-CRU direction, locants, complex substituent naming and independent chemical review still need expansion. Increase supported rules against independent reference cases and unseen positive/negative structures, rather than adding exact paper-specific aliases, answer tables or more model stages.
