from __future__ import unicode_literals
from floe.api import WorkFloe, OEMolOStreamCube
from ComplexPrepCubes.cubes import HydrationCube, ComplexPrep, ForceFieldPrep, SolvationCube
from ComplexPrepCubes.port import ProteinReader
from OpenMMCubes.cubes import OpenMMminimizeCube
from LigPrepCubes.cubes import LigChargeCube
from LigPrepCubes.ports import LigandReader

from ComplexPrepCubes.cubes import SolvationCube

job = WorkFloe("Complex Preparation and Minimization")

job.description = """
Complex Preparation and Minimization Workflow

Ex. python floes/openmm_complex_prep.py --protein protein.oeb
--ligands ligands.oeb  --ofs-data_out min.oeb

Parameters:
-----------
protein (file): OEB file of the prepared protein
ligands (file): OEB file of the prepared ligands


Outputs:
--------
ofs: Output file of the assembled and minimized complex
"""

job.classification = [['Simulation']]
job.tags = [tag for lists in job.classification for tag in lists]

# Ligand setting
iligs = LigandReader("LigandReader", title="Ligand Reader")
iligs.promote_parameter("data_in", promoted_name="ligands", title="Ligand Input File", description="Ligand file name")

chargelig = LigChargeCube("LigCharge")
chargelig.promote_parameter('max_conformers', promoted_name='max_conformers',
                            description="Set the max number of conformers per ligand", default=800)

# Protein Setting
iprot = ProteinReader("ProteinReader")
iprot.promote_parameter("data_in", promoted_name="protein", title="Protein Input File", description="Protein file name")
iprot.promote_parameter("protein_prefix", promoted_name="protein_prefix", default='PRT',
                        description="Protein Prefix")

# Complex Setting
complx = ComplexPrep("Complex")

# Solvate the system
# solvate = HydrationCube("Hydration")

solvate = SolvationCube("Hydration")
solvate.promote_parameter('density', promoted_name='density', default=1.0,
                          description="Solution density in g/ml")
solvate.promote_parameter('close_solvent', promoted_name='close_solvent', default=True,
                          description='The solvent molecules will be placed very close to the solute')
solvate.promote_parameter('salt_concentration', promoted_name='salt_concentration', default=50.0,
                          description='Salt concentration (Na+, Cl-) in millimolar')

# Force Field application
ff = ForceFieldPrep("ForceField")

# Minimization
minComplex = OpenMMminimizeCube('minComplex')
minComplex.promote_parameter('steps', promoted_name='steps', default=0)
minComplex.promote_parameter('center', promoted_name='center', default=True)

ofs = OEMolOStreamCube('ofs', title='OFS-Success')
ofs.set_parameters(backend='s3')

fail = OEMolOStreamCube('fail', title='OFS-Failure')
fail.set_parameters(backend='s3')
fail.set_parameters(data_out='fail.oeb.gz')

job.add_cubes(iprot, iligs, chargelig, complx,  solvate, ff, minComplex, ofs, fail)

iprot.success.connect(complx.system_port)
iligs.success.connect(chargelig.intake)
chargelig.success.connect(complx.intake)
complx.success.connect(solvate.intake)
solvate.success.connect(ff.intake)
ff.success.connect(minComplex.intake)
minComplex.success.connect(ofs.intake)
minComplex.failure.connect(fail.intake)


if __name__ == "__main__":
    job.run()
