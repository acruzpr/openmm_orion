from __future__ import unicode_literals
from floe.api import WorkFloe
from cuberecord import DataSetWriterCube

from MDCubes.OpenMMCubes.cubes import (OpenMMminimizeCube,
                                       OpenMMNvtCube,
                                       OpenMMNptCube)

from ComplexPrepCubes.cubes import (HydrationCube,
                                    ComplexPrepCube,
                                    SolvationCube)

from ForceFieldCubes.cubes import ForceFieldCube

from ProtPrepCubes.ports import ProteinReaderCube

from LigPrepCubes.ports import LigandReaderCube
from LigPrepCubes.cubes import LigandChargeCube


job = WorkFloe('Merk Frosst MD Protocol Longer Equilibration')

job.description = """
Set up an OpenMM complex then minimize, warm up and equilibrate a system by using three equilibration stages

Ex: python floes/openmm_MDprep.py --ligands ligands.oeb --protein protein.oeb --ofs-data_out prep.oeb

Parameters:
-----------
ligands (file): oeb file of ligand posed in the protein active site.
protein (file): oeb file of the protein structure, assumed to be pre-prepared

Optionals:
-----------

Outputs:
--------
ofs: Outputs a ready system to MD production run
"""

job.classification = [['Complex Setup', 'FrosstMD']]
job.tags = [tag for lists in job.classification for tag in lists]

# Ligand setting
iligs = LigandReaderCube("LigandReader", title="Ligand Reader")
iligs.promote_parameter("data_in", promoted_name="ligands", title="Ligand Input File", description="Ligand file name")


chargelig = LigandChargeCube("LigCharge")
chargelig.promote_parameter('max_conformers', promoted_name='max_conformers',
                            description="Set the max number of conformers per ligand", default=800)

# Protein Reading cube. The protein prefix parameter is used to select a name for the
# output system files
iprot = ProteinReaderCube("ProteinReader")
iprot.promote_parameter("data_in", promoted_name="protein", title='Protein Input File',
                        description="Protein file name")
iprot.promote_parameter("protein_prefix", promoted_name="protein_prefix",
                        default='PRT', description="Protein prefix")

# Complex cube used to assemble the ligands and the solvated protein
complx = ComplexPrepCube("Complex")

# The solvation cube is used to solvate the system and define the ionic strength of the solution
# solvate = HydrationCube("Hydration")

solvate = SolvationCube("Hydration")
solvate.promote_parameter('density', promoted_name='density', default=1.0,
                          description="Solution density in g/ml")
solvate.promote_parameter('close_solvent', promoted_name='close_solvent', default=True,
                          description='The solvent molecules will be placed very close to the solute')
solvate.promote_parameter('salt_concentration', promoted_name='salt_concentration', default=50.0,
                          description='Salt concentration (Na+, Cl-) in millimolar')

# Force Field Application
ff = ForceFieldCube("ForceField")
ff.promote_parameter('protein_forcefield', promoted_name='protein_ff', default='amber99sbildn.xml')
ff.promote_parameter('solvent_forcefield', promoted_name='solvent_ff', default='tip3p.xml')
ff.promote_parameter('ligand_forcefield', promoted_name='ligand_ff', default='GAFF2')
ff.promote_parameter('other_forcefield', promoted_name='other_ff', default='GAFF2')

# Minimization
minComplex = OpenMMminimizeCube('minComplex', title='Minimize')
minComplex.promote_parameter('restraints', promoted_name='m_restraints', default="noh (ligand or protein)",
                             description='Select mask to apply restarints')
minComplex.promote_parameter('restraintWt', promoted_name='m_restraintWt', default=5.0,
                             description='Restraint weight')
minComplex.promote_parameter('steps', promoted_name='steps', default=0)
minComplex.promote_parameter('center', promoted_name='center', default=True)

# NVT simulation. Here the assembled system is warmed up to the final selected temperature
warmup = OpenMMNvtCube('warmup', title='warmup')
warmup.promote_parameter('time', promoted_name='warm_psec', default=100.0,
                         description='Length of MD run in picoseconds')
warmup.promote_parameter('restraints', promoted_name='w_restraints', default="noh (ligand or protein)",
                         description='Select mask to apply restarints')
warmup.promote_parameter('restraintWt', promoted_name='w_restraintWt', default=2.0, description='Restraint weight')
warmup.promote_parameter('trajectory_interval', promoted_name='w_trajectory_interval', default=0.0,
                         description='Trajectory saving interval in ps')
warmup.promote_parameter('reporter_interval', promoted_name='w_reporter_interval', default=0.0,
                         description='Reporter saving interval in ps')
warmup.promote_parameter('outfname', promoted_name='w_outfname', default='warmup',
                         description='Equilibration suffix name')

# The system is equilibrated at the right pressure and temperature in 3 stages
# The main difference between the stages is related to the restraint force used
# to keep the ligand and protein in their starting positions. A relatively strong force
# is applied in the first stage while a relatively small one is applied in the latter

# NPT Equilibration stage 1
equil1 = OpenMMNptCube('equil1', title='equil1')
equil1.promote_parameter('time', promoted_name='eq1_psec', default=100.0,
                         description='Length of MD run in picoseconds')
equil1.promote_parameter('restraints', promoted_name='eq1_restraints', default="noh (ligand or protein)",
                         description='Select mask to apply restarints')
equil1.promote_parameter('restraintWt', promoted_name='eq1_restraintWt', default=2.0, description='Restraint weight')
equil1.promote_parameter('trajectory_interval', promoted_name='eq1_trajectory_interval', default=0.0,
                         description='Trajectory saving interval in ps')
equil1.promote_parameter('reporter_interval', promoted_name='eq1_reporter_interval', default=0.0,
                         description='Reporter saving interval in ps')
equil1.promote_parameter('outfname', promoted_name='eq1_outfname', default='equil1',
                         description='Equilibration suffix name')

# NPT Equilibration stage 2
equil2 = OpenMMNptCube('equil2', title='equil2')
equil2.promote_parameter('time', promoted_name='eq2_psec', default=100.0,
                         description='Length of MD run in picoseconds')
equil2.promote_parameter('restraints', promoted_name='eq2_restraints', default="noh (ligand or protein)",
                         description='Select mask to apply restarints')
equil2.promote_parameter('restraintWt', promoted_name='eq2_restraintWt', default=0.5,
                         description='Restraint weight')
equil2.promote_parameter('trajectory_interval', promoted_name='eq2_trajectory_interval', default=0.0,
                         description='Trajectory saving interval in ps')
equil2.promote_parameter('reporter_interval', promoted_name='eq2_reporter_interval', default=0.0,
                         description='Reporter saving interval in ps')
equil2.promote_parameter('outfname', promoted_name='eq2_outfname', default='equil2',
                         description='Equilibration suffix name')

# NPT Equilibration stage 3
equil3 = OpenMMNptCube('equil3', title='equil3')
equil3.promote_parameter('time', promoted_name='eq3_psec', default=200.0,
                         description='Length of MD run in picoseconds')
equil3.promote_parameter('restraints', promoted_name='eq3_restraints', default="ca_protein or (noh ligand)",
                         description='Select mask to apply restarints')
equil3.promote_parameter('restraintWt', promoted_name='eq3_restraintWt', default=0.1,
                         description='Restraint weight')
equil3.promote_parameter('trajectory_interval', promoted_name='eq3_trajectory_interval', default=0.0,
                         description='Trajectory saving interval in ps')
equil3.promote_parameter('reporter_interval', promoted_name='eq3_reporter_interval', default=0.0,
                         description='Reporter saving interval in ps')
equil3.promote_parameter('outfname', promoted_name='eq3_outfname', default='equil3',
                         description='Equilibration suffix name')

prod = OpenMMNptCube("Production")
prod.promote_parameter('time', promoted_name='prod_psec', default=2000.0,
                       description='Length of MD run in picoseconds')

prod.promote_parameter('trajectory_interval', promoted_name='prod_trajectory_interval', default=1.0,
                       description='Trajectory saving interval in ps')
prod.promote_parameter('reporter_interval', promoted_name='prod_reporter_interval', default=1.0,
                       description='Reporter saving interval in ps')
prod.promote_parameter('outfname', promoted_name='prod_outfname', default='prod',
                       description='Equilibration suffix name')

ofs = DataSetWriterCube('ofs', title='OFS-Success')


fail = DataSetWriterCube('fail', title='OFS-Failure')
fail.set_parameters(data_out='fail.oeb.gz')

job.add_cubes(iprot, iligs, chargelig, complx, solvate, ff,
              minComplex, warmup, equil1, equil2, equil3, prod, ofs, fail)

iprot.success.connect(complx.protein_port)
iligs.success.connect(chargelig.intake)
chargelig.success.connect(complx.intake)
complx.success.connect(solvate.intake)
solvate.success.connect(ff.intake)
ff.success.connect(minComplex.intake)
minComplex.success.connect(warmup.intake)
warmup.success.connect(equil1.intake)
equil1.success.connect(equil2.intake)
equil2.success.connect(equil3.intake)
equil3.success.connect(prod.intake)
prod.success.connect(ofs.intake)
prod.failure.connect(fail.intake)

if __name__ == "__main__":
    job.run()
