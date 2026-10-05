// -*- mode: C++; tab-width: 4; indent-tabs-mode: nil; c-basic-offset: 4 -*-
// vi: set et ts=4 sw=4 sts=4:
//
// SPDX-FileCopyrightText: Copyright © DuMux Project contributors, see AUTHORS.md in root folder
// SPDX-License-Identifier: GPL-3.0-or-later
//

#ifndef DUMUX_ONEP_TEST_PROBLEM_HH
#define DUMUX_ONEP_TEST_PROBLEM_HH

// ## Initial and boundary conditions (`problem_1p.hh`)
//
// This file contains the __problem class__ which defines the initial and boundary
// conditions for the single-phase flow simulation.
//
// [[content]]
//
// ### Include files
//
// Include the `PorousMediumFlowProblem` class, the base
// class from which we will derive.
#include <dumux/porousmediumflow/problem.hh>
// Include the `BoundaryTypes` class which specifies the boundary types set in this problem.
#include <dumux/common/boundarytypes.hh>

// ### The problem class
// We enter the problem class where all necessary boundary and initial conditions are set for our simulation.
// As we are solving a problem related to flow in porous media, we inherit from the base class `PorousMediumFlowProblem`.
// [[codeblock]]
namespace Dumux {

template<class TypeTag>
class OnePTestProblem : public PorousMediumFlowProblem<TypeTag>
{
    // A few convenience aliases used throughout this class.
    using ParentType = PorousMediumFlowProblem<TypeTag>;
    using GridView = typename GetPropType<TypeTag, Properties::GridGeometry>::GridView;
    using Element = typename GridView::template Codim<0>::Entity;
    using GlobalPosition = typename Element::Geometry::GlobalCoordinate;

    using Scalar = GetPropType<TypeTag, Properties::Scalar>;
    using PrimaryVariables = GetPropType<TypeTag, Properties::PrimaryVariables>;
    using FVElementGeometry = typename GetPropType<TypeTag, Properties::GridGeometry>::LocalView;
    using SubControlVolumeFace = typename FVElementGeometry::SubControlVolumeFace;
    using GridGeometry = GetPropType<TypeTag, Properties::GridGeometry>;
    using BoundaryTypes = Dumux::BoundaryTypes<PrimaryVariables::size()>;

    static constexpr int dimWorld = GridView::dimensionworld;

public:
    // This is the constructor of our problem class:
    OnePTestProblem(std::shared_ptr<const GridGeometry> gridGeometry)
    : ParentType(gridGeometry) {}
    // [[/codeblock]]

    // #### Boundary conditions
    // With the following function we define the __type of boundary conditions__ depending on the location.
    // Two types of boundary conditions can be specified: Dirichlet or Neumann boundary conditions. On
    // Dirichlet boundaries, the values of the primary variables need to be fixed. On a Neumann boundaries,
    // values for derivatives need to be fixed. Mixed boundary conditions (different types for different
    // equations on the same boundary) are not accepted for cell-centered finite volume schemes.
    // [[codeblock]]
    BoundaryTypes boundaryTypesAtPos(const GlobalPosition& globalPos) const
    {
        // we define a small epsilon value
        Scalar eps = 1.0e-6;

        // Initially, set Neumann boundary conditions for all equations.
        BoundaryTypes values;
        values.setAllNeumann();

        // On the top and bottom, use Dirichlet boundary conditions to prescribe pressures later.
        const auto yMax = this->gridGeometry().bBoxMax()[dimWorld-1];
        if (globalPos[dimWorld-1] < eps || globalPos[dimWorld-1] > yMax - eps)
            values.setAllDirichlet();

        return values;
    }
    // [[/codeblock]]

    // The following function specifies the __values on Dirichlet boundaries__.
    // We need to define values for the primary variable (pressure), for which we
    // set a pressure of 1.1 bar and 1 bar at the bottom and top boundaries, respectively.
    // [[codeblock]]
    PrimaryVariables dirichletAtPos(const GlobalPosition& globalPos) const
    {
        // Instantiate a primary variables object
        PrimaryVariables values;

        // and assign a pressure value in [Pa] such that at the bottom boundary
        // a pressure of 1.1 bar is set, and on the top boundary a pressure of 1 bar.
        values[0] = 1.0e5*(1.1 - globalPos[dimWorld-1]*0.1);
        return values;
    }

}; // end class definition of OnePTestProblem
} // end namespace Dumux
// [[/codeblock]]
// [[/content]]
#endif
