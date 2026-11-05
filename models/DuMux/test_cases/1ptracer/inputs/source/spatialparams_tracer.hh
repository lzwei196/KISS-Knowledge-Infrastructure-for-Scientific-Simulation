// -*- mode: C++; tab-width: 4; indent-tabs-mode: nil; c-basic-offset: 4 -*-
// vi: set et ts=4 sw=4 sts=4:
//
// SPDX-FileCopyrightText: Copyright © DuMux Project contributors, see AUTHORS.md in root folder
// SPDX-License-Identifier: GPL-3.0-or-later
//

#ifndef DUMUX_TRACER_TEST_SPATIAL_PARAMS_HH
#define DUMUX_TRACER_TEST_SPATIAL_PARAMS_HH

// ## Parameter distributions (`spatialparams_tracer.hh`)
//
//
// In this file, we define spatial properties of the porous medium such as permeability
// and porosity in various functions for the tracer problem. Furthermore, spatially-dependent
// properties of the tracer fluid system are defined as well as functions related to setting
// and retrieving the volume fluxes calculated from the solution of the 1p problem.
//
// [[content]]
//
// ### Include files
// We include the spatial parameters class for single-phase models discretized by
// finite volume schemes, from which the spatial parameters defined for this example will inherit.
#include <dumux/porousmediumflow/fvspatialparams1p.hh>

// ### The spatial parameters class
//
// In the OnePTestSpatialParams class, we define all functions needed to define
// the spatially-dependent parameters for the tracer problem.
// We inherit from the FVPorousMediumFlowSpatialParamsOneP class here, which is the base class for
// spatial parameters in the context of single-phase porous medium flow applications
// using finite volume discretization schemes.
// [[codeblock]]
namespace Dumux {

template<class GridGeometry, class Scalar>
class TracerTestSpatialParams
: public FVPorousMediumFlowSpatialParamsOneP<GridGeometry, Scalar,
                             TracerTestSpatialParams<GridGeometry, Scalar>>
{
    using GridView = typename GridGeometry::GridView;
    using FVElementGeometry = typename GridGeometry::LocalView;
    using SubControlVolume = typename FVElementGeometry::SubControlVolume;
    using SubControlVolumeFace = typename FVElementGeometry::SubControlVolumeFace;
    using Element = typename GridView::template Codim<0>::Entity;
    using ParentType = FVPorousMediumFlowSpatialParamsOneP<GridGeometry, Scalar,
                                           TracerTestSpatialParams<GridGeometry, Scalar>>;

    static const int dimWorld = GridView::dimensionworld;
    using GlobalPosition = typename Dune::FieldVector<Scalar, dimWorld>;

public:

    TracerTestSpatialParams(std::shared_ptr<const GridGeometry> gridGeometry)
    : ParentType(gridGeometry) {}
    // [[/codeblock]]
    //
    // #### Properties of the porous matrix
    // We define the same porosity for the whole domain as in the 1p spatialparams.
    Scalar porosityAtPos(const GlobalPosition& globalPos) const
    { return 0.2; }

    // #### Properties of the fluid phase
    // In the following, we define fluid phase properties that are spatial parameters
    // in the tracer model.
    // They can possible vary in space but are usually constants.
    // We define the fluid density to a constant value of 1000 $`\frac{kg}{m^3}`$ (liquid water).
    Scalar fluidDensity(const Element &element,
                        const SubControlVolume& scv) const
    { return 1000; }

    // The following functions define the molar mass of the fluid phase as function of the
    // elements of the computational grid and the position in the domain.
    // [[codeblock]]
    // This interface defines the fluid phase's molar mass within the sub-control volume `scv`
    // inside an `element` of the computational grid.
    Scalar fluidMolarMass(const Element& element,
                          const SubControlVolume& scv) const
    { return fluidMolarMassAtPos(scv.dofPosition()); }

    // This interface defines the fluid phase's molar mass depending on the position in the domain.
    Scalar fluidMolarMassAtPos(const GlobalPosition& globalPos) const
    { return 18.0; }
    // [[/codeblock]]
    //
    // #### The volume fluxes
    // The following function returns the volume flux across the given sub-control volume face `scvf`.
    // This flux is obtained from the vector `volumeFlux_` that contains the fluxes across al sub-control
    // volume faces of the discretization. This vector can be set using the `setVolumeFlux` function.
    template<class ElementVolumeVariables>
    Scalar volumeFlux(const Element &element,
                      const FVElementGeometry& fvGeometry,
                      const ElementVolumeVariables& elemVolVars,
                      const SubControlVolumeFace& scvf) const
    {
        return volumeFlux_[scvf.index()];
    }

    // This function allows setting the volume fluxes for all sub-control volume faces of the discretization.
    // This is used in the main function after these fluxes have been based on the pressure solution obtained
    // with the single-phase model.
    void setVolumeFlux(const std::vector<Scalar>& f)
    { volumeFlux_ = f; }

    // The remainder of the class contains the private data members, which in this case
    // are only the volume fluxes across the sub-control volume faces of the discretization.
    // [[codeblock]]
private:
    std::vector<Scalar> volumeFlux_;
}; // end class definition TracerTestSpatialParams
} // end namespace Dumux
// [[/codeblock]]
// [[/content]]
#endif
