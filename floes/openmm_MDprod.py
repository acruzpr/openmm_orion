from __future__ import unicode_literals
from floe.api import WorkFloe, OEMolIStreamCube, OEMolOStreamCube
from OpenMMCubes.cubes import OpenMMnptCube

job = WorkFloe("Production Run")

job.description = """
Run an unrestrained NPT simulation at 300K and 1atm
"""

job.classification = [['Simulation']]
job.tags = [tag for lists in job.classification for tag in lists]

ifs = OEMolIStreamCube("SystemReader", title="System Reader")
ifs.promote_parameter("data_in", promoted_name="system", title='System Input File',
                      description="System input file")

prod = OpenMMnptCube('production')

# Set simulation time
prod.promote_parameter('time', promoted_name='picosec', default=2000)

# Set the temperature in K
prod.promote_parameter('temperature', promoted_name='temperature', default=300.0,
                       description='Selected temperature in K')

# Set the pressure in atm
prod.promote_parameter('pressure', promoted_name='pressure', default=1.0,
                       description='Selected pressure in atm')

# Trajectory and logging info frequency intervals
prod.promote_parameter('trajectory_interval', promoted_name='trajectory_interval', default=0.5,
                       description='Trajectory saving interval in ps')
prod.promote_parameter('reporter_interval', promoted_name='reporter_interval', default=1.0,
                       description='Reporter saving interval in ps')

prod.promote_parameter('tar', promoted_name='tar', default=True,
                       description='Compress the output files')

prod.promote_parameter('outfname', promoted_name='suffix', default='prod',
                       description='Production suffix name')


ofs = OEMolOStreamCube('ofs', title='OFS-Success')
ofs.set_parameters(backend='s3')
fail = OEMolOStreamCube('fail', title='OFS-Failure')
fail.set_parameters(backend='s3')
fail.set_parameters(data_out='fail.oeb.gz')

job.add_cubes(ifs, prod, ofs, fail)
ifs.success.connect(prod.intake)
prod.success.connect(ofs.intake)
prod.failure.connect(fail.intake)


if __name__ == "__main__":
    job.run()
