from __future__ import unicode_literals
from floe.api import WorkFloe, OEMolOStreamCube
from ComplexPrepCubes.cubes import HydrationCube, ComplexPrep, ForceFieldPrep
from ComplexPrepCubes.port import ProteinReader
from LigPrepCubes.ports import LigandReader
from LigPrepCubes.cubes import LigChargeCube

job = WorkFloe("Complex Preparation")

job.description = """
Complex Preparation Workflow

Ex. python floes/openmm_complex_prep.py --protein protein.oeb
--ligands ligands.oeb  --ofs-data_out complex.oeb

Parameters:
-----------
protein (file): OEB file of the prepared protein
ligands (file): OEB file of the prepared ligands


Outputs:
--------
ofs: Output file
"""

job.classification = [['Simulation']]
job.tags = [tag for lists in job.classification for tag in lists]

# Ligand setting
iligs = LigandReader("Ligand Reader", title="Ligand Reader")
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
ff = ForceFieldPrep("ForceField")

# solvate the system
solvate = HydrationCube("Hydration")

ofs = OEMolOStreamCube('ofs', title='OFS-Success')
ofs.set_parameters(backend='s3')

fail = OEMolOStreamCube('fail', title='OFS-Failure')
fail.set_parameters(backend='s3')
fail.set_parameters(data_out='fail.oeb.gz')

job.add_cubes(iprot, iligs, chargelig, complx,  solvate, ff, ofs, fail)

iprot.success.connect(complx.system_port)
iligs.success.connect(chargelig.intake)
chargelig.success.connect(complx.intake)
complx.success.connect(solvate.intake)
solvate.success.connect(ff.intake)
ff.success.connect(ofs.intake)
ff.failure.connect(fail.intake)

if __name__ == "__main__":
    job.run()
