import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const molecule = JSON.parse(await readFile(new URL("../src/data/molecules/ethane.json", import.meta.url), "utf8"));

test("decorative ethane uses the NIST C2H6 composition and saturated valences", () => {
  assert.equal(molecule.atoms.filter(a => a.element === "C").length, 2);
  assert.equal(molecule.atoms.filter(a => a.element === "H").length, 6);
  assert.equal(molecule.bonds.length, 7);
  const degrees = molecule.atoms.map(() => 0);
  const unique = new Set();
  for (const [a, b] of molecule.bonds) {
    assert.notEqual(a, b);
    assert.ok(molecule.atoms[a] && molecule.atoms[b]);
    const pair = [a, b].sort((x, y) => x - y).join(":");
    assert.ok(!unique.has(pair));
    unique.add(pair);
    degrees[a]++; degrees[b]++;
    const distance = Math.hypot(...molecule.atoms[a].position.map((v, i) => v - molecule.atoms[b].position[i]));
    const expected = molecule.atoms[a].element === molecule.atoms[b].element ? 1.536 : 1.091;
    assert.ok(Math.abs(distance - expected) < 0.0001, `bond ${pair}: ${distance}`);
  }
  molecule.atoms.forEach((a, i) => assert.equal(degrees[i], a.element === "C" ? 4 : 1));
});
