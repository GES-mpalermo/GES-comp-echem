from compechem.config import get_ncores
from compechem.core.base import Engine
from compechem.systems import System
from compechem.engines.orca import M06
from compechem.engines.xtb import XtbInput
import logging
from typing import List

logger = logging.getLogger(__name__)


def reorder_energies(
    system_list: List[System],
    ncores: int = None,
    maxcore: int = 350,
    method_opt: Engine = None,
    method_el: Engine = None,
    method_vib: Engine = None,
):
    """Reorders a System list (generated by a CREST routine such as deprotonation) at a different
    level of theory.

    Parameters
    ----------
    system_list : list(System)
        list containing the System objects to be reordered (e.g., generated by a CREST routine)
    ncores : int, optional
        number of cores, by default all available cores
    maxcore : int, optional
        memory per core, in MB, by default 350
    method_opt : XtbInput/OrcaInput, optional
        level of theory for the geometry optimization. By default converted to gfn2
    method_el : XtbInput/OrcaInput, optional
        level of theory for the electronic part of the energy. By default converted to M06-2X
    method_vib : XtbInput/OrcaInput, optional
        level of theory for the vibronic contribution to the energy. By default converted to gfn2

    Returns
    -------
    molecule_list : list(System)
        System list, reordered at the new level of theory.
    """

    if ncores is None:
        ncores = get_ncores()

    if method_opt is None:
        method_opt = XtbInput()
    if method_el is None:
        method_el = M06()
    if method_vib is None:
        method_vib = XtbInput()

    def get_total_energy(molecule: System):
        return molecule.properties.electronic_energy + molecule.properties.vibronic_energy

    for system in system_list:

        method_opt.opt(system, ncores=ncores, maxcore=maxcore, inplace=True)

        if method_el.level_of_theory != system.properties.level_of_theory_electronic:
            method_el.spe(system, ncores=ncores, maxcore=maxcore, inplace=True)

        if method_vib.level_of_theory != system.properties.level_of_theory_vibronic:
            dummy = method_vib.freq(system, ncores=ncores, maxcore=maxcore)
            system.properties.set_vibronic_energy(dummy.properties.vibronic_energy, method_vib)

    system_list.sort(key=get_total_energy)

    return system_list
