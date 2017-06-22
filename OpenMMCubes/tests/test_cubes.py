import unittest
import pytest
from floe.test import CubeTestRunner
from openeye import oechem
import OpenMMCubes.utils as utils
from OpenMMCubes.cubes import OpenMMminimizeCube, OpenMMnvtCube, OpenMMnptCube
from simtk import unit, openmm
from simtk.openmm import app

# class SetupCubeTester(unittest.TestCase):
#     """
#     Test the OpenMM complex setup cube
#     Example inputs from `openmm_orion/examples/data`
#     """
#     def setUp(self):
#         self.cube = OpenMMComplexSetup("complex_setup")
#         self.cube.args.protein = utils.get_data_filename('examples', 'data/epox_hydrolase_apo-protein.pdb')
#         self.cube.args.solvent_padding = 1
#         self.cube.args.salt_concentration = 10
#         self.runner = CubeTestRunner(self.cube)
#         self.runner.start()
#
#     def test_success(self):
#         print('Testing cube:', self.cube.name)
#         # Read a molecule
#         mol = oechem.OEMol()
#         ifs = oechem.oemolistream(utils.get_data_filename('examples', 'data/TOL-smnf.oeb.gz'))
#         if not oechem.OEReadMolecule(ifs, mol):
#             raise Exception('Cannot read molecule')
#         ifs.close()
#
#         # Process the molecules
#         self.cube.process(mol, self.cube.intake.name)
#         # Assert that one molecule was emitted on the success port
#         self.assertEqual(self.runner.outputs['success'].qsize(), 1)
#         # Assert that zero molecules were emitted on the failure port
#         self.assertEqual(self.runner.outputs['failure'].qsize(), 0)
#
#         # Check for ParmEd Structure
#         outmol = self.runner.outputs["success"].get()
#         self.assertTrue(outmol.HasData(oechem.OEGetTag('Structure')))
#         # Check structure is for protein:ligand complex, not molecule
#         gd = utils.PackageOEMol.unpack(mol)
#         self.assertGreater(len(gd['Structure'].atoms), mol.NumAtoms())
#
#     def test_failure(self):
#         pass
#
#     def tearDown(self):
#         self.runner.finalize()


# class SimulationCubeTester(unittest.TestCase):
#     """
#     Test the OpenMM Simulation cube
#     Example inputs from `openmm_orion/examples/data`
#     """
#     def setUp(self):
#         self.cube = OpenMMSimulation("md")
#         self.runner = CubeTestRunner(self.cube)
#         self.cube.args.steps = 3
#         self.cube.args.reporter_interval = 1
#         self.cube.args.tarxz = False
#         self.runner = CubeTestRunner(self.cube)
#         self.runner.start()
#
#     def tearDown(self):
#         self.runner.finalize()
#
#     def test_success(self):
#         print('Testing cube:', self.cube.name)
#         mol = oechem.OEMol()
#         fname = get_data_filename('examples','data/TOL-complex.oeb.gz')
#         ifs = oechem.oemolistream(fname)
#         if not oechem.OEReadMolecule(ifs, mol):
#             raise Exception('Cannot read complex from %s' % fname)
#         ifs.close()
#
#         # Process the molecules
#         self.cube.process(mol, self.cube.intake.name)
#         # Assert that one molecule was emitted on the success port
#         self.assertEqual(self.runner.outputs['success'].qsize(), 1)
#         # Assert that zero molecules were emitted on the failure port
#         self.assertEqual(self.runner.outputs['failure'].qsize(), 0)
#
#         outmol = self.runner.outputs["success"].get()
#         self.assertTrue(outmol.HasData(oechem.OEGetTag('Structure')))
#         self.assertTrue(outmol.HasData(oechem.OEGetTag('State')))
#         self.assertTrue(outmol.HasData(oechem.OEGetTag('Log')))
#
#     def test_failure(self):
#         pass

class MinimizationCubeTester(unittest.TestCase):
    """
    Test the OpenMM Minimization cube
    Example inputs from `openmm_orion/examples/data`
    """

    def calculate_eng(self, oe_mol):
        # Extract starting MD data from OEMol
        mdData = utils.MDData(oe_mol)
        topology = mdData.topology
        positions = mdData.positions
        structure = mdData.structure
        box = mdData.box

        # OpenMM system
        system = structure.createSystem(nonbondedMethod=eval("app.%s" % self.cube.args.nonbondedMethod),
                                        nonbondedCutoff=self.cube.args.nonbondedCutoff * unit.angstroms,
                                        constraints=eval("app.%s" % self.cube.args.constraints))
        # OpenMM Integrator
        integrator = openmm.LangevinIntegrator(self.cube.args.temperature * unit.kelvin,
                                               1.0 / unit.picoseconds, 0.002 * unit.picoseconds)
        # Set Simulation
        simulation = app.Simulation(topology, system, integrator)

        # Set Positions
        simulation.context.setPositions(positions)

        # Set Box dimensions
        simulation.context.setPeriodicBoxVectors(box[0], box[1], box[2])

        # Collect the OpenMM state energy info
        state = simulation.context.getState(getEnergy=True)

        # Potential Energy
        peng = state.getPotentialEnergy()

        return peng

    def setUp(self):
        self.cube = OpenMMminimizeCube('minComplex')
        self.runner = CubeTestRunner(self.cube)
        self.runner.start()

    def _test_success(self):
        print('Testing cube:', self.cube.name)
        # File name of a charged ligand
        lig_fname = utils.get_data_filename('examples', 'data/pbase_lcat13a_complex.oeb.gz')

        # Read OEMol molecule
        mol = oechem.OEMol()

        with oechem.oemolistream(lig_fname) as ifs:
          oechem.OEReadMolecule(ifs, mol)

        # Calculate starting potential energy
        eng_i = self.calculate_eng(mol)

        # Process the molecules
        self.cube.process(mol, self.cube.intake.name)
        # Assert that one molecule was emitted on the success port
        self.assertEqual(self.runner.outputs['success'].qsize(), 1)
        # Assert that zero molecules were emitted on the failure port
        self.assertEqual(self.runner.outputs['failure'].qsize(), 0)

        outmol = self.runner.outputs["success"].get()
        # Calculate final potential energy
        eng_f = self.calculate_eng(outmol)

        self.assertLess(eng_f, eng_i)

    @pytest.mark.slow
    def test_success(self):
        self.cube.args.steps = 100000
        self._test_success()

    def test_failure(self):
        pass

    def tearDown(self):
        self.runner.finalize()


class NVTCubeTester(unittest.TestCase):
    """
    Test the OpenMM NVT cube
    Example inputs from `openmm_orion/examples/data`
    """

    def calculate_VT(self, oe_mol):
        # Extract starting MD data from OEMol
        mdData = utils.MDData(oe_mol)
        structure = mdData.structure
        topology = mdData.topology
        positions = mdData.positions
        velocities = mdData.velocities
        box = mdData.box

        volume = box[0][0] * box[1][1] * box[2][2]

        # OpenMM system
        system = structure.createSystem(nonbondedMethod=eval("app.%s" % self.cube.args.nonbondedMethod),
                                        nonbondedCutoff=self.cube.args.nonbondedCutoff * unit.angstroms,
                                        constraints=eval("app.%s" % self.cube.args.constraints))
        # OpenMM Integrator
        integrator = openmm.LangevinIntegrator(self.cube.args.temperature * unit.kelvin,
                                               1.0 / unit.picoseconds, 0.002 * unit.picoseconds)
        # Set Simulation
        simulation = app.Simulation(topology, system, integrator)

        # Set Positions
        simulation.context.setPositions(positions)
        # Set Velocities
        simulation.context.setVelocities(velocities)

        # Set Box dimensions
        simulation.context.setPeriodicBoxVectors(box[0], box[1], box[2])

        # Collect the OpenMM state energy info
        state = simulation.context.getState(getEnergy=True)

        # Kinetic Energy
        keng = state.getKineticEnergy()

        # Calculate system degrees of freedom:
        dof = 0
        for i in range(system.getNumParticles()):
            if system.getParticleMass(i) > 0 * unit.dalton:
                dof += 3

        dof -= system.getNumConstraints()

        if any(type(system.getForce(i)) == openmm.CMMotionRemover for i in range(system.getNumForces())):
            dof -= 3

        # Calculate the temperature from the equipartition theorem
        temperature = ((2*keng)/(dof*unit.MOLAR_GAS_CONSTANT_R))

        return volume, temperature

    def setUp(self):
        self.cube = OpenMMnvtCube('NVT')
        self.runner = CubeTestRunner(self.cube)
        self.runner.start()

    def _test_success(self):
        print('Testing cube:', self.cube.name)
        # File name of a charged ligand
        lig_fname = utils.get_data_filename('examples', 'data/pP38_lp38a_2x_complex.oeb.gz')

        # Read OEMol molecule
        mol = oechem.OEMol()

        with oechem.oemolistream(lig_fname) as ifs:
            oechem.OEReadMolecule(ifs, mol)

        # Process the molecules
        self.cube.process(mol, self.cube.intake.name)
        # Assert that one molecule was emitted on the success port
        self.assertEqual(self.runner.outputs['success'].qsize(), 1)
        # Assert that zero molecules were emitted on the failure port
        self.assertEqual(self.runner.outputs['failure'].qsize(), 0)

        outmol = self.runner.outputs["success"].get()

        # Calculate final volume and temperature
        vol_f, temp_f = self.calculate_VT(outmol)

        # Check 3*std volume
        # Average volume and its standard deviation (in nm^3) measured along
        # one 10ns run for the selected system
        avg_volume = 683.685643 * (unit.nanometers ** 3)
        std_volume = 0.000001

        self.assertAlmostEqual(avg_volume/(unit.nanometers ** 3),
                               vol_f.in_units_of(unit.nanometers ** 3) / (unit.nanometers ** 3),
                               delta=3*std_volume)

        # Check temperature
        # Average temperature and its standard deviation (in K) measured along
        # one 10ns run for the selected system
        avg_temperature = 300.0 * unit.kelvin
        std_temperature = 0.9
        self.assertAlmostEqual(avg_temperature/unit.kelvin,
                               temp_f.in_units_of(unit.kelvin)/unit.kelvin,
                               delta=3*std_temperature)

    @pytest.mark.slow
    def test_success(self):
        self.cube.args.time = 50  # in picoseconds
        self._test_success()

    def test_failure(self):
        pass

    def tearDown(self):
        self.runner.finalize()


class NPTCubeTester(unittest.TestCase):
    """
    Test the OpenMM NPT cube
    Example inputs from `openmm_orion/examples/data`
    """
    def calculate_VT(self, oe_mol):
        # Extract starting MD data from OEMol
        mdData = utils.MDData(oe_mol)
        structure = mdData.structure
        topology = mdData.topology
        positions = mdData.positions
        velocities = mdData.velocities
        box = mdData.box

        volume = box[0][0] * box[1][1] * box[2][2]

        # OpenMM system
        system = structure.createSystem(nonbondedMethod=eval("app.%s" % self.cube.args.nonbondedMethod),
                                        nonbondedCutoff=self.cube.args.nonbondedCutoff * unit.angstroms,
                                        constraints=eval("app.%s" % self.cube.args.constraints))
        # OpenMM Integrator
        integrator = openmm.LangevinIntegrator(self.cube.args.temperature * unit.kelvin,
                                               1.0 / unit.picoseconds, 0.002 * unit.picoseconds)

        # Add Force Barostat to the system
        system.addForce(openmm.MonteCarloBarostat(self.cube.args.pressure * unit.atmospheres,
                                                  self.cube.args.temperature*unit.kelvin, 25))

        # Set Simulation
        simulation = app.Simulation(topology, system, integrator)

        # Set Positions
        simulation.context.setPositions(positions)

        # Set Velocities
        simulation.context.setVelocities(velocities)

        # Set Box dimensions
        simulation.context.setPeriodicBoxVectors(box[0], box[1], box[2])

        # Collect the OpenMM state energy info
        state = simulation.context.getState(getEnergy=True)

        # Kinetic Energy
        keng = state.getKineticEnergy()

        # Calculate system degrees of freedom:
        dof = 0
        for i in range(system.getNumParticles()):
            if system.getParticleMass(i) > 0 * unit.dalton:
                dof += 3

        dof -= system.getNumConstraints()

        if any(type(system.getForce(i)) == openmm.CMMotionRemover for i in range(system.getNumForces())):
            dof -= 3

        # Calculate the temperature from the equipartition theorem
        temperature = ((2*keng)/(dof*unit.MOLAR_GAS_CONSTANT_R))

        return volume, temperature

    def setUp(self):
        self.cube = OpenMMnptCube('NPT')
        self.runner = CubeTestRunner(self.cube)
        self.runner.start()

    def _test_success(self):
        print('Testing cube:', self.cube.name)
        # File name of a charged ligand
        lig_fname = utils.get_data_filename('examples', 'data/pP38_lp38a_2x_complex.oeb.gz')

        # Read OEMol molecule
        mol = oechem.OEMol()

        with oechem.oemolistream(lig_fname) as ifs:
            oechem.OEReadMolecule(ifs, mol)

        # Process the molecules
        self.cube.process(mol, self.cube.intake.name)
        # Assert that one molecule was emitted on the success port
        self.assertEqual(self.runner.outputs['success'].qsize(), 1)
        # Assert that zero molecules were emitted on the failure port
        self.assertEqual(self.runner.outputs['failure'].qsize(), 0)

        outmol = self.runner.outputs["success"].get()

        # Calculate final volume and temperature
        vol_f, temp_f = self.calculate_VT(outmol)

        # Check 3*std volume
        # Average volume and its standard deviation (in nm^3) measured along
        # one 10ns run for the selected system
        avg_volume = 683.0 * (unit.nanometers**3)
        std_volume = 1.0

        self.assertAlmostEqual(avg_volume/(unit.nanometers**3),
                               vol_f.in_units_of(unit.nanometers**3)/(unit.nanometers**3),
                               delta=3*std_volume)

        # Check 3*std temperature
        # Average temperature and its standard deviation (in K) measured along
        # one 10ns run for the selected system
        avg_temperature = 300.0 * unit.kelvin
        std_temperature = 1.0

        self.assertAlmostEqual(avg_temperature/unit.kelvin,
                               temp_f.in_units_of(unit.kelvin)/unit.kelvin,
                               delta=3*std_temperature)

    @pytest.mark.slow
    def test_success(self):
        self.cube.args.time = 50  # in picoseconds
        self._test_success()

    def test_failure(self):
        pass

    def tearDown(self):
        self.runner.finalize()

if __name__ == "__main__":
        unittest.main()