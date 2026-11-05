// -*- mode: C++; tab-width: 4; indent-tabs-mode: nil; c-basic-offset: 4 -*-
// vi: set et ts=4 sw=4 sts=4:
//
// SPDX-FileCopyrightText: Copyright © DuMux Project contributors, see AUTHORS.md in root folder
// SPDX-License-Identifier: GPL-3.0-or-later
//
// ## The main file (`main.cc`)
// [[content]]
//
// ### Included header files
// [[details]] includes
// [[exclude]]
// Some generic includes.
#include <config.h>
#include <ctime>
#include <iostream>
// [[/exclude]]

// These time measurements and parallel backend initialization
#include <dune/common/timer.hh>
#include <dumux/common/initialize.hh>

// The following headers include functionality related to property definition or retrieval, as well as
// the retrieval of input parameters specified in the input file or via the command line.
#include <dumux/common/properties.hh>
#include <dumux/common/parameters.hh>

// The following files contains the available linear solver backends and the assembler for the linear
// systems arising from finite volume discretizations (box-scheme, tpfa-approximation, mpfa-approximation).
#include <dumux/linear/istlsolvers.hh>
#include <dumux/linear/linearsolvertraits.hh>
#include <dumux/linear/linearalgebratraits.hh>
#include <dumux/assembly/fvassembler.hh>
#include <dumux/assembly/diffmethod.hh> // analytic or numeric differentiation

// The following class provides a convenient way of writing DuMu<sup>x</sup> simulation results to VTK format.
#include <dumux/io/vtkoutputmodule.hh>
// The gridmanager constructs a grid from the information in the input or grid file.
// Many different Dune grid implementations are supported, of which a list can be found
// in `gridmanager.hh`.
#include <dumux/io/grid/gridmanager.hh>

// For both the single-phase and the tracer problem, `TypeTags` are defined, which collect
// the properties that are required for the simulation. These type tags are defined
// in the headers that we include here. For detailed information, please have a look
// at the documentation provided therein.
#include "properties_1p.hh"
#include "properties_tracer.hh"
// [[/details]]
//

// ### The main function
// We will now discuss the main program flow implemented within the `main` function.
// At the beginning of each program using Dune, an instance of `Dune::MPIHelper` has to
// be created. Moreover, we parse the run-time arguments from the command line and the
// input file:
// [[codeblock]]
int main(int argc, char** argv) try
{
    using namespace Dumux;

    // maybe initialize MPI and/or multithreading backend
    Dumux::initialize(argc, argv);

    // parse command line arguments and input file
    Parameters::init(argc, argv);
    // [[/codeblock]]

    // We define convenience aliases for the type tags of the two problems. The type
    // tags contain all the properties that are needed to define the model and the problem
    // setup. Throughout the main file, we will obtain types defined for these type tags
    // using the property system, i.e. with `GetPropType`. A more detailed documentation
    // for the type tags and properties can be found in the documentation of the single-phase
    // and the tracer transport setups, respectively.
    using OnePTypeTag = Properties::TTag::IncompressibleTest;
    using TracerTypeTag = Properties::TTag::TracerTest;

    // #### Step 1: Create the grid
    // The `GridManager` class creates the grid from information given in the input file.
    // This can either be a grid file, or in the case of structured grids, one can specify the coordinates
    // of the corners of the grid and the number of cells to be used to discretize each spatial direction.
    // Here, we solve both the single-phase and the tracer problem on the same grid, and thus,
    // the grid is only created once using the grid type defined by the `OnePTypeTag` of the single-phase problem.
    // [[codeblock]]
    GridManager<GetPropType<OnePTypeTag, Properties::Grid>> gridManager;
    gridManager.init();

    // We compute on the leaf grid view.
    const auto& leafGridView = gridManager.grid().leafGridView();
    // [[/codeblock]]

    // #### Step 2: Solving the single-phase problem
    // First, a finite volume grid geometry is constructed from the grid that was created above.
    // This builds the sub-control volumes (scv) and sub-control volume faces (scvf) for each element
    // of the grid partition.
    using GridGeometry = GetPropType<OnePTypeTag, Properties::GridGeometry>;
    auto gridGeometry = std::make_shared<GridGeometry>(leafGridView);

    // We now instantiate the problem, in which we define the boundary and initial conditions.
    using OnePProblem = GetPropType<OnePTypeTag, Properties::Problem>;
    auto problemOneP = std::make_shared<OnePProblem>(gridGeometry);

    // The jacobian matrix (`A`), the solution vector (`p`) and the residual (`r`) make up the linear system.
    using JacobianMatrix = GetPropType<OnePTypeTag, Properties::JacobianMatrix>;
    using SolutionVector = GetPropType<OnePTypeTag, Properties::SolutionVector>;
    SolutionVector p(leafGridView.size(0));

    auto A = std::make_shared<JacobianMatrix>();
    auto r = std::make_shared<SolutionVector>();

    // The grid variables are used store variables (primary and secondary variables) on sub-control volumes and faces (volume and flux variables).
    using OnePGridVariables = GetPropType<OnePTypeTag, Properties::GridVariables>;
    auto onePGridVariables = std::make_shared<OnePGridVariables>(problemOneP, gridGeometry);
    onePGridVariables->init(p);

    // We now instantiate the assembler class, assemble the linear system and solve it with the linear
    // solver AMGCGIstlSolver (a conjugate gradient solver preconditioned by an algebraic multigrid).
    // Besides that, the time needed for assembly and solve is measured and printed.
    using OnePAssembler = FVAssembler<OnePTypeTag, DiffMethod::analytic>;
    auto assemblerOneP = std::make_shared<OnePAssembler>(problemOneP, gridGeometry, onePGridVariables);
    assemblerOneP->setLinearSystem(A, r); // tell assembler to use our previously defined system

    Dune::Timer timer;
    Dune::Timer assemblyTimer; std::cout << "Assembling linear system ..." << std::flush;
    assemblerOneP->assembleJacobianAndResidual(p); // assemble linear system around current solution
    assemblyTimer.stop(); std::cout << " took " << assemblyTimer.elapsed() << " seconds." << std::endl;

    (*r) *= -1.0; // We want to solve `Ax = -r`.

    using OnePLinearSolver = AMGCGIstlSolver<LinearSolverTraits<GridGeometry>, LinearAlgebraTraitsFromAssembler<OnePAssembler>>;
    Dune::Timer solverTimer; std::cout << "Solving linear system ..." << std::flush;
    auto onePLinearSolver = std::make_shared<OnePLinearSolver>(gridGeometry->gridView(), gridGeometry->dofMapper());
    onePLinearSolver->solve(*A, p, *r);
    solverTimer.stop(); std::cout << " took " << solverTimer.elapsed() << " seconds." << std::endl;

    Dune::Timer updateTimer; std::cout << "Updating variables ..." << std::flush;
    onePGridVariables->update(p); // update grid variables to new pressure distribution
    updateTimer.elapsed(); std::cout << " took " << updateTimer.elapsed() << std::endl;

    // The solution vector `p` now contains the pressure field, i.e.the solution to the single-phase
    // problem defined in `problem_1p.hh`. Let us now write this solution to a VTK file using the Dune
    // `VTKWriter`. Moreover, we add the permeability distribution to the writer.
    // [[codeblock]]
    using GridView = typename GridGeometry::GridView;
    Dune::VTKWriter<GridView> onepWriter(leafGridView);
    onepWriter.addCellData(p, "p");

    const auto& k = problemOneP->spatialParams().getKField(); // defined in spatialparams_1p.hh
    onepWriter.addCellData(k, "permeability"); // add permeability to writer
    onepWriter.write("1p");  // write the file "1p.vtk"

    // print overall CPU time required for assembling and solving the 1p problem.
    timer.stop();
    const auto& comm = leafGridView.comm();
    std::cout << "Simulation took " << timer.elapsed() << " seconds on "
              << comm.size() << " processes.\n"
              << "The cumulative CPU time was " << timer.elapsed()*comm.size() << " seconds.\n";
    // [[/codeblock]]

    // #### Step 3: Computation of the volume fluxes
    // We use the results of the 1p problem to calculate the volume fluxes across all sub-control volume
    // faces of the discretization and store them in the vector `volumeFlux`. In order to do so, we iterate
    // over all elements of the grid, and in each element compute the volume fluxes for all sub-control volume
    // faces embedded in that element.
    // [[codeblock]]
    using Scalar =  GetPropType<OnePTypeTag, Properties::Scalar>; // type for scalar values
    std::vector<Scalar> volumeFlux(gridGeometry->numScvf(), 0.0);

    using FluxVariables =  GetPropType<OnePTypeTag, Properties::FluxVariables>;
    auto upwindTerm = [](const auto& volVars) { return volVars.mobility(0); };

    // We iterate over all elements
    for (const auto& element : elements(leafGridView))
    {
        // Compute the element-local views on geometry, primary and secondary variables
        // as well as variables needed for flux computations.

        // This creates instances of the local views
        auto fvGeometry = localView(*gridGeometry);
        auto elemVolVars = localView(onePGridVariables->curGridVolVars());
        auto elemFluxVars = localView(onePGridVariables->gridFluxVarsCache());

        // we now have to bind the views to the current element
        fvGeometry.bind(element);
        elemVolVars.bind(element, fvGeometry, p);
        elemFluxVars.bind(element, fvGeometry, elemVolVars);

        // We calculate the volume fluxes for all sub-control volume faces except for Neumann boundary faces
        for (const auto& scvf : scvfs(fvGeometry))
        {
            // skip Neumann boundary faces
            if (scvf.boundary() && problemOneP->boundaryTypes(element, scvf).hasNeumann())
                continue;

            // let the FluxVariables class do the flux computation.
            FluxVariables fluxVars;
            fluxVars.init(*problemOneP, element, fvGeometry, elemVolVars, scvf, elemFluxVars);
            volumeFlux[scvf.index()] = fluxVars.advectiveFlux(0, upwindTerm);
        }
    }
    // [[/codeblock]]

    // #### Step 4: Solving the tracer transport problem
    // First, we instantiate the tracer problem containing initial and boundary conditions,
    // and pass to it the previously computed volume fluxes (see the documentation of the
    // file `spatialparams_tracer.hh` for more details).
    using TracerProblem = GetPropType<TracerTypeTag, Properties::Problem>;
    auto tracerProblem = std::make_shared<TracerProblem>(gridGeometry);
    tracerProblem->spatialParams().setVolumeFlux(volumeFlux);

    // We create and initialize the solution vector. In contrast to the steady-state single-phase problem,
    // the tracer problem is transient, and the initial solution defined in the problem is applied to the
    // solution vector. On the basis of this solution, we initialize then the grid variables.
    SolutionVector x(leafGridView.size(0));
    tracerProblem->applyInitialSolution(x);
    auto xOld = x;

    using GridVariables = GetPropType<TracerTypeTag, Properties::GridVariables>;
    auto gridVariables = std::make_shared<GridVariables>(tracerProblem, gridGeometry);
    gridVariables->init(x);

    // Let us now instantiate the time loop. Therefore, we read in some time loop parameters from the input file.
    // The parameter `tEnd` defines the duration of the simulation, `dt` the initial time step size and `maxDt` the maximal time step size.
    // Moreover, we define 10 check points in the time loop at which we will write the solution to vtk files.
    // [[codeblock]]
    const auto tEnd = getParam<Scalar>("TimeLoop.TEnd");
    auto dt = getParam<Scalar>("TimeLoop.DtInitial");
    const auto maxDt = getParam<Scalar>("TimeLoop.MaxTimeStepSize");

    // We instantiate the time loop.
    auto timeLoop = std::make_shared<CheckPointTimeLoop<Scalar>>(0.0, dt, tEnd);
    timeLoop->setMaxTimeStepSize(maxDt);
    timeLoop->setPeriodicCheckPoint(tEnd/10.0);
    // [[/codeblock]]

    // We create and initialize the assembler with a time loop for the transient problem.
    // Within the time loop, we will use this assembler in each time step to assemble the linear system.
    // As solver we use the ILUBiCGSTABIstlSolver (a bi-conjugate gradient solver preconditioned by an incomplete LU-factorization).
    using TracerAssembler = FVAssembler<TracerTypeTag, DiffMethod::analytic, /*implicit=*/false>;
    auto assembler = std::make_shared<TracerAssembler>(tracerProblem, gridGeometry, gridVariables, timeLoop, xOld);
    assembler->setLinearSystem(A, r);

    using TracerLinearSolver = ILUBiCGSTABIstlSolver<LinearSolverTraits<GridGeometry>, LinearAlgebraTraitsFromAssembler<TracerAssembler>>;
    auto tracerLinearSolver = std::make_shared<TracerLinearSolver>(gridGeometry->gridView(), gridGeometry->dofMapper());

    // The following lines of code initialize the vtk output module, add the velocity output facility
    // and write out the initial solution. At each checkpoint, we will use the output module to write
    // the solution of a time step into a corresponding vtk file.
    // [[codeblock]]
    VtkOutputModule<GridVariables, SolutionVector> vtkWriter(*gridVariables, x, tracerProblem->name());

    // add model-specific output fields to the writer
    using IOFields = GetPropType<TracerTypeTag, Properties::IOFields>;
    IOFields::initOutputModule(vtkWriter);

    // add velocity output facility
    using VelocityOutput = GetPropType<TracerTypeTag, Properties::VelocityOutput>;
    vtkWriter.addVelocityOutput(std::make_shared<VelocityOutput>(*gridVariables));

    // write initial solution
    vtkWriter.write(0.0);
    // [[/codeblock]]

    // ##### The time loop
    // We start the time loop and solve a new time step as long as `tEnd` is not reached. In every time step,
    // the problem is assembled and solved, the solution is updated, and when a checkpoint is reached the solution
    // is written to a new vtk file. In addition, statistics related to CPU time, the current simulation time
    // and the time step sizes used is printed to the terminal.
    // [[codeblock]]
    timeLoop->start(); do
    {
        // Then the linear system is assembled.
        Dune::Timer assembleTimer;
        assembler->assembleJacobianAndResidual(x);
        assembleTimer.stop();

        // We solve the linear system `A(xOld-xNew) = r`.
        Dune::Timer solveTimer;
        SolutionVector xDelta(x);
        tracerLinearSolver->solve(*A, xDelta, *r);
        solveTimer.stop();

        // update the solution vector and the grid variables.
        updateTimer.reset();
        x -= xDelta;
        gridVariables->update(x);
        updateTimer.stop();

        // display the statistics of the actual time step.
        const auto elapsedTot = assembleTimer.elapsed() + solveTimer.elapsed() + updateTimer.elapsed();
        std::cout << "Assemble/solve/update time: "
                  <<  assembleTimer.elapsed() << "(" << 100*assembleTimer.elapsed()/elapsedTot << "%)/"
                  <<  solveTimer.elapsed() << "(" << 100*solveTimer.elapsed()/elapsedTot << "%)/"
                  <<  updateTimer.elapsed() << "(" << 100*updateTimer.elapsed()/elapsedTot << "%)"
                  <<  std::endl;

        // Update the old solution with the one computed in this time step and move to the next one
        xOld = x;
        gridVariables->advanceTimeStep();
        timeLoop->advanceTimeStep();

        // Write the Vtk output on check points.
        if (timeLoop->isCheckPoint())
            vtkWriter.write(timeLoop->time());

        // report statistics of this time step
        timeLoop->reportTimeStep();

        // set the time step size for the next time step
        timeLoop->setTimeStepSize(dt);

    } while (!timeLoop->finished());
    // [[/codeblock]]

    // The following piece of code prints a final status report of the time loop
    //  before the program is terminated.
    timeLoop->finalize(leafGridView.comm());

    return 0;
}
// #### Exception handling
// In this part of the main file we catch and print possible exceptions that could
// occur during the simulation.
// [[details]] exception handler
// [[codeblock]]
// errors related to run-time parameters
catch (Dumux::ParameterException &e)
{
    std::cerr << std::endl << e << " ---> Abort!" << std::endl;
    return 1;
}
// errors related to the parsing of Dune grid files
catch (Dune::DGFException & e)
{
    std::cerr << "DGF exception thrown (" << e <<
                 "). Most likely, the DGF file name is wrong "
                 "or the DGF file is corrupted, "
                 "e.g. missing hash at end of file or wrong number (dimensions) of entries."
                 << " ---> Abort!" << std::endl;
    return 2;
}
// generic error handling with Dune::Exception
catch (Dune::Exception &e)
{
    std::cerr << "Dune reported error: " << e << " ---> Abort!" << std::endl;
    return 3;
}
// other exceptions
catch (...)
{
    std::cerr << "Unknown exception thrown! ---> Abort!" << std::endl;
    return 4;
}
// [[/codeblock]]
// [[/details]]
// [[/content]]
