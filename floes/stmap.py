from __future__ import unicode_literals
from floe.api import WorkFloe
from cuberecord import DataSetWriterCube, DataSetReaderCube
from TrjAnalysis.cubes import SSTMapSetCube

job = WorkFloe("Testing SSTMAP")

job.description = """
Testing Floe

Ex. python floes/up.py --ligands ligands.oeb
--ofs-data_out prep.oeb

Parameters:
-----------
ligands (file): OEB file of the prepared ligands

Outputs:
--------
ofs: Output file
"""

ifs = DataSetReaderCube("ifs")

ifs.promote_parameter("data_in", promoted_name="system", title="System Input File", description="System file name")

scube = SSTMapSetCube("SSTMap")

scube.promote_parameter("trj_fn", promoted_name='trj', default='trj.nc')

ofs = DataSetWriterCube('ofs', title='OFS-Success')

job.add_cubes(ifs, scube, ofs)

ifs.success.connect(scube.intake)
scube.success.connect(ofs.intake)

if __name__ == "__main__":
    job.run()
