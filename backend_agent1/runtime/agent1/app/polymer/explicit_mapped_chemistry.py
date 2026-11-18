"""Supplied mapped graph edits only; source verification belongs to the host."""
from copy import deepcopy

try:
    from rdkit import Chem
except ImportError:
    Chem = None

CONTRACT = "explicit-mapped-chemistry/1.0"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sources(value):
    _require(isinstance(value, list) and bool(value) and
             all(isinstance(x, str) and x.strip() for x in value),
             "Explicit nonempty source IDs are required; host must verify them")


def _integer(value):
    return type(value) is int and value > 0


def _parse(smiles):
    _require(isinstance(smiles, str) and 0 < len(smiles) <= 12000, "SMILES required (at most 12000 characters)")
    _require(not any(c.isspace() for c in smiles) and "|" not in smiles,
             "Names, whitespace and CX payloads are unsupported")
    _require(not any(c in smiles for c in "@/\\"), "Stereo unsupported; raw input preserved")
    params = Chem.SmilesParserParams()
    params.removeHs, params.parseName, params.allowCXSMILES = False, False, False
    mol = Chem.MolFromSmiles(smiles, params)
    _require(mol is not None and 0 < mol.GetNumAtoms() <= 300,
             "Invalid SMILES, valence, or atom count (1..300)")
    _require(not any(a.GetNumRadicalElectrons() for a in mol.GetAtoms()), "Radical edits unsupported; raw input preserved")
    maps = [a.GetAtomMapNum() for a in mol.GetAtoms()]
    _require(all(m > 0 for m in maps) and len(set(maps)) == len(maps),
             "Every atom, including explicit H and dummies, needs a unique positive map")
    _require(all(a.GetChiralTag() == Chem.ChiralType.CHI_UNSPECIFIED for a in mol.GetAtoms())
             and all(b.GetStereo() == Chem.BondStereo.STEREONONE and
                     b.GetBondDir() == Chem.BondDir.NONE for b in mol.GetBonds()),
             "Stereo unsupported; raw input preserved")
    return mol, {a.GetAtomMapNum(): a for a in mol.GetAtoms()}


def _atom(a):
    return dict(atom_map=a.GetAtomMapNum(), input_index=a.GetIdx(),
                element=a.GetSymbol(), atomic_number=a.GetAtomicNum(), isotope=a.GetIsotope(),
                formal_charge=a.GetFormalCharge(), explicit_h=a.GetNumExplicitHs(),
                implicit_h=a.GetNumImplicitHs(), total_h=a.GetTotalNumHs(includeNeighbors=True),
                aromatic=a.GetIsAromatic(), radical_electrons=a.GetNumRadicalElectrons(),
                no_implicit=a.GetNoImplicit())


def _bonds(mol):
    return {tuple(sorted((b.GetBeginAtom().GetAtomMapNum(), b.GetEndAtom().GetAtomMapNum()))):
            str(b.GetBondType()) for b in mol.GetBonds()}


def _bond_records(bonds):
    return [dict(atom_maps=list(pair), bond_type=bonds[pair]) for pair in sorted(bonds)]


def _run(spec, operation):
    raw = deepcopy(spec)
    extra = raw.get("uncertainties", []) if isinstance(raw, dict) else []
    result = dict(contract=CONTRACT, status="UNDETERMINED", raw_inputs=raw,
                  uncertainties=deepcopy(extra if isinstance(extra, list) else [extra]),
                  source_fact=False, automatic_update=False, full_iupac_conformance=False,
                  independently_verified=False,
                  assumptions=["Caller-supplied edit, not reaction proof or a reaction prediction.",
                               "Source IDs are supplied; source verification belongs to the host."])
    result["uncertainties"].append("Actual sample transformation and chemical identity are unverified.")
    if Chem is None:
        result.update(status="TOOL_UNAVAILABLE", reason="RDKit unavailable")
        return result
    try:
        _require(isinstance(raw, dict), "Specification must be an object")
        _sources(raw.get("src"))
        result.update(operation(deepcopy(raw)))
        result["status"] = "CANDIDATE"
    except (ValueError, TypeError, KeyError, RuntimeError, OverflowError) as exc:
        result["reason"] = str(exc)
        result["uncertainties"].append(str(exc))
    return result


def residue(spec):
    """Apply only explicitly selected retention, boundary cuts and H replacements."""
    return _run(spec, _residue)


def _residue(spec):
    mol, atoms = _parse(spec.get("smiles"))
    keep_list, ports = spec.get("retain_maps"), spec.get("ports")
    _require(isinstance(keep_list, list) and bool(keep_list) and
             all(_integer(m) for m in keep_list), "retain_maps must be positive integers")
    keep = set(keep_list)
    _require(len(keep) == len(keep_list) and keep <= atoms.keys(), "Invalid retained maps")
    _require(isinstance(ports, list) and len(ports) <= 20, "ports must be a list of at most 20")
    removed = set(atoms) - keep
    crossing = {(a, b) for a in keep for b in removed
                if mol.GetBondBetweenAtoms(atoms[a].GetIdx(), atoms[b].GetIdx()) is not None}
    declared, new_maps, h_loss = set(), set(), {}
    for p in ports:
        _require(isinstance(p, dict), "Port must be an object")
        _sources(p.get("src"))
        a, new = p.get("anchor_map"), p.get("port_map")
        _require(_integer(a) and a in keep, "Port anchor must be retained")
        _require(_integer(new) and new not in atoms and new not in new_maps,
                 "Port map must be new and noncolliding")
        new_maps.add(new)
        if "departing_map" in p:
            d = p["departing_map"]
            _require(_integer(d) and d in removed and (a, d) in crossing,
                     "Departing map must identify a removed neighbor")
            _require("hydrogen_delta" not in p, "Cut and hydrogen replacement cannot be combined")
            _require((a, d) not in declared, "Duplicate cut declaration")
            bond = mol.GetBondBetweenAtoms(atoms[a].GetIdx(), atoms[d].GetIdx())
            _require(bond.GetBondType() == Chem.BondType.SINGLE, "Crossing bonds must be single")
            declared.add((a, d))
        else:
            _require(type(p.get("hydrogen_delta")) is int and p["hydrogen_delta"] == -1,
                     "A port without departing_map requires hydrogen_delta=-1")
            h_loss[a] = h_loss.get(a, 0) + 1
            _require(h_loss[a] <= atoms[a].GetNumExplicitHs() + atoms[a].GetNumImplicitHs(),
                     "No available nonisotopic implicit/bracket hydrogen")
    _require(declared == crossing, "Every crossing bond must be declared exactly once")
    for component in Chem.GetMolFrags(mol):
        _require(any(mol.GetAtomWithIdx(i).GetAtomMapNum() in keep for i in component),
                 "A wholly disconnected original component cannot be removed")
    records = {m: _atom(a) for m, a in atoms.items()}
    original_bonds = _bonds(mol)
    fragments, pending = [], set(removed)
    while pending:
        group, stack = set(), [min(pending)]
        while stack:
            m = stack.pop()
            if m in group:
                continue
            group.add(m)
            stack.extend(n.GetAtomMapNum() for n in atoms[m].GetNeighbors()
                         if n.GetAtomMapNum() in removed and n.GetAtomMapNum() not in group)
        pending -= group
        internal = {p: order for p, order in original_bonds.items() if set(p) <= group}
        fragments.append(dict(atom_maps=sorted(group), atoms=[records[m] for m in sorted(group)],
                              bonds=_bond_records(internal), asserted_byproduct=False,
                              input_subgraph_smiles=Chem.MolFragmentToSmiles(
                                  mol, atomsToUse=sorted(atoms[m].GetIdx() for m in group),
                                  canonical=False, allHsExplicit=True)))
    edit = Chem.RWMol(mol)
    for m in keep:
        atom = edit.GetAtomWithIdx(atoms[m].GetIdx())
        atom.SetNumExplicitHs(records[m]["explicit_h"] + records[m]["implicit_h"] - h_loss.get(m, 0))
        atom.SetNoImplicit(True)
    for i in sorted((atoms[m].GetIdx() for m in removed), reverse=True):
        edit.RemoveAtom(i)
    indices = {a.GetAtomMapNum(): a.GetIdx() for a in edit.GetAtoms()}
    for p in ports:
        dummy = Chem.Atom(0)
        dummy.SetAtomMapNum(p["port_map"])
        edit.AddBond(indices[p["anchor_map"]], edit.AddAtom(dummy), Chem.BondType.SINGLE)
    product = edit.GetMol()
    Chem.SanitizeMol(product)
    smiles = Chem.MolToSmiles(product)
    _, final_atoms = _parse(smiles)
    _require(set(final_atoms) == keep | new_maps, "Output atom accounting failed")
    for m in keep:
        before, after = records[m], _atom(final_atoms[m])
        _require(all(before[k] == after[k] for k in ("element", "isotope", "formal_charge")),
                 "Retained element, isotope or charge changed")
        cut_h = sum(atoms[d].GetAtomicNum() == 1 for a, d in declared if a == m)
        _require(after["total_h"] == before["total_h"] - h_loss.get(m, 0) - cut_h,
                 "Undeclared retained-atom hydrogen change")
    open_ports = [dict(deepcopy(p), origin="supplied_edit") for p in ports]
    open_ports.extend(dict(port_map=m, anchor_maps=sorted(n.GetAtomMapNum() for n in
                      final_atoms[m].GetNeighbors()), origin="retained_input_dummy")
                      for m in sorted(keep) if atoms[m].GetAtomicNum() == 0)
    return dict(residue_smiles=smiles, removed_atoms=[records[m] for m in sorted(removed)],
                removed_fragments=fragments, open_ports=open_ports,
                atom_correspondence=[dict(atom_map=m, input_index=atoms[m].GetIdx(),
                                         disposition="retained" if m in keep else "explicitly_removed",
                                         output_map=m if m in keep else None) for m in sorted(atoms)])


def modification(spec):
    """Compare two supplied mapped graphs; never infer grafts or reaction mechanisms."""
    return _run(spec, _modification)


def _modification(spec):
    before, old = _parse(spec.get("before_smiles"))
    after, new = _parse(spec.get("after_smiles"))
    shared = old.keys() & new.keys()
    for m in shared:
        _require(old[m].GetAtomicNum() == new[m].GetAtomicNum() and
                 old[m].GetIsotope() == new[m].GetIsotope(),
                 "A conserved map cannot change element or isotope")
    ob, nb = _bonds(before), _bonds(after)
    added = _bond_records({p: nb[p] for p in nb.keys() - ob.keys()})
    removed = _bond_records({p: ob[p] for p in ob.keys() - nb.keys()})
    orders = [dict(atom_maps=list(p), before=ob[p], after=nb[p])
              for p in sorted(ob.keys() & nb.keys()) if ob[p] != nb[p]]
    charges, hydrogens = [], []
    for m in sorted(shared):
        for target, a, b in ((charges, old[m].GetFormalCharge(), new[m].GetFormalCharge()),
                             (hydrogens, old[m].GetTotalNumHs(includeNeighbors=True),
                              new[m].GetTotalNumHs(includeNeighbors=True))):
            if a != b:
                target.append(dict(atom_map=m, before=a, after=b, delta=b-a))
    graph_change = bool(added or removed or orders or old.keys() != new.keys())
    kind = "BOND_GRAPH_CHANGE" if graph_change else (
        "CHARGE_OR_HYDROGEN_CHANGE" if charges or hydrogens else "NO_GRAPH_CHANGE")
    return dict(modification_kind=kind, conserved_atoms=[dict(atom_map=m, before=_atom(old[m]),
                after=_atom(new[m])) for m in sorted(shared)],
                added_atoms=[_atom(new[m]) for m in sorted(new.keys() - old.keys())],
                removed_atoms=[_atom(old[m]) for m in sorted(old.keys() - new.keys())],
                bonds_added=added, bonds_removed=removed, bond_order_changes=orders,
                charge_changes=charges, total_h_changes=hydrogens,
                covalent_bond_change=any(order not in ("DATIVE", "DATIVEONE", "DATIVEL", "DATIVER", "ZERO")
                    for item in added + removed + orders for order in
                    ([item["bond_type"]] if "bond_type" in item else [item["before"], item["after"]])))
