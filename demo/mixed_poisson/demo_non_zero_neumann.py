## Copyright 2019-2020, Jack S. Hale, Raphaël Bulle
## SPDX-License-Identifier: LGPL-3.0-or-later
import numpy as np
import pandas as pd

from dolfin import *
import ufl

import fenics_error_estimation

parameters['ghost_mode'] = 'shared_facet'

k = 1
def main():
    mesh = UnitSquareMesh(5,5)
    class BoundaryN(SubDomain):
        def inside(self, x, on_boundary):
            return on_boundary and (near(x[1], 0., DOLFIN_EPS) or near(x[1], 1., DOLFIN_EPS))

    class BoundaryD(SubDomain):
        def inside(self, x, on_boundary):
            return on_boundary and (near(x[0], 0., DOLFIN_EPS) or near(x[0], 1., DOLFIN_EPS))

    boundaryD = BoundaryD()
    boundaryN = BoundaryN()

    results = []
    for i in range(0, 16):
        boundary_marker = MeshFunction("size_t", mesh, 1)
        boundary_marker.set_all(0)
        boundaryN.mark(boundary_marker, 1)

        dN = Measure('ds', domain=mesh, subdomain_data=boundary_marker)

        V = FunctionSpace(mesh, 'CG', 1)
        result = {}
        
        f, g = pbm_data(mesh)
        V = FunctionSpace(mesh, "CG", k)
        u_h = solve(V, f, g, boundaryD, dN)
        with XDMFFile("output/u_h_{}.xdmf".format(str(i).zfill(4))) as xdmf:
            xdmf.write(u_h)

        eta_bw = bw_estimate(u_h, f, g, boundaryD, dN)
        with XDMFFile("output/eta_bw_{}.xdmf".format(str(i).zfill(4))) as xdmf:
            xdmf.write_checkpoint(eta_bw, "eta_bw")

        result["error_bw"] = np.sqrt(eta_bw.vector().sum())

        result["hmin"] = mesh.hmin()
        result["hmax"] = mesh.hmax()
        result["num_dofs"] = V.dim()

        markers = fenics_error_estimation.dorfler(eta_bw, 0.5)
        mesh = refine(mesh, markers, redistribute=True)

        with XDMFFile("output/mesh_{}.xdmf".format(str(i).zfill(4))) as xdmf:
            xdmf.write(mesh)

        results.append(result)

    if (MPI.comm_world.rank == 0):
        df = pd.DataFrame(results)
        df.to_pickle("output/results.pkl")
        print(df)

def solve(V, f, g, boundaryD, dN):
    u = TrialFunction(V)
    v = TestFunction(V)

    a = inner(grad(u), grad(v))*dx
    L = inner(f, v)*dx + inner(g, v)*dN(1)

    bcs = DirichletBC(V, Constant(0.) , boundaryD)

    A, b = assemble_system(a, L, bcs=bcs)

    u_h = Function(V, name='u_h')
    solver = PETScLUSolver('mumps')
    solver.solve(A, u_h.vector(), b)

    return u_h

def bw_estimate(u_h, f, g, boundaryD, dN, df=k+1, dg=k, verf=False, dof_list=None):
    mesh = u_h.function_space().mesh()

    element_f = FiniteElement("DG", triangle, df)
    element_g = FiniteElement("DG", triangle, dg)

    N = fenics_error_estimation.create_interpolation(element_f, element_g, dof_list)

    V_f = FunctionSpace(mesh, element_f)

    e = TrialFunction(V_f)
    v = TestFunction(V_f)

    bcs = DirichletBC(V_f, Constant(0.0), boundaryD, "geometric")

    n = FacetNormal(mesh)
    a_e = inner(grad(e), grad(v))*dx
    L_e = inner(f + div(grad(u_h)), v)*dx + \
        inner(jump(grad(u_h), -n), avg(v))*dS + \
        inner(g - inner(grad(u_h), n), v)*dN(1)

    e_h = fenics_error_estimation.estimate(a_e, L_e, N, bcs)
    error = norm(e_h, "H10")

    # Computation of local error indicator
    V_e = FunctionSpace(mesh, "DG", 0)
    v = TestFunction(V_e)

    eta_h = Function(V_e, name="eta_h")
    eta = assemble(inner(inner(grad(e_h), grad(e_h)), v)*dx)
    eta_h.vector()[:] = eta
    return eta_h


def pbm_data(mesh):
    # Exact solution
    x = ufl.SpatialCoordinate(mesh)

    # Data
    f = 10.*ufl.exp(-((x[0]-0.5)**2 + (x[1]-0.5)**2)/0.02)
    g = ufl.sin(5.*x[0])
    return f, g


if __name__ == "__main__":
    main()
