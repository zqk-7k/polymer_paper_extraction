# Polymer Identity App

Read README.md and docs/STATUS.md before changing this application. Follow the current user task; saved jobs and historical evidence do not authorize further runs. Four first paper attempts are sealed. Do not start a fifth paper or old queues without a new request.

Runtime chemistry remains 0.9.0. Use the existing Kernel/create_passport/NamingService. A candidate graph, deterministic rule name, most likely IUPAC candidate, certified preferred name and real material identity are separate claims. Preserve stereo, isotope, salt, charge, maps, ports, occurrences, graft roles, unknowns and replayable prior versions. Never label model output as independent chemical review.

Normal application code uses this directory and sibling Polymer_Identity_App_Data. Do not import from or write to Polymer_Identity_V1, shared catalog databases, original raw data or frozen reports. Private credentials belong outside source control. New job work belongs in a new job directory. Preserve adopted bundles and sealed receipts; do not rewrite first-run evidence after repairs.

Each explicitly requested paper uses one persistent gpt-6.1-sol/xhigh Codex CLI session, workspace-write, one paper at a time. A resumed session retains its original deadline. The core sees only its neutral source, current state and domain tools. Human references and old results are post-seal reading material only, never solver input or tuning data. Do not add scoring/comparison modules.

Use `python -m pytest tests -q`, `node tests/test_reader.cjs`, and `node --check web/app.js` for relevant engineering changes. Passing tests is not independent chemical validation. Source and execution manifests distinguish the first four-run code snapshot from later reader polish.
