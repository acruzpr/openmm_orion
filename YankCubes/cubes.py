import traceback
from openeye import oechem
import netCDF4 as netcdf
from tempfile import TemporaryDirectory
from floe.api import parameter, ParallelOEMolComputeCube
from LigPrepCubes.ports import CustomMoleculeInputPort, CustomMoleculeOutputPort
from YankCubes.utils import molecule_is_charged, download_dataset_to_file
from yank.experiment import ExperimentBuilder
from oeommtools import utils as oeommutils
from oeommtools import data_utils
from simtk.openmm import app, unit, XmlSerializer, openmm
import os
import numpy as np
import yaml
from yank.analyze import get_analyzer
from YankCubes.yank_templates import yank_solvation_template

################################################################################
# Hydration free energy calculations
################################################################################

hydration_yaml_template = """\
---
options:
  minimize: no
  timestep: %(timestep)f*femtoseconds
  nsteps_per_iteration: %(nsteps_per_iteration)d
  number_of_iterations: %(number_of_iterations)d
  temperature: %(temperature)f*kelvin
  pressure: %(pressure)f*atmosphere
  anisotropic_dispersion_correction: yes
  anisotropic_dispersion_cutoff: 9*angstroms
  output_dir: %(output_directory)s
  verbose: %(verbose)s

molecules:
  input_molecule:
    filepath: %(output_directory)s/input.mol2
    antechamber:
      charge_method: null

solvents:
  tip3p:
    nonbonded_method: PME
    nonbonded_cutoff: 9*angstroms
    clearance: 8*angstroms
    ewald_error_tolerance: 1.0e-4
  gbsa:
    nonbonded_method: NoCutoff
    implicit_solvent: OBC2
  vacuum:
    nonbonded_method: NoCutoff

systems:
  hydration-tip3p:
    solute: input_molecule
    solvent1: tip3p
    solvent2: vacuum
    leap:
      parameters: [leaprc.gaff, leaprc.protein.ff14SB, leaprc.water.tip3p]
  hydration-gbsa:
    solute: input_molecule
    solvent1: gbsa
    solvent2: vacuum
    leap:
      parameters: [leaprc.gaff, leaprc.protein.ff14SB, leaprc.water.tip3p]

protocols:
  protocol-tip3p:
    solvent1:
      alchemical_path:
        lambda_electrostatics: [1.00, 0.75, 0.50, 0.25, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00]
        lambda_sterics:        [1.00, 1.00, 1.00, 1.00, 1.00, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10, 0.00]
    solvent2:
      alchemical_path:
        lambda_electrostatics: [1.00, 0.75, 0.50, 0.25, 0.00, 0.00]
        lambda_sterics:        [1.00, 1.00, 1.00, 1.00, 1.00, 0.00]
  protocol-gbsa:
    solvent1:
      alchemical_path:
        lambda_electrostatics: [1.00, 0.00]
        lambda_sterics:        [1.00, 0.00]
    solvent2:
      alchemical_path:
        lambda_electrostatics: [1.00, 0.00]
        lambda_sterics:        [1.00, 0.00]

experiments:
  system: hydration-%(solvent)s
  protocol: protocol-%(solvent)s
"""

class YankHydrationCube(ParallelOEMolComputeCube):
    title = "YankHydrationCube"
    description = """
    Compute the hydration free energy of a small molecule with YANK.

    This cube uses the YANK alchemical free energy code to compute the
    transfer free energy of one or more small molecules from gas phase
    to TIP3P solvent.

    See http://getyank.org for more information about YANK.
    """
    classification = ["Alchemical free energy calculations"]
    tags = [tag for lists in classification for tag in lists]

    # Override defaults for some parameters
    parameter_overrides = {
        "prefetch_count": {"default": 1}, # 1 molecule at a time
        "item_timeout": {"default": 3600}, # Default 1 hour limit (units are seconds)
        "item_count": {"default": 1} # 1 molecule at a time
    }

    #Define Custom Ports to handle oeb.gz files
    intake = CustomMoleculeInputPort('intake')
    success = CustomMoleculeOutputPort('success')
    failure = CustomMoleculeOutputPort('failure')

    # These can override YAML parameters
    nsteps_per_iteration = parameter.IntegerParameter('nsteps_per_iteration', default=500,
                                     help_text="Number of steps per iteration")

    timestep = parameter.DecimalParameter('timestep', default=2.0,
                                     help_text="Timestep (fs)")

    simulation_time = parameter.DecimalParameter('simulation_time', default=0.100,
                                     help_text="Simulation time (ns/replica)")

    temperature = parameter.DecimalParameter('temperature', default=300.0,
                                     help_text="Temperature (Kelvin)")

    pressure = parameter.DecimalParameter('pressure', default=1.0,
                                 help_text="Pressure (atm)")

    solvent = parameter.StringParameter('solvent', default='gbsa',
                                 choices=['gbsa', 'tip3p'],
                                 help_text="Solvent choice: one of ['gbsa', 'tip3p']")

    verbose = parameter.BooleanParameter('verbose', default=False,
                                     help_text="Print verbose YANK logging output")

    def construct_yaml(self, **kwargs):
        # Make substitutions to YAML here.
        # TODO: Can we override YAML parameters without having to do string substitutions?
        options = {
            'timestep' : self.args.timestep,
            'nsteps_per_iteration' : self.args.nsteps_per_iteration,
            'number_of_iterations' : int(np.ceil(self.args.simulation_time * unit.nanoseconds / (self.args.nsteps_per_iteration * self.args.timestep * unit.femtoseconds))),
            'temperature' : self.args.temperature,
            'pressure' : self.args.pressure,
            'solvent' : self.args.solvent,
            'verbose' : 'yes' if self.args.verbose else 'no',
        }

        for parameter in kwargs.keys():
            options[parameter] = kwargs[parameter]

        return hydration_yaml_template % options

    def begin(self):
        # TODO: Is there another idiom to use to check valid input?
        if self.args.solvent not in ['gbsa', 'tip3p']:
            raise Exception("solvent must be one of ['gbsa', 'tip3p']")

        # Compute kT
        kB = unit.BOLTZMANN_CONSTANT_kB * unit.AVOGADRO_CONSTANT_NA # Boltzmann constant
        self.kT = kB * (self.args.temperature * unit.kelvin)

    def process(self, mol, port):
        kT_in_kcal_per_mole = self.kT.value_in_unit(unit.kilocalories_per_mole)

        # Retrieve data about which molecule we are processing
        title = mol.GetTitle()

        with TemporaryDirectory() as output_directory:
            try:
                # Print out which molecule we are processing
                self.log.info('Processing {} in directory {}.'.format(title, output_directory))

                # Check that molecule is charged.
                if not molecule_is_charged(mol):
                    raise Exception('Molecule %s has no charges; input molecules must be charged.' % mol.GetTitle())

                # Write the specified molecule out to a mol2 file without changing its name.
                mol2_filename = os.path.join(output_directory, 'input.mol2')
                ofs = oechem.oemolostream(mol2_filename)
                oechem.OEWriteMol2File(ofs, mol)

                # Undo oechem fuckery with naming mol2 substructures `<0>`
                from YankCubes.utils import unfuck_oechem_mol2_file
                unfuck_oechem_mol2_file(mol2_filename)

                # Run YANK on the specified molecule.
                from yank.yamlbuild import YamlBuilder
                yaml = self.construct_yaml(output_directory=output_directory)
                yaml_builder = YamlBuilder(yaml)
                yaml_builder.build_experiments()
                self.log.info('Ran Yank experiments for molecule {}.'.format(title))

                # Analyze the hydration free energy.
                from yank.analyze import estimate_free_energies
                (Deltaf_ij_solvent, dDeltaf_ij_solvent) = estimate_free_energies(netcdf.Dataset(output_directory + '/experiments/solvent1.nc', 'r'))
                (Deltaf_ij_vacuum,  dDeltaf_ij_vacuum)  = estimate_free_energies(netcdf.Dataset(output_directory + '/experiments/solvent2.nc', 'r'))
                DeltaG_hydration = Deltaf_ij_vacuum[0,-1] - Deltaf_ij_solvent[0,-1]
                dDeltaG_hydration = np.sqrt(Deltaf_ij_vacuum[0,-1]**2 + Deltaf_ij_solvent[0,-1]**2)

                # Add result to original molecule
                oechem.OESetSDData(mol, 'DeltaG_yank_hydration', str(DeltaG_hydration * kT_in_kcal_per_mole))
                oechem.OESetSDData(mol, 'dDeltaG_yank_hydration', str(dDeltaG_hydration * kT_in_kcal_per_mole))
                self.log.info('Analyzed and stored hydration free energy for molecule {}.'.format(title))

                # Emit molecule to success port.
                self.success.emit(mol)

            except Exception as e:
                self.log.info('Exception encountered when processing molecule {}.'.format(title))
                # Attach error message to the molecule that failed
                # TODO: If there is an error in the leap setup log,
                # we should capture that and attach it to the failed molecule.
                self.log.error(traceback.format_exc())
                mol.SetData('error', str(e))
                # Return failed molecule
                self.failure.emit(mol)

################################################################################
# Binding free energy calculations
################################################################################

binding_yaml_template = """\
---
options:
  minimize: %(minimize)s
  timestep: %(timestep)f*femtoseconds
  nsteps_per_iteration: %(nsteps_per_iteration)d
  number_of_iterations: %(number_of_iterations)d
  temperature: %(temperature)f*kelvin
  pressure: %(pressure)f*atmosphere
  output_dir: %(output_directory)s
  verbose: %(verbose)s
  randomize_ligand: %(randomize_ligand)s

molecules:
  receptor:
    filepath: %(output_directory)s/receptor.pdb
    strip_protons: yes
  ligand:
    filepath: %(output_directory)s/input.mol2
    antechamber:
      charge_method: null

solvents:
  pme:
    nonbonded_method: PME
    nonbonded_cutoff: 9*angstroms
    ewald_error_tolerance: 1.0e-4
    clearance: 9*angstroms
    positive_ion: Na+
    negative_ion: Cl-
  rf:
    nonbonded_method: CutoffPeriodic
    nonbonded_cutoff: 9*angstroms
    clearance: 9*angstroms
    positive_ion: Na+
    negative_ion: Cl-
  gbsa:
    nonbonded_method: NoCutoff
    implicit_solvent: OBC2

systems:
  binding-pme:
    receptor: receptor
    ligand: ligand
    solvent: pme
    leap:
      parameters: [leaprc.protein.ff14SB, leaprc.gaff2, leaprc.water.tip3p]
  binding-rf:
    receptor: receptor
    ligand: ligand
    solvent: rf
    leap:
      parameters: [leaprc.protein.ff14SB, leaprc.gaff2, leaprc.water.tip3p]
  binding-gbsa:
    receptor: receptor
    ligand: ligand
    solvent: gbsa
    leap:
      parameters: [leaprc.protein.ff14SB, leaprc.gaff2, leaprc.water.tip3p]

protocols:
  protocol:
    complex:
      alchemical_path:
        lambda_electrostatics: [1.00, 0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00]
        lambda_sterics:        [1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10, 0.00]
        lambda_restraints:     [1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00]
    solvent:
      alchemical_path:
        lambda_electrostatics: [1.00, 0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00]
        lambda_sterics:        [1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10, 0.00]

experiments:
  system: binding-%(solvent)s
  protocol: protocol
  restraint:
    type: Harmonic
"""

class YankBindingCube(ParallelOEMolComputeCube):
    title = "YankBindingCube"
    description = """
    Compute thebinding free energy of a small molecule with YANK.

    This cube uses the YANK alchemical free energy code to compute the binding
    free energy of one or more small molecules using harmonic restraints.

    See http://getyank.org for more information about YANK.
    """
    classification = ["Alchemical free energy calculations"]
    tags = [tag for lists in classification for tag in lists]

    # Override defaults for some parameters
    parameter_overrides = {
        "prefetch_count": {"default": 1}, # 1 molecule at a time
        "item_timeout": {"default": 3600}, # Default 1 hour limit (units are seconds)
        "item_count": {"default": 1} # 1 molecule at a time
    }

    #Define Custom Ports to handle oeb.gz files
    intake = CustomMoleculeInputPort('intake')
    success = CustomMoleculeOutputPort('success')
    failure = CustomMoleculeOutputPort('failure')

    # Receptor specification
    receptor = parameter.DataSetInputParameter(
        'receptor',
        required=True,
        help_text='Receptor structure file')

    # These can override YAML parameters
    nsteps_per_iteration = parameter.IntegerParameter('nsteps_per_iteration', default=500,
                                     help_text="Number of steps per iteration")

    timestep = parameter.DecimalParameter('timestep', default=2.0,
                                     help_text="Timestep (fs)")

    simulation_time = parameter.DecimalParameter('simulation_time', default=0.100,
                                     help_text="Simulation time (ns/replica)")

    temperature = parameter.DecimalParameter('temperature', default=300.0,
                                     help_text="Temperature (Kelvin)")

    pressure = parameter.DecimalParameter('pressure', default=1.0,
                                 help_text="Pressure (atm)")

    solvent = parameter.StringParameter('solvent', default='gbsa',
                                 choices=['gbsa', 'pme', 'rf'],
                                 help_text="Solvent choice ['gbsa', 'pme', 'rf']")

    minimize = parameter.BooleanParameter('minimize', default=True,
                                     help_text="Minimize initial structures for stability")

    randomize_ligand = parameter.BooleanParameter('randomize_ligand', default=False,
                                     help_text="Randomize initial ligand position (implicit only)")

    verbose = parameter.BooleanParameter('verbose', default=False,
                                     help_text="Print verbose YANK logging output")

    def construct_yaml(self, **kwargs):
        # Make substitutions to YAML here.
        # TODO: Can we override YAML parameters without having to do string substitutions?
        options = {
            'timestep' : self.args.timestep,
            'nsteps_per_iteration' : self.args.nsteps_per_iteration,
            'number_of_iterations' : int(np.ceil(self.args.simulation_time * unit.nanoseconds / (self.args.nsteps_per_iteration * self.args.timestep * unit.femtoseconds))),
            'temperature' : self.args.temperature,
            'pressure' : self.args.pressure,
            'solvent' : self.args.solvent,
            'minimize' : 'yes' if self.args.minimize else 'no',
            'verbose' : 'yes' if self.args.verbose else 'no',
            'randomize_ligand' : 'yes' if self.args.randomize_ligand else 'no',
        }

        for parameter in kwargs.keys():
            options[parameter] = kwargs[parameter]

        return binding_yaml_template % options

    def begin(self):
        # TODO: Is there another idiom to use to check valid input?
        if self.args.solvent not in ['gbsa', 'pme', 'rf']:
            raise Exception("solvent must be one of ['gbsa', 'pme', 'rf']")

        # Compute kT
        kB = unit.BOLTZMANN_CONSTANT_kB * unit.AVOGADRO_CONSTANT_NA # Boltzmann constant
        self.kT = kB * (self.args.temperature * unit.kelvin)

        # Load receptor
        self.receptor = oechem.OEMol()
        receptor_filename = download_dataset_to_file(self.args.receptor)
        with oechem.oemolistream(receptor_filename) as ifs:
            if not oechem.OEReadMolecule(ifs, self.receptor):
                raise RuntimeError("Error reading receptor")

    def process(self, mol, port):
        kT_in_kcal_per_mole = self.kT.value_in_unit(unit.kilocalories_per_mole)

        # Retrieve data about which molecule we are processing
        title = mol.GetTitle()

        with TemporaryDirectory() as output_directory:
            try:
                # Print out which molecule we are processing
                self.log.info('Processing {} in {}.'.format(title, output_directory))

                # Check that molecule is charged.
                if not molecule_is_charged(mol):
                    raise Exception('Molecule %s has no charges; input molecules must be charged.' % mol.GetTitle())


                # Write the receptor.
                pdbfilename = os.path.join(output_directory, 'receptor.pdb')
                with oechem.oemolostream(pdbfilename) as ofs:
                    res = oechem.OEWriteConstMolecule(ofs, self.receptor)
                    if res != oechem.OEWriteMolReturnCode_Success:
                        raise RuntimeError("Error writing receptor: {}".format(res))

                # Write the specified molecule out to a mol2 file without changing its name.
                mol2_filename = os.path.join(output_directory, 'input.mol2')
                ofs = oechem.oemolostream(mol2_filename)
                oechem.OEWriteMol2File(ofs, mol)

                # Undo oechem fuckery with naming mol2 substructures `<0>`
                from YankCubes.utils import unfuck_oechem_mol2_file
                unfuck_oechem_mol2_file(mol2_filename)

                # Run YANK on the specified molecule.
                from yank.yamlbuild import YamlBuilder
                yaml = self.construct_yaml(output_directory=output_directory)
                yaml_builder = YamlBuilder(yaml)
                yaml_builder.build_experiments()
                self.log.info('Ran Yank experiments for molecule {}.'.format(title))

                # Analyze the binding free energy
                # TODO: Use yank.analyze API for this
                from YankCubes.analysis import analyze
                store_directory = os.path.join(output_directory, 'experiments')
                [DeltaG_binding, dDeltaG_binding] = analyze(store_directory)

                """
                # Extract trajectory (DEBUG)
                from yank.analyze import extract_trajectory
                trajectory_filename = 'trajectory.pdb'
                store_filename = os.path.join(store_directory, 'complex.pdb')
                extract_trajectory(trajectory_filename, store_filename, state_index=0, keep_solvent=False,
                       discard_equilibration=True, image_molecules=True)
                ifs = oechem.oemolistream(trajectory_filename)
                ifs.SetConfTest(oechem.OEAbsCanonicalConfTest()) # load multi-conformer molecule
                mol = oechem.OEMol()
                for mol in ifs.GetOEMols():
                    print (mol.GetTitle(), "has", mol.NumConfs(), "conformers")
                ifs.close()
                os.remove(trajectory_filename)
                """

                # Attach binding free energy estimates to molecule
                oechem.OESetSDData(mol, 'DeltaG_yank_binding', str(DeltaG_binding * kT_in_kcal_per_mole))
                oechem.OESetSDData(mol, 'dDeltaG_yank_binding', str(dDeltaG_binding * kT_in_kcal_per_mole))
                self.log.info('Analyzed and stored binding free energy for molecule {}.'.format(title))

                # Emit molecule to success port.
                self.success.emit(mol)

            except Exception as e:
                self.log.info('Exception encountered when processing molecule {}.'.format(title))
                # Attach error message to the molecule that failed
                # TODO: If there is an error in the leap setup log,
                # we should capture that and attach it to the failed molecule.
                self.log.error(traceback.format_exc())
                mol.SetData('error', str(e))
                # Return failed molecule
                self.failure.emit(mol)


class YankSolvationFECube(ParallelOEMolComputeCube):
    version = "0.0.0"
    title = "YankSolvationFECube"
    description = """
    Compute the hydration free energy of a small molecule with YANK.

    This cube uses the YANK alchemical free energy code to compute the
    transfer free energy of one or more small molecules from gas phase
    to the selected solvent.

    See http://getyank.org for more information about YANK.
    """
    classification = ["Alchemical free energy calculations"]
    tags = [tag for lists in classification for tag in lists]

    # Override defaults for some parameters
    parameter_overrides = {
        "prefetch_count": {"default": 1},  # 1 molecule at a time
        "item_timeout": {"default": 43200},  # Default 12 hour limit (units are seconds)
        "item_count": {"default": 1}  # 1 molecule at a time
    }

    temperature = parameter.DecimalParameter(
        'temperature',
        default=300.0,
        help_text="Temperature (Kelvin)")

    pressure = parameter.DecimalParameter(
        'pressure',
        default=1.0,
        help_text="Pressure (atm)")

    minimize = parameter.BooleanParameter(
        'minimize',
        default=False,
        help_text="Minimize input system")

    iterations = parameter.IntegerParameter(
        'iterations',
        default=1000,
        help_text="Number of iterations")

    nsteps_per_iteration = parameter.IntegerParameter(
        'nsteps_per_iteration',
        default=500,
        help_text="Number of steps per iteration")

    timestep = parameter.DecimalParameter(
        'timestep',
        default=2.0,
        help_text="Timestep (fs)")

    nonbondedCutoff = parameter.DecimalParameter(
        'nonbondedCutoff',
        default=10.0,
        help_text="The non-bonded cutoff in angstroms")

    verbose = parameter.BooleanParameter(
        'verbose',
        default=False,
        help_text="Print verbose YANK logging output")

    @staticmethod
    def analyze_directory(source_directory):
        """
        This Function has been copied and adapted from the Yank ver 0.17.0 source code
        (yank.analyse.analyze_directory)

        Analyze contents of store files to compute free energy differences.

        This function is needed to preserve the old auto-analysis style of YANK. What it exactly does can be refined
        when more analyzers and simulations are made available. For now this function exposes the API.

        Parameters
        ----------
        source_directory : string
           The location of the simulation storage files.

        """
        analysis_script_path = os.path.join(source_directory, 'analysis.yaml')
        if not os.path.isfile(analysis_script_path):
            err_msg = 'Cannot find analysis.yaml script in {}'.format(source_directory)
            raise RuntimeError(err_msg)
        with open(analysis_script_path, 'r') as f:
            analysis = yaml.load(f)

        data = dict()
        for phase_name, sign in analysis:
            phase_path = os.path.join(source_directory, phase_name + '.nc')
            phase = get_analyzer(phase_path)
            data[phase_name] = phase.analyze_phase()
            kT = phase.kT

        # Compute free energy and enthalpy
        DeltaF = 0.0
        dDeltaF = 0.0
        DeltaH = 0.0
        dDeltaH = 0.0
        for phase_name, sign in analysis:
            DeltaF -= sign * (data[phase_name]['DeltaF'] + data[phase_name]['DeltaF_standard_state_correction'])
            dDeltaF += data[phase_name]['dDeltaF'] ** 2
            DeltaH -= sign * (data[phase_name]['DeltaH'] + data[phase_name]['DeltaF_standard_state_correction'])
            dDeltaH += data[phase_name]['dDeltaH'] ** 2
        dDeltaF = np.sqrt(dDeltaF)
        dDeltaH = np.sqrt(dDeltaH)

        DeltaF = DeltaF * kT / unit.kilocalories_per_mole
        dDeltaF = dDeltaF * kT / unit.kilocalories_per_mole
        DeltaH = DeltaH * kT / unit.kilocalories_per_mole
        dDeltaH = dDeltaH * kT / unit.kilocalories_per_mole

        return DeltaF, dDeltaF, DeltaH, dDeltaH

    def begin(self):
        self.opt = vars(self.args)
        self.opt['Logger'] = self.log

    def process(self, solvated_system, port):

        try:
            # The copy of the dictionary option as local variable
            # is necessary to avoid filename collisions due to
            # the parallel cube processes
            opt = dict(self.opt)

            # Split the complex in components
            protein, solute, water, excipients = oeommutils.split(solvated_system, ligand_res_name='LIG')

            # Update cube simulation parameters with the eventually molecule SD tags
            new_args = {dp.GetTag(): dp.GetValue() for dp in oechem.OEGetSDDataPairs(solute) if dp.GetTag() in
                        ["temperature", "pressure"]}

            if new_args:
                for k in new_args:
                    try:
                        new_args[k] = float(new_args[k])
                    except:
                        pass
                self.log.info("Updating parameters for molecule: {}\n{}".format(solute.GetTitle(), new_args))
                opt.update(new_args)

            # Extract the MD data
            mdData = data_utils.MDData(solvated_system)
            solvated_structure = mdData.structure

            # Extract the ligand parmed structure
            solute_structure = solvated_structure.split()[0][0]
            solute_structure.box = None

            # Set the ligand title
            solute.SetTitle(solvated_system.GetTitle())

            # Create the solvated and vacuum system
            solvated_omm_sys = solvated_structure.createSystem(nonbondedMethod=app.PME,
                                                               nonbondedCutoff=opt['nonbondedCutoff'] * unit.angstroms,
                                                               constraints=app.HBonds,
                                                               removeCMMotion=False)

            solute_omm_sys = solute_structure.createSystem(nonbondedMethod=app.NoCutoff,
                                                           constraints=app.HBonds,
                                                           removeCMMotion=False)

            # This is a note from:
            # https://github.com/MobleyLab/SMIRNOFF_paper_code/blob/e5012c8fdc4570ca0ec750f7ab81dd7102e813b9/scripts/create_input_files.py#L114
            # Fix switching function.
            for force in solvated_omm_sys.getForces():
                if isinstance(force, openmm.NonbondedForce):
                    force.setUseSwitchingFunction(True)
                    force.setSwitchingDistance((opt['nonbondedCutoff'] - 1.0) * unit.angstrom)

            # Write out all the required files and set-run the Yank experiment
            with TemporaryDirectory() as output_directory:

                opt['Logger'].info("Output Directory {}".format(output_directory))

                solvated_structure_fn = os.path.join(output_directory, "solvated.pdb")
                solvated_structure.save(solvated_structure_fn, overwrite=True)

                solute_structure_fn = os.path.join(output_directory, "solute.pdb")
                solute_structure.save(solute_structure_fn, overwrite=True)

                solvated_omm_sys_serialized = XmlSerializer.serialize(solvated_omm_sys)
                solvated_omm_sys_serialized_fn = os.path.join(output_directory, "solvated.xml")
                solvated_f = open(solvated_omm_sys_serialized_fn, 'w')
                solvated_f.write(solvated_omm_sys_serialized)
                solvated_f.close()

                solute_omm_sys_serialized = XmlSerializer.serialize(solute_omm_sys)
                solute_omm_sys_serialized_fn = os.path.join(output_directory, "solute.xml")
                solute_f = open(solute_omm_sys_serialized_fn, 'w')
                solute_f.write(solute_omm_sys_serialized)
                solute_f.close()

                # Build the Yank Experiment
                yaml_builder = ExperimentBuilder(yank_solvation_template.format(
                                                 verbose='yes' if opt['verbose'] else 'no',
                                                 minimize='yes' if opt['minimize'] else 'no',
                                                 output_directory=output_directory,
                                                 timestep=opt['timestep'],
                                                 nsteps_per_iteration=opt['nsteps_per_iteration'],
                                                 number_iterations=opt['iterations'],
                                                 temperature=opt['temperature'],
                                                 pressure=opt['pressure'],
                                                 solvated_pdb_fn=solvated_structure_fn,
                                                 solvated_xml_fn=solvated_omm_sys_serialized_fn,
                                                 solute_pdb_fn=solute_structure_fn,
                                                 solute_xml_fn=solute_omm_sys_serialized_fn))

                # Run Yank
                yaml_builder.run_experiments()

                exp_dir = os.path.join(output_directory, "experiments")

                # Calculate solvation free energy, solvation Enthalpy and their errors
                DeltaG_solvation, dDeltaG_solvation, DeltaH, dDeltaH = self.__class__.analyze_directory(exp_dir)

                # # Add result to the original molecule in kcal/mol
                oechem.OESetSDData(solute, 'DG_yank_solv', str(DeltaG_solvation))
                oechem.OESetSDData(solute, 'dG_yank_solv', str(dDeltaG_solvation))

            # Emit the ligand
            self.success.emit(solute)

        except Exception as e:
            # Attach an error message to the molecule that failed
            self.log.error(traceback.format_exc())
            solvated_system.SetData('error', str(e))
            # Return failed mol
            self.failure.emit(solvated_system)

        return
