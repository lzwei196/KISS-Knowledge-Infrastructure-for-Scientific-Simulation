// -*- mode: C++; tab-width: 4; indent-tabs-mode: nil; c-basic-offset: 4 -*-
// vi: set et ts=4 sw=4 sts=4:
//
// SPDX-FileCopyrightText: Copyright © DuMux Project contributors, see AUTHORS.md in root folder
// SPDX-License-Identifier: GPL-3.0-or-later
//

#ifndef DUMUX_TRACER_TEST_PROBLEM_HH
#define DUMUX_TRACER_TEST_PROBLEM_HH

// ## Initial and boundary conditions (`problem_tracer.hh`)
//
// This file contains the __problem class__ which defines the initial and boundary
// conditions for the tracer transport simulation.
//
// [[content]]
//
// ### Include files
// Include the `PorousMediumFlowProblem` class, the base
// class from which we will derive.
#include <dumux/porousmediumflow/problem.hh>
// Include the `BoundaryTypes` class which specifies the boundary types set in this problem.
#include <dumux/common/boundarytypes.hh>
// Include the `NumEqVector` class which specifies a field vector with size number of equations in this problem.
#include <dumux/common/numeqvector.hh>

// ### The problem class
//
// We enter the problem class where all necessary boundary conditions and initial
// conditions are set for our simulation. As we are solving a problem related to
// flow in porous media, we inherit from the base class `PorousMediumFlowProblem`.
// [[codeblock]]
namespace Dumux {

template <class TypeTag>
class TracerTestProblem : public PorousMediumFlowProblem<TypeTag>
{
    // A few convenience aliases used throughout this class.
    using ParentType = PorousMediumFlowProblem<TypeTag>;
    using Scalar = GetPropType<TypeTag, Properties::Scalar>;
    using Indices = typename GetPropType<TypeTag, Properties::ModelTraits>::Indices;
    using GridView = typename GetPropType<TypeTag, Properties::GridGeometry>::GridView;
    using GridGeometry = GetPropType<TypeTag, Properties::GridGeometry>;
    using PrimaryVariables = GetPropType<TypeTag, Properties::PrimaryVariables>;
    using BoundaryTypes = Dumux::BoundaryTypes<PrimaryVariables::size()>;
    using FluidSystem = GetPropType<TypeTag, Properties::FluidSystem>;
    using SpatialParams = GetPropType<TypeTag, Properties::SpatialParams>;
    using Element = typename GridGeometry::GridView::template Codim<0>::Entity;
    using GlobalPosition = typename Element::Geometry::GlobalCoordinate;
    using NumEqVector = Dumux::NumEqVector<PrimaryVariables>;
    using GridVariables = GetPropType<TypeTag, Properties::GridVariables>;
    using ElementVolumeVariables = typename GridVariables::GridVolumeVariables::LocalView;
    using ElementFluxVariablesCache = typename GridVariables::GridFluxVariablesCache::LocalView;
    using FVElementGeometry = typename GetPropType<TypeTag, Properties::GridGeometry>::LocalView;
    using SubControlVolumeFace = typename FVElementGeometry::SubControlVolumeFace;
    // We create a convenience bool stating whether mole or mass fractions are used
    static constexpr bool useMoles = getPropValue<TypeTag, Properties::UseMoles>();
    // We create additional convenience integers to make dimWorld and numComponents available in the problem
    static constexpr int dimWorld = GridView::dimensionworld;
    static const int numComponents = FluidSystem::numComponents;

public:
    // This is the constructor of our problem class:
    TracerTestProblem(std::shared_ptr<const GridGeometry> gridGeometry)
    : ParentType(gridGeometry)
    {
        // We print to the terminal whether mole or mass fractions are used
        if(useMoles)
            std::cout<<"problem uses mole fractions" << '\n';
        else
            std::cout<<"problem uses mass fractions" << '\n';
    }
    // [[/codeblock]]

    // #### Boundary conditions
    //
    // We define the __type of boundary conditions__ depending on the location.
    // All boundaries are set to a neumann-type flow boundary condition.
    // [[codeblock]]
    BoundaryTypes boundaryTypesAtPos(const GlobalPosition& globalPos) const
    {
        BoundaryTypes values;
        values.setAllNeumann();
        return values;
    }
    // [[/codeblock]]

    // In the following function we implement the __Neumann boundary conditions__.
    // Here, we define an outflow boundary on the top of the domain and prescribe zero-flux
    // Neumann boundary conditions on all other boundaries.
    // [[codeblock]]
    NumEqVector neumann(const Element& element,
                        const FVElementGeometry& fvGeometry,
                        const ElementVolumeVariables& elemVolVars,
                        const ElementFluxVariablesCache& elemFluxVarsCache,
                        const SubControlVolumeFace& scvf) const
    {
        NumEqVector values(0.0);
        const auto& volVars = elemVolVars[scvf.insideScvIdx()];
        const auto& globalPos = scvf.center();

        // This is the outflow boundary, where tracer is transported by advection with the given flux field.
        if (globalPos[dimWorld-1] > this->gridGeometry().bBoxMax()[dimWorld-1] - eps_)
        {
            values = this->spatialParams().volumeFlux(element, fvGeometry, elemVolVars, scvf)
                     * volVars.massFraction(0, 0) * volVars.density(0)
                     / scvf.area();
            assert(values>=0.0 && "Volume flux at outflow boundary is expected to have a positive sign");
        }

        // Prescribe zero-flux Neumann boundary conditions elsewhere
        else
            values = 0.0;

        return values;
    }
    // [[/codeblock]]

    // #### Initial conditions
    //
    // We specify the initial conditions for the primary variable (tracer mass fraction) depending
    // on the location. Here, we set zero mass fractions everywhere in the domain except for a strip
    // at the bottom of the domain where we set an initial mole fraction of $`10^{-9}`$.
    // [[codeblock]]
    PrimaryVariables initialAtPos(const GlobalPosition& globalPos) const
    {
        // initialize the mole fraction to zero
        PrimaryVariables initialValues(0.0);

        // The initial contamination is located at the bottom of the domain
        if (globalPos[1] < 0.1 + eps_)
        {
            // We chose a mole fraction of 1e-9, but in case the mass fractions
            // are used by the model, we have to convert this value:
            if (useMoles)
                initialValues = 1e-9;
            else
                initialValues = 1e-9*FluidSystem::molarMass(0)
                                    /this->spatialParams().fluidMolarMassAtPos(globalPos);
        }

        return initialValues;
    }
    // [[/codeblock]]
    //
    // The remainder of the class contains an epsilon value used for floating point comparisons.
    // [[codeblock]]
private:
    // We assign a private global variable for the epsilon:
    static constexpr Scalar eps_ = 1e-6;

}; // end class definition TracerTestProblem
} // end namespace Dumux
// [[/codeblock]]
// [[/content]]
#endif
