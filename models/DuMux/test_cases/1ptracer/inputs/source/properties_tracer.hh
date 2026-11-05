// -*- mode: C++; tab-width: 4; indent-tabs-mode: nil; c-basic-offset: 4 -*-
// vi: set et ts=4 sw=4 sts=4:
//
// SPDX-FileCopyrightText: Copyright © DuMux Project contributors, see AUTHORS.md in root folder
// SPDX-License-Identifier: GPL-3.0-or-later
//

#ifndef DUMUX_TRACER_TEST_PROPERTIES_HH
#define DUMUX_TRACER_TEST_PROPERTIES_HH

// ## Compile-time settings (`properties_tracer.hh`)
//
// This file defines the type tag used for the tracer transport simulation, for
// which we then specialize `properties` to the needs of the desired setup.
//
// [[content]]
//
// ### Includes
// [[details]] includes
// As for the single-phase problem, atype tag is defined also for this simulation.
// Here, we inherit all properties of the `Tracer` type tag, a convenience type tag
// that specializes most of the required properties for tracer transport flow simulations in DuMu<sup>x</sup>.
#include <dumux/porousmediumflow/tracer/model.hh>

// We use YaspGrid, an implementation of the dune grid interface for structured grids.
#include <dune/grid/yaspgrid.hh>
// We want to discretize the equations with the cell centered finite volume scheme using
// two-point-flux approximation.
#include <dumux/discretization/cctpfa.hh>
// This includes the base class for fluid systems. We will define a custom fluid
// system that inherits from that class.
#include <dumux/material/fluidsystems/base.hh>

// We include the problem and spatial parameter headers used for this simulation.
#include "problem_tracer.hh"
#include "spatialparams_tracer.hh"
// [[/details]]
//
// ### Definition of a custom fluid system
//
// In the following, we define a new tracer fluid system that contains a single component
// with a molar mass of 0.3 kg/mol. This fluid system derives from the base class for
// fluid systems `FluidSystems::Base`.
// [[codeblock]]
namespace Dumux {

// In the following, we create a new tracer fluid system and derive from the base fluid system.
template<class TypeTag>
class TracerFluidSystem : public FluidSystems::Base<GetPropType<TypeTag, Properties::Scalar>,
                                                               TracerFluidSystem<TypeTag>>
{
    // Some convenience aliases to be used inside this class.
    using Scalar = GetPropType<TypeTag, Properties::Scalar>;
    using Problem = GetPropType<TypeTag, Properties::Problem>;
    using GridView = typename GetPropType<TypeTag, Properties::GridGeometry>::GridView;
    using Element = typename GridView::template Codim<0>::Entity;
    using FVElementGeometry = typename GetPropType<TypeTag, Properties::GridGeometry>::LocalView;
    using SubControlVolume = typename FVElementGeometry::SubControlVolume;

public:
    // We specify that the fluid system only contains tracer components,
    static constexpr bool isTracerFluidSystem()
    { return true; }

    // We define the number of components of this fluid system (one single tracer component)
    static constexpr int numComponents = 1;

    // This interface is designed to define the names of the components of the fluid system.
    // Here, we only have a single component, so `compIdx` should always be 0.
    // The component name is used for the vtk output.
    static std::string componentName(int compIdx = 0)
    { return "tracer_" + std::to_string(compIdx); }

    // We set the phase name for the phase index (`phaseIdx`) for velocity vtk output:
    // Here, we only have a single phase, so `phaseIdx` should always be zero.
    static std::string phaseName(int phaseIdx = 0)
    { return "Groundwater"; }

    // We set the molar mass of the tracer component with index `compIdx` (should again always be zero here).
    static Scalar molarMass(unsigned int compIdx = 0)
    { return 0.300; }

    // We set the value for the binary diffusion coefficient. This
    // might depend on spatial parameters like pressure / temperature.
    // But, in this case we neglect diffusion and return 0.0.
    static Scalar binaryDiffusionCoefficient(unsigned int compIdx,
                                             const Problem& problem,
                                             const Element& element,
                                             const SubControlVolume& scv)
    { return 0.0; }
};
// [[/codeblock]]
//
// ### Type tag definition
//
// We define a type tag for our simulation with the name `TracerTest` and inherit
// the properties specialized for the type tags `Tracer` and `CCTpfaModel`.
// This way, most of the properties required for tracer transport simulations using
// the cell centered finite volume scheme with two-point-flux approximation are
// conveniently specialized for our new type tag.
// However, some properties depend on user choices and no meaningful default value
// can be set. Those properties will be addressed later in this file.
// [[codeblock]]
namespace Properties {

// declaration of the `TracerTest` type tag for the tracer transport problem
namespace TTag {
struct TracerTest { using InheritsFrom = std::tuple<Tracer, CCTpfaModel>; };
}
// [[/codeblock]]
//
// ### Property specializations
//
// In the following piece of code, mandatory properties for which no meaningful
// default can be set, are specialized for our type tag `TracerTest`.
// [[codeblock]]
// We use the same grid type as in the stationary one-phase model, a structured 2D grid.
template<class TypeTag>
struct Grid<TypeTag, TTag::TracerTest> { using type = Dune::YaspGrid<2>; };

// This sets our problem class (see problem_tracer.hh) that specifies initial and boundary conditions.
template<class TypeTag>
struct Problem<TypeTag, TTag::TracerTest> { using type = TracerTestProblem<TypeTag>; };

// This defines the spatial parameters class (spatialparams_tracer.hh) for our tracer simulation.
template<class TypeTag>
struct SpatialParams<TypeTag, TTag::TracerTest>
{
private:
    using GridGeometry = GetPropType<TypeTag, Properties::GridGeometry>;
    using Scalar = GetPropType<TypeTag, Properties::Scalar>;
public:
    using type = TracerTestSpatialParams<GridGeometry, Scalar>;
};

// We set the tracer fluid system that we have defined above.
template<class TypeTag>
struct FluidSystem<TypeTag, TTag::TracerTest> { using type = TracerFluidSystem<TypeTag>; };
// [[/codeblock]]
//
// The above are all mandatory properties, however, we also specialize the `UseMoles`
// property, which can be used to switch between mole or mass balances to be solved
// in compositional models. It defaults to `true`, and thus, to a molar formulation,
// and we set it to `false` here to specify that we want to solve the mass balance
// equation for the tracer component.
template<class TypeTag>
struct UseMoles<TypeTag, TTag::TracerTest> { static constexpr bool value = false; };

// Moreover, we specialize several properties related to efficiency optimizations
// [[details]] caching properties
// [[codeblock]]
// In Dumux, one has the option to activate/deactivate the grid-wide caching of geometries
// and variables. If active, the CPU time can be significantly reduced as less dynamic
// memory allocation procedures are necessary. Per default, grid-wide caching is disabled
// to ensure minimal memory requirements, however, in this example we want to active all
// available caches, which significanlty increases the memory demand but makes the simulation faster
template<class TypeTag>
struct EnableGridVolumeVariablesCache<TypeTag, TTag::TracerTest> { static constexpr bool value = true; };
template<class TypeTag>
struct EnableGridFluxVariablesCache<TypeTag, TTag::TracerTest> { static constexpr bool value = true; };
template<class TypeTag>
struct EnableGridGeometryCache<TypeTag, TTag::TracerTest> { static constexpr bool value = true; };

// We use solution-independent molecular diffusion coefficients. Per default, solution-dependent
// diffusion coefficients are assumed during the computation of the jacobian matrix entries. Specifying
// solution-independent diffusion coefficients can speed up computations significantly.
template<class TypeTag>
struct SolutionDependentMolecularDiffusion<TypeTag, TTag::TracerTest>
{ static constexpr bool value = false; };

} // end namespace Properties
} // end namespace Dumux
// [[/codeblock]]
// [[/details]]
// [[/content]]
#endif
