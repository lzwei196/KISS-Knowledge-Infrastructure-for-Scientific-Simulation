import os.path
from arch import archread
import numpy as np
import inspect
from verbose import verbose
from InterpFromMeshToMesh2d import InterpFromMeshToMesh2d
from paterson import paterson
from SetIceShelfBC import SetIceShelfBC

#Start defining model parameters here
#Geometry
hmin = 300.
hmax = 1000.
ymin = np.min(md.mesh.y)
ymax = np.max(md.mesh.y)
xmin = min(md.mesh.x)
xmax = max(md.mesh.x)
md.geometry.thickness = hmax + (hmin - hmax) * (md.mesh.y - ymin) / (ymax - ymin) + 0.1 * (hmin - hmax) * (md.mesh.x - xmin) / (xmax - xmin)
md.geometry.base = -md.materials.rho_ice / md.materials.rho_water * md.geometry.thickness
md.geometry.surface = md.geometry.base + md.geometry.thickness
md.geometry.bed = md.geometry.base - 10

#Initial velocity
x = np.array(archread('../Data/SquareShelfConstrained.arch', 'x'))
y = np.array(archread('../Data/SquareShelfConstrained.arch', 'y'))
vx = np.array(archread('../Data/SquareShelfConstrained.arch', 'vx'))
vy = np.array(archread('../Data/SquareShelfConstrained.arch', 'vy'))
index = np.array(archread('../Data/SquareShelfConstrained.arch', 'index').astype(int))

md.initialization.vx = InterpFromMeshToMesh2d(index, x, y, vx, md.mesh.x, md.mesh.y)
md.initialization.vy = InterpFromMeshToMesh2d(index, x, y, vy, md.mesh.x, md.mesh.y)
md.initialization.vz = np.zeros((md.mesh.numberofvertices))
md.initialization.pressure = np.zeros((md.mesh.numberofvertices))

#Materials
md.initialization.temperature = (273. - 20.) * np.ones((md.mesh.numberofvertices))
md.materials.rheology_B = paterson(md.initialization.temperature)
md.materials.rheology_n = 3. * np.ones((md.mesh.numberofelements))

#Surface mass balance and basal melting
md.smb.mass_balance = 10. * np.ones((md.mesh.numberofvertices))
md.basalforcings.groundedice_melting_rate = 5. * np.ones((md.mesh.numberofvertices))
md.basalforcings.floatingice_melting_rate = 5. * np.ones((md.mesh.numberofvertices))

#Friction
md.friction.coefficient = 20. * np.ones((md.mesh.numberofvertices))
md.friction.coefficient[np.nonzero(md.mask.ocean_levelset < 0.)[0]] = 0.
md.friction.p = np.ones((md.mesh.numberofelements))
md.friction.q = np.ones((md.mesh.numberofelements))

#Numerical parameters
md.masstransport.stabilization = 1
md.thermal.stabilization = 1
md.verbose = verbose(0)
md.settings.waitonlock = 30
md.stressbalance.restol = 0.05
md.stressbalance.reltol = 0.05
md.steadystate.reltol = 0.05
md.stressbalance.abstol = float('nan')
md.timestepping.time_step = 1.
md.timestepping.final_time = 3.

#Deal with boundary conditions:
md = SetIceShelfBC(md)

#Change name so that no tests have the same name
if len(inspect.stack()) > 2:
    md.miscellaneous.name = os.path.basename(inspect.stack()[2][1]).split('.')[0]
