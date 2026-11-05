// -*- mode: C++; tab-width: 4; indent-tabs-mode: nil; c-basic-offset: 4 -*-
// vi: set et ts=4 sw=4 sts=4:
//
// SPDX-FileCopyrightText: Copyright © DuMux Project contributors, see AUTHORS.md in root folder
// SPDX-License-Identifier: GPL-3.0-or-later
//

#ifndef DUMUX_ONEP_TEST_PROPERTIES_HH
#define DUMUX_ONEP_TEST_PROPERTIES_HH

// ## Compile-time settings (`properties_1p.hh`)
//
// In this file, the type tag used for the single-phase flow simulation is defined,
// for which we then specialize `properties` to the needs of the desired setup.
//
// [[content]]
//
// ### Includes
// [[details]] includes
//
// The `OneP` type tag specializes most of the `properties` required for single-
// phase flow simulations in DuMu<sup>x</sup>. We will use this in the following to inherit the
// respective properties and subsequently specialize those `properties` for our
// type tag, which we want to modify or for which no meaningful default can be set.
#include <dumux/porousmediumflow/1p/model.hh>

// We want to use `YaspGrid`, an implementation of the dune grid interface for structured grids:
#include <dune/grid/yaspgrid.hh>
// In this example, we want to discretize the equations with the cell centered finite volume
// scheme using two-point-flux approximation:
#include <dumux/discretization/cctpfa.hh>
// The fluid properties are specified in the following headers (we use liquid water as the fluid phase):
#include <dumux/material/components/simpleh2o.hh>
#include <dumux/material/fluidsystems/1pliquid.hh>

// The local residual for incompressible flow is included.
#include <dumux/porousmediumflow/1p/incompressiblelocalresidual.hh>

// We include the problem and spatial parameters headers used for this simulation.
#include "problem_1p.hh"
#include "spatialparams_1p.hh"
// [[/details]]
//
// ### Type tag definition
//
// We define a type tag for our simulation with the name `IncompressibleTest`
// and inherit the `properties` specialized for the type tags `OneP` and `CCTpfaModel`.
// This way, most of the `properties` required for single-phase flow simulations
// using the cell centered finite volume scheme with two-point-flux approximation
// are conveniently specialized for our new type tag.
// However, some properties depend on user choices and no meaningful default value can be set.
// Those properties will be addressed later in this file.
// [[codeblock]]
// We enter the namespace Dumux::Properties in order to import the entire Dumux namespace for general use:
namespace Dumux::Properties {

// declaration of the `IncompressibleTest` type tag for the single-phase flow problem
namespace TTag {
struct IncompressibleTest { using InheritsFrom = std::tuple<OneP, CCTpfaModel>; };
}
// [[/codeblock]]

// ### Property specializations
//
// In the following piece of code, mandatory `properties` for which no meaningful
// default can be set, are specialized for our type tag `IncompressibleTest`.
// [[codeblock]]
// This sets the grid type used for the simulation. Here, we use a structured 2D grid.
template<class TypeTag>
struct Grid<TypeTag, TTag::IncompressibleTest> { using type = Dune::YaspGrid<2>; };

// This sets our problem class (see problem_1p.hh) containing initial and boundary conditions.
template<class TypeTag>
struct Problem<TypeTag, TTag::IncompressibleTest> { using type = OnePTestProblem<TypeTag>; };

// This sets our spatial parameters class (see spatialparams_1p.hh) in which we define
// the distributions for porosity and permeability to be used.
template<class TypeTag>
struct SpatialParams<TypeTag, TTag::IncompressibleTest>
{
private:
    using GridGeometry = GetPropType<TypeTag, Properties::GridGeometry>;
    using Scalar = GetPropType<TypeTag, Properties::Scalar>;
public:
    using type = OnePTestSpatialParams<GridGeometry, Scalar>;
};

// This sets the fluid system to be used. Here, we use liquid water as fluid phase.
template<class TypeTag>
struct FluidSystem<TypeTag, TTag::IncompressibleTest>
{
private:
    using Scalar = GetPropType<TypeTag, Properties::Scalar>;
public:
    using type = FluidSystems::OnePLiquid<Scalar, Components::SimpleH2O<Scalar> >;
};
// [[/codeblock]]
//
// These are all mandatory `properties`. However, we also want to specialize the
// `LocalResidual` property, as we want to use analytic differentiation (see `main.cc`).
// The default for the `LocalResidual` property, specialized by the type tag `OneP`,
// is the implementation of the local residual for compressible single-phase flow.
// Therein, the functionality required for analytic derivatives is not implemented
// as for compressible fluids this would require the derivatives of the fluid properties
// (eg density and viscosity) with respect to pressure. For the case of an incompressible
// fluid phase, a specialized local residual is available that contains the required
// functionality, and we set this with the following piece of code:
template<class TypeTag>
struct LocalResidual<TypeTag, TTag::IncompressibleTest> { using type = OnePIncompressibleLocalResidual<TypeTag>; };

// Apart from that, we also set some properties related to memory management
// throughout the simulation.
// [[details]] caching properties
//
// In DuMu<sup>x<\sup>, one has the option to activate/deactivate the grid-wide caching of
// geometries and variables. If active, the CPU time can be significantly reduced
// as less dynamic memory allocation procedures are necessary. Per default, grid-wide
// caching is disabled to ensure minimal memory requirements, however, in this example we
// want to active all available caches, which significanlty increases the memory
// demand but makes the simulation faster.
//
// [[codeblock]]
// This enables grid-wide caching of the volume variables.
template<class TypeTag>
struct EnableGridVolumeVariablesCache<TypeTag, TTag::IncompressibleTest> { static constexpr bool value = true; };
//This enables grid wide caching for the flux variables.
template<class TypeTag>
struct EnableGridFluxVariablesCache<TypeTag, TTag::IncompressibleTest> { static constexpr bool value = true; };
// This enables grid-wide caching for the finite volume grid geometry
template<class TypeTag>
struct EnableGridGeometryCache<TypeTag, TTag::IncompressibleTest> { static constexpr bool value = true; };

} // end namespace Dumux::Properties
// [[/codeblock]]
// [[/details]]
// [[/content]]
#endif
