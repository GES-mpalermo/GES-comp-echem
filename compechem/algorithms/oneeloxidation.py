import os, shutil, pickle
import numpy as np
from dataclasses import dataclass

from compechem.molecule import Molecule
from compechem import tools
from compechem.functions.pka import calculate_pka
from compechem.functions.potential import calculate_potential
from compechem.calculators import crest
from compechem.calculators.xtb import XtbInput


xtb = XtbInput()


@dataclass
class Container:
    """Dataclass containing the singlets and radicals lists"""

    singlets: list = []
    radicals: list = []


def calculate_deprotomers(mol: Molecule, method, nproc: int, conformer_search: bool = True):
    """Calculates all the deprotomers with a pKa < 20 for a given Molecule object

    Parameters
    ----------
    mol : Molecule object
        Molecule object of the molecule under examination
    method : calculator
        Calculator object (i.e., XtbInput/OrcaInput object) giving the level of theory at which
        to evaluate the pKa for the deprotomers.
    nproc : int
        number of cores, by default 1
    conformer_search : Bool
        If True (default), also carries out conformer searches at all stages

    Returns
    -------
    mol_list : list
        List containing all the deprotomers with pKa < 20 for the given molecule
    """

    mol_list = []

    if conformer_search:
        mol = crest.conformer_search(mol, nproc=nproc)[0]
    xtb.opt(mol, inplace=True)

    if type(method) != XtbInput:
        method.spe(mol, inplace=True)

    pKa = 0
    i = 1
    currently_protonated = mol

    while pKa < 20:

        deprotomer_list = crest.deprotonate(currently_protonated, nproc=nproc)

        if type(method) != XtbInput:
            deprotomer_list = tools.reorder_energies(
                deprotomer_list, nproc=nproc, method_opt=xtb, method_el=method, method_vib=xtb
            )

        if deprotomer_list:
            currently_deprotonated = deprotomer_list[0]

        # if deprotonation is unsuccessful (e.g., topology change), save the molecule but with
        # sentinel values for pKa (which cannot be calculated)
        else:
            mol_list.append([currently_protonated, None, None])
            break

        if conformer_search:
            currently_deprotonated = crest.conformer_search(currently_deprotonated, nproc=nproc)[0]

        xtb.opt(currently_deprotonated, inplace=True)
        if type(method) != XtbInput:
            method.spe(currently_deprotonated, inplace=True)

        try:
            pKa = calculate_pka(
                protonated=currently_protonated,
                deprotonated=currently_deprotonated,
                method_el=method.method,
                method_vib=xtb.method,
            )

        except:
            pKa = None

        print(
            f"INFO: {currently_protonated.name} (charge {currently_protonated.charge} spin {currently_protonated.spin}) pKa{i} = {pKa} ({method.method})"
        )

        currently_protonated.properties.pka[method.method] = pKa

        mol_list.append(currently_protonated)

        if pKa is None:
            break
        else:
            currently_protonated = currently_deprotonated
            i += 1

    return mol_list


def calculate_states(
    filepath: str, method, nproc: int, conformer_search: bool = True, tautomer_search: bool = True
):
    """Carries out all the calculations for the singlet and radical species to be used in the
    calculate_potential function, given a file path with a .xyz file
    
    Parameters
    ----------
    filepath : str
        Path to the .xyz file to be used in the calculation
    method : calculator
        Calculator object (i.e., XtbInput/OrcaInput object) giving the level of theory at which
        to evaluate the pKa for the deprotomers.
    nproc : int
        number of cores, by default 1
    conformer_search : Bool
        If True (default), also carries out a preliminary conformer search on the given structure
    tautomer_search : Bool
        If True (default), also carries out a preliminary conformer search on the given structure

    Returns
    -------
    container : Container
        Container object with the singlets and radicals for the given input molecule
    """

    container = Container()

    base_mol = Molecule(filepath, charge=0, spin=1)
    molname = base_mol.name

    try:
        if conformer_search:
            base_mol = crest.conformer_search(base_mol, nproc=nproc, optionals="--noreftopo")[0]
        if tautomer_search:
            base_mol = crest.tautomer_search(base_mol, nproc=nproc, optionals="--noreftopo")[0]

        ### SINGLET SPECIES ###
        singlet = xtb.spe(base_mol, charge=0, spin=1)
        container.singlets = calculate_deprotomers(
            mol=singlet, method=method, nproc=nproc, conformer_search=conformer_search
        )

        ### RADICAL SPECIES ###
        radical = xtb.spe(base_mol, charge=1, spin=2)
        container.radicals = calculate_deprotomers(
            mol=radical, method=method, nproc=nproc, conformer_search=conformer_search
        )

    except:
        print(f"ERROR: Error occurred for {molname}! Skipping molecule")
        return

    return container


def potential_calculation(container: Container, method, step: float = 1.0):
    """Calculates the 1-el oxidation potential for the given molecule in the pH range 0-14

    Parameters
    ----------
    container : Container
        Container object with the singlet and radical deprotomers for the input molecule
    method : calculator
        Calculator object (i.e., XtbInput/OrcaInput object) giving the level of theory at which
        to evaluate the pKa for the deprotomers.
    step : float
        pH step at which the potential is calculated (by default, 1.0 pH units)


    Returns
    -------
    potential : list? csv?

    """

    print("INFO: starting potentials calculation")

    potentials = ["molname,singlet_pKa,radical_pKa,pH,potential"]

    last_potential = None

    molname = container.singlets[0].name

    singlets = container.singlets
    radicals = container.radicals

    potentials_mol = []

    for current_pH in np.around(np.arange(0, 14, step), 1):

        # getting deprotomers with pKa > current_pH or with sentinel value (deprotonation was
        # unsuccessful)
        for singlet in singlets:
            pka = singlet.properties.pka[method.method]
            if pka is None or pka > current_pH:
                current_singlet = singlet
                current_singlet_pka = pka
                break

        for radical in radicals:
            pka = radical.properties.pka[method.method]
            if pka is None or pka > current_pH:
                current_radical = radical
                current_radical_pka = pka
                break

        potential = potential.calculate_potential(
            oxidised=current_radical,
            reduced=current_singlet,
            pH=current_pH,
            method_el=method.method,
            method_vib=xtb.method,
        )

        potentials_mol.append([current_singlet_pka, current_radical_pka, current_pH, potential])

        if last_potential is not None and abs(potential - last_potential) > 0.1:
            print(
                f"WARNING: potential changed by {abs(potential - last_potential)} at pH {current_pH}"
            )
        last_potential = potential

    for i in potentials_mol:
        potentials.append(f"{molname},{i[0]},{i[1]},{i[2]},{i[3]}")

    with open("potentials.csv", "w") as out:
        for i in potentials:
            out.write(f"{i}\n")
    print("INFO: created file potentials.csv")


def main():

    os.makedirs("pickle_files", exist_ok=True)

    pickle.dump(container, open(f"pickle_files/{molname}.ctr", "wb"))
