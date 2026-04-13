#!/usr/bin/env python3
"""
generate_aed_config.py — Generate AED2 water quality configuration for GLM.

Creates aed2.nml with selected biogeochemical modules. The default
configuration enables: oxygen, nitrogen, phosphorus, organic matter,
sediment flux, and totals — a good starting point for eutrophication studies.

For phytoplankton simulations, use --modules with 'phytoplankton' and set
--phyto_groups to select functional groups (diatom, green, cyano).

Phytoplankton module dependencies:
  - REQUIRES: oxygen, nitrogen, phosphorus, organic_matter, silica (for diatoms)
  - OPTIONAL: carbon (for CO2 limitation)
  - Any missing dependency is auto-added when phytoplankton is enabled.

Usage:
    python generate_aed_config.py --output aed2.nml
    python generate_aed_config.py --modules oxygen,nitrogen,phosphorus \
        --output aed2.nml
    python generate_aed_config.py \
        --modules oxygen,nitrogen,phosphorus,organic_matter,silica,phytoplankton,sedflux,totals \
        --phyto_groups diatom,green,cyano \
        --output aed2.nml
"""

import argparse
import json
import os
import sys


AVAILABLE_MODULES = [
    'oxygen', 'carbon', 'silica', 'nitrogen', 'phosphorus',
    'organic_matter', 'phytoplankton', 'zooplankton',
    'sedflux', 'totals', 'pathogens', 'tracer',
]

DEFAULT_MODULES = ['oxygen', 'nitrogen', 'phosphorus',
                   'organic_matter', 'sedflux', 'totals']

# Phytoplankton functional group presets
# Each group has calibrated defaults from AED2 literature
# (Hipsey et al. 2019, https://doi.org/10.5194/gmd-12-5137-2019)
PHYTO_GROUP_DEFAULTS = {
    'diatom': {
        'label':       'diatom',
        'description': 'Diatoms (Bacillariophyceae)',
        'R_growth':    1.5,    # max growth rate (/day)
        'fT_Method':   1,      # temperature function method
        'theta_growth': 1.06,  # Arrhenius temp coeff for growth
        'T_std':       12.0,   # standard temperature for growth (degC)
        'T_opt':       18.0,   # optimum temperature (degC)
        'T_max':       30.0,   # max temperature (degC)
        'lightModel':  1,      # light limitation model (1=Webb/Steel)
        'I_S':        100.0,   # light saturation intensity (W/m2 PAR)
        'KePHY':       0.004,  # specific light attenuation (/mmolC/m)
        'R_resp':      0.05,   # respiration rate (/day)
        'theta_resp':  1.07,
        'R_mort':      0.02,   # mortality rate (/day)
        'R_excr':      0.02,   # excretion rate (fraction of uptake)
        'N_uptake':    'NIT_nit',  # nitrogen source variable
        'P_uptake':    'PHS_frp',  # phosphorus source variable
        'Si_uptake':   'SIL_rsi',  # silica source (diatoms only)
        'K_N':         3.5,    # half-saturation for N uptake (mmol N/m3)
        'K_P':         0.15,   # half-saturation for P uptake (mmol P/m3)
        'K_Si':       10.0,    # half-saturation for Si uptake (mmol Si/m3)
        'X_ncon':      0.15,   # N:C ratio (mmol N / mmol C)
        'X_pcon':      0.009,  # P:C ratio (mmol P / mmol C)
        'X_sicon':     0.4,    # Si:C ratio (mmol Si / mmol C)
        'w_p':        -0.2,    # sedimentation velocity (m/day, negative=sinking)
        'Xcc':         50.0,   # C:Chl ratio (mg C / mg Chl)
        'p_initial':   5.0,    # initial concentration (mmol C/m3)
    },
    'green': {
        'label':       'green',
        'description': 'Green algae (Chlorophyceae)',
        'R_growth':    1.8,
        'fT_Method':   1,
        'theta_growth': 1.08,
        'T_std':       18.0,
        'T_opt':       25.0,
        'T_max':       35.0,
        'lightModel':  1,
        'I_S':        150.0,
        'KePHY':       0.003,
        'R_resp':      0.06,
        'theta_resp':  1.08,
        'R_mort':      0.03,
        'R_excr':      0.02,
        'N_uptake':    'NIT_nit',
        'P_uptake':    'PHS_frp',
        'Si_uptake':   '',
        'K_N':         4.0,
        'K_P':         0.1,
        'K_Si':        0.0,
        'X_ncon':      0.13,
        'X_pcon':      0.008,
        'X_sicon':     0.0,
        'w_p':        -0.1,
        'Xcc':         40.0,
        'p_initial':   3.0,
    },
    'cyano': {
        'label':       'cyano',
        'description': 'Cyanobacteria (blue-green algae)',
        'R_growth':    0.8,     # slower growth than greens/diatoms
        'fT_Method':   1,
        'theta_growth': 1.09,
        'T_std':       22.0,   # prefer warm water
        'T_opt':       28.0,
        'T_max':       38.0,
        'lightModel':  1,
        'I_S':        120.0,
        'KePHY':       0.005,
        'R_resp':      0.04,
        'theta_resp':  1.07,
        'R_mort':      0.02,
        'R_excr':      0.015,
        'N_uptake':    'NIT_amm',  # cyano prefer ammonium; some fix N2
        'P_uptake':    'PHS_frp',
        'Si_uptake':   '',
        'K_N':         2.0,     # lower N half-sat (competitive advantage at low N)
        'K_P':         0.05,    # lower P half-sat
        'K_Si':        0.0,
        'X_ncon':      0.1,
        'X_pcon':      0.006,
        'X_sicon':     0.0,
        'w_p':         0.05,    # positive = buoyant (gas vacuoles)
        'Xcc':         60.0,
        'p_initial':   1.0,
    },
    'crypto': {
        'label':       'crypto',
        'description': 'Cryptophytes',
        'R_growth':    1.2,
        'fT_Method':   1,
        'theta_growth': 1.07,
        'T_std':       15.0,
        'T_opt':       20.0,
        'T_max':       32.0,
        'lightModel':  1,
        'I_S':         80.0,   # shade-adapted
        'KePHY':       0.003,
        'R_resp':      0.05,
        'theta_resp':  1.07,
        'R_mort':      0.03,
        'R_excr':      0.02,
        'N_uptake':    'NIT_nit',
        'P_uptake':    'PHS_frp',
        'Si_uptake':   '',
        'K_N':         3.0,
        'K_P':         0.1,
        'K_Si':        0.0,
        'X_ncon':      0.14,
        'X_pcon':      0.008,
        'X_sicon':     0.0,
        'w_p':        -0.05,
        'Xcc':         45.0,
        'p_initial':   2.0,
    },
}


def validate_inputs(args):
    """Validate inputs."""
    errors = []
    for mod in args.modules_list:
        if mod not in AVAILABLE_MODULES:
            errors.append(f"Unknown AED module: {mod}. "
                          f"Available: {', '.join(AVAILABLE_MODULES)}")

    if hasattr(args, 'phyto_groups_list') and args.phyto_groups_list:
        for grp in args.phyto_groups_list:
            if grp not in PHYTO_GROUP_DEFAULTS:
                errors.append(
                    f"Unknown phyto group: {grp}. "
                    f"Available: {', '.join(PHYTO_GROUP_DEFAULTS.keys())}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def ensure_phyto_dependencies(modules):
    """
    Auto-add modules required by phytoplankton.

    Phytoplankton couples with oxygen (DO production), nitrogen (N uptake),
    phosphorus (P uptake), organic matter (excretion/mortality products),
    noncohesive sediment (provides NCS_resus for resuspension coupling),
    and optionally silica (diatoms).
    """
    required = ['oxygen', 'nitrogen', 'phosphorus', 'organic_matter',
                'noncohesive']
    added = []
    for req in required:
        if req not in modules:
            modules.append(req)
            added.append(req)
    return modules, added


def generate_phyto_pars_nml(groups):
    """
    Generate aed2_phyto_pars.nml content for libaed2 v1.3.5.

    libaed2 reads phytoplankton group parameters from a separate namelist
    file using &phyto_data blocks with pd% prefixed parameter names.
    Each group gets one &phyto_data block.
    """
    content = "!-- AED2 phytoplankton parameter database --\n"
    content += "!-- Generated by HydroCraft GLM knowledge infrastructure --\n\n"

    for g in groups:
        content += f"!-- {g['description']} --\n"
        content += "&phyto_data\n"
        content += f"  pd%p_name = '{g['label']}'\n"
        content += f"  pd%p_initial = {g['p_initial']}\n"
        content += f"  pd%p0 = 0.03\n"
        content += f"  pd%w_p = {g['w_p']}\n"
        content += f"  pd%Xcc = {g['Xcc']}\n"
        content += f"  pd%R_growth = {g['R_growth']}\n"
        content += f"  pd%fT_Method = {g['fT_Method']}\n"
        content += f"  pd%theta_growth = {g['theta_growth']}\n"
        content += f"  pd%T_std = {g['T_std']}\n"
        content += f"  pd%T_opt = {g['T_opt']}\n"
        content += f"  pd%T_max = {g['T_max']}\n"
        content += f"  pd%lightModel = {g['lightModel']}\n"
        content += f"  pd%I_S = {g['I_S']}\n"
        content += f"  pd%KePHY = {g['KePHY']}\n"
        content += f"  pd%f_pr = 0.025\n"
        content += f"  pd%R_resp = {g['R_resp']}\n"
        content += f"  pd%theta_resp = {g['theta_resp']}\n"
        content += f"  pd%k_fres = 0.6\n"
        content += f"  pd%k_fdom = 0.1\n"
        content += f"  pd%simDINUptake = 1\n"
        content += f"  pd%simDONUptake = 0\n"
        content += f"  pd%simNFixation = 0\n"
        content += f"  pd%simINDynamics = 0\n"
        content += f"  pd%simDIPUptake = 1\n"
        content += f"  pd%simIPDynamics = 0\n"
        has_si = g.get('Si_uptake', '') == 'SIL_rsi'
        content += f"  pd%simSiUptake = {1 if has_si else 0}\n"
        content += f"  pd%K_N = {g['K_N']}\n"
        content += f"  pd%K_P = {g['K_P']}\n"
        content += f"  pd%K_Si = {g['K_Si']}\n"
        content += f"  pd%X_ncon = {g['X_ncon']}\n"
        content += f"  pd%X_pcon = {g['X_pcon']}\n"
        content += f"  pd%X_sicon = {g['X_sicon']}\n"
        content += f"  pd%R_nuptake = 0.08\n"
        content += f"  pd%R_puptake = 0.004\n"
        content += "/\n\n"

    return content


def generate_phyto_block(groups):
    """
    Generate the &aed_phytoplankton namelist block.

    AED2 phytoplankton supports multiple functional groups (up to ~7).
    Each group has its own growth, respiration, mortality, nutrient uptake,
    light limitation, and sedimentation parameters.

    The phytoplankton module computes:
      - Gross primary production (GPP) per group
      - Net growth = GPP - respiration - mortality - excretion - sedimentation
      - Nutrient uptake (N, P, Si) at fixed stoichiometry (Redfield-like)
      - Oxygen production from photosynthesis
      - Chlorophyll-a as diagnostic variable (PHY_tchla)

    Key output variables:
      PHY_<group>  : biomass of each group (mmol C/m3)
      PHY_tchla    : total chlorophyll-a (ug/L)
      PHY_tphy     : total phytoplankton biomass (mmol C/m3)

    Conversion: Chl-a (ug/L) = sum(PHY_group / Xcc * 12.01)
      where Xcc is the C:Chl ratio (mg C / mg Chl-a)
    """
    num_groups = len(groups)
    group_names = ', '.join(f"'PHY_{g['label']}'" for g in groups)
    p_initial_vals = ', '.join(str(g['p_initial']) for g in groups)
    R_growth_vals = ', '.join(str(g['R_growth']) for g in groups)
    fT_Method_vals = ', '.join(str(g['fT_Method']) for g in groups)
    theta_growth_vals = ', '.join(str(g['theta_growth']) for g in groups)
    T_std_vals = ', '.join(str(g['T_std']) for g in groups)
    T_opt_vals = ', '.join(str(g['T_opt']) for g in groups)
    T_max_vals = ', '.join(str(g['T_max']) for g in groups)
    lightModel_vals = ', '.join(str(g['lightModel']) for g in groups)
    I_S_vals = ', '.join(str(g['I_S']) for g in groups)
    KePHY_vals = ', '.join(str(g['KePHY']) for g in groups)
    R_resp_vals = ', '.join(str(g['R_resp']) for g in groups)
    theta_resp_vals = ', '.join(str(g['theta_resp']) for g in groups)
    R_mort_vals = ', '.join(str(g['R_mort']) for g in groups)
    R_excr_vals = ', '.join(str(g['R_excr']) for g in groups)
    K_N_vals = ', '.join(str(g['K_N']) for g in groups)
    K_P_vals = ', '.join(str(g['K_P']) for g in groups)
    X_ncon_vals = ', '.join(str(g['X_ncon']) for g in groups)
    X_pcon_vals = ', '.join(str(g['X_pcon']) for g in groups)
    w_p_vals = ', '.join(str(g['w_p']) for g in groups)
    Xcc_vals = ', '.join(str(g['Xcc']) for g in groups)

    # N and P uptake sources per group
    N_uptake_vals = ', '.join(f"'{g['N_uptake']}'" for g in groups)
    P_uptake_vals = ', '.join(f"'{g['P_uptake']}'" for g in groups)

    # Si parameters (only for diatoms)
    has_si = any(g.get('Si_uptake', '') == 'SIL_rsi' for g in groups)
    si_section = ""
    if has_si:
        K_Si_vals = ', '.join(str(g['K_Si']) for g in groups)
        X_sicon_vals = ', '.join(str(g['X_sicon']) for g in groups)
        Si_uptake_vals = ', '.join(
            f"'{g['Si_uptake']}'" if g.get('Si_uptake') else "''"
            for g in groups)
        si_section = f"""
   !-- Silica uptake (diatoms) --
   simSilicaLim = {', '.join(str(1 if g.get('Si_uptake') else 0) for g in groups)}
   Si_uptake_var = {Si_uptake_vals}
   K_Si = {K_Si_vals}
   X_sicon = {X_sicon_vals}"""

    block = f"""
!-------------------------------------------------------------------------------
! Phytoplankton — {num_groups} functional group(s)
!   Groups: {', '.join(g['description'] for g in groups)}
!   Key output: PHY_tchla (total chlorophyll-a, ug/L)
!
!   Growth limitation: min(f_light, f_N, f_P [, f_Si]) * f_T * R_growth
!   f_light = 1 - exp(-I/I_S)  [Webb/Steel model]
!   f_N = N / (N + K_N)         [Michaelis-Menten]
!   f_P = P / (P + K_P)
!   f_T = theta^(T - T_std)     [Arrhenius]
!
!   Chlorophyll conversion: Chl-a (ug/L) = PHY_group * 12.01 / Xcc
!   Typical Chl-a ranges:
!     Oligotrophic:  <2 ug/L
!     Mesotrophic:   2-8 ug/L
!     Eutrophic:     8-25 ug/L
!     Hypereutrophic: >25 ug/L
!-------------------------------------------------------------------------------
&aed_phytoplankton
   num_phytos = {num_groups}
   the_phytos = {group_names}
   p_initial = {p_initial_vals}

   !-- Growth --
   R_growth = {R_growth_vals}
   fT_Method = {fT_Method_vals}
   theta_growth = {theta_growth_vals}
   T_std = {T_std_vals}
   T_opt = {T_opt_vals}
   T_max = {T_max_vals}

   !-- Light limitation --
   lightModel = {lightModel_vals}
   I_S = {I_S_vals}
   KePHY = {KePHY_vals}

   !-- Respiration and losses --
   R_resp = {R_resp_vals}
   theta_resp = {theta_resp_vals}
   R_mort = {R_mort_vals}
   R_excr = {R_excr_vals}

   !-- Nitrogen uptake --
   simDINUptake = {', '.join(['1'] * num_groups)}
   N_uptake_var = {N_uptake_vals}
   K_N = {K_N_vals}
   X_ncon = {X_ncon_vals}

   !-- Phosphorus uptake --
   simDIPUptake = {', '.join(['1'] * num_groups)}
   P_uptake_var = {P_uptake_vals}
   K_P = {K_P_vals}
   X_pcon = {X_pcon_vals}
{si_section}
   !-- Sedimentation --
   w_p = {w_p_vals}

   !-- Carbon:Chlorophyll ratio (mg C / mg Chl) --
   Xcc = {Xcc_vals}

   !-- Oxygen coupling (photosynthesis produces O2, respiration consumes) --
   simPHY_oxygen = {fmt_bool(True)}
/
"""
    return block


def fmt_bool(val):
    """Format boolean for Fortran namelist."""
    return '.true.' if val else '.false.'


def generate_aed2_nml(modules, phyto_groups=None):
    """Generate aed2.nml content."""
    nml = """!-------------------------------------------------------------------------------
! aed2.nml — AED2 water quality configuration
! Generated by HydroCraft GLM knowledge infrastructure
!-------------------------------------------------------------------------------

&aed2_models
   models = {models}
/
""".format(models=', '.join(f"'aed2_{m}'" for m in modules))

    if 'oxygen' in modules:
        nml += """
&aed2_oxygen
   oxy_initial = 300.0   ! mmol/m3
   Fsed_oxy = -40.0      ! sediment oxygen demand (mmol/m2/day)
   Ksed_oxy = 30.0       ! half-saturation for SOD (mmol/m3)
   theta_sed_oxy = 1.08
   oxy_min = 0.0
   oxy_max = 500.0
/
"""

    if 'nitrogen' in modules:
        nml += """
&aed2_nitrogen
   amm_initial = 2.0     ! mmol/m3
   nit_initial = 5.0     ! mmol/m3
   Rnitrif = 0.1         ! nitrification rate (/day)
   Rdenit = 0.1          ! denitrification rate (/day)
   Fsed_amm = 5.0        ! sediment ammonium flux (mmol/m2/day)
   Fsed_nit = -2.0       ! sediment nitrate flux (mmol/m2/day)
   Knitrif = 62.0        ! O2 half-sat for nitrification
   Kdenit = 20.0         ! O2 half-sat for denitrification
   theta_nitrif = 1.08
   theta_denit = 1.08
/
"""

    if 'phosphorus' in modules:
        nml += """
&aed2_phosphorus
   frp_initial = 0.1     ! mmol/m3
   Fsed_frp = 0.05       ! sediment PO4 flux (mmol/m2/day)
   Ksed_frp = 50.0       ! O2 half-sat for P release
   theta_sed_frp = 1.08
   phosphorus_reactant_variable = 'OXY_oxy'
/
"""

    if 'organic_matter' in modules:
        # Note: libaed2 v1.3.5 has strict namelist parsing for organic_matter.
        # Only use parameters confirmed to exist in the binary.
        # Additional rate parameters use internal defaults.
        nml += """
&aed2_organic_matter
   poc_initial = 10.0    ! mmol/m3
   doc_initial = 50.0    ! mmol/m3
/
"""

    if 'sedflux' in modules:
        nml += """
&aed2_sedflux
   sedflux_model = 'Constant2D'
/
"""

    if 'silica' in modules:
        nml += """
&aed2_silica
   rsi_initial = 50.0    ! mmol/m3
   Fsed_rsi = 5.0        ! sediment silica flux (mmol/m2/day)
   Ksed_rsi = 50.0
   theta_sed_rsi = 1.08
/
"""

    if 'noncohesive' in modules:
        # Noncohesive sediment module — required when phytoplankton is
        # enabled (provides NCS_resus variable for resuspension coupling)
        nml += """
&aed2_noncohesive
   num_ss = 1
   ss_initial = 1.0
   resuspension = 1
   settling = 1
/
"""

    if 'phytoplankton' in modules:
        if phyto_groups:
            groups = [PHYTO_GROUP_DEFAULTS[g] for g in phyto_groups]
        else:
            groups = [PHYTO_GROUP_DEFAULTS['diatom'],
                      PHYTO_GROUP_DEFAULTS['green'],
                      PHYTO_GROUP_DEFAULTS['cyano']]
        num_groups = len(groups)
        # libaed2 v1.3.5 reads phytoplankton parameters from a separate
        # database file (aed2_phyto_pars.nml), not inline in aed2.nml.
        # the_phytos takes integer indices selecting from the database.
        phyto_indices = ', '.join(str(i+1) for i in range(num_groups))
        nml += f"""
&aed2_phytoplankton
   num_phytos = {num_groups}
   the_phytos = {phyto_indices}
   dbase = 'aed2_phyto_pars.nml'
/
"""

    if 'zooplankton' in modules:
        nml += """
!-------------------------------------------------------------------------------
! Zooplankton — grazing on phytoplankton
!   Requires phytoplankton module to be active.
!   Single generic zooplankton group (Daphnia-like).
!-------------------------------------------------------------------------------
&aed2_zooplankton
   num_zoops = 1
   the_zoops = 'ZOO_zoo1'
   zoop_initial = 1.0         ! mmol C/m3

   !-- Grazing --
   R_graze = 1.0              ! max grazing rate (/day)
   theta_graze = 1.08
   K_graze = 5.0              ! half-saturation for grazing (mmol C/m3)

   !-- Respiration --
   R_resp = 0.1               ! respiration rate (/day)
   theta_resp = 1.08

   !-- Mortality --
   R_mort = 0.02              ! mortality rate (/day)

   !-- Nutrient stoichiometry --
   X_ncon = 0.15              ! N:C ratio
   X_pcon = 0.01              ! P:C ratio

   !-- Prey preferences (must match phytoplankton groups) --
   num_prey = 1
   prey_name = 'PHY_green'
   Pgrazer = 1.0
/
"""

    if 'totals' in modules:
        # Build TN and TP vars including phyto contributions if present
        tn_vars = ["'NIT_nit'", "'NIT_amm'", "'OGM_don'", "'OGM_pon'"]
        tp_vars = ["'PHS_frp'", "'OGM_dop'", "'OGM_pop'"]
        toc_vars = ["'OGM_doc'", "'OGM_poc'"]

        if 'phytoplankton' in modules:
            if phyto_groups:
                groups = phyto_groups
            else:
                groups = ['diatom', 'green', 'cyano']
            for g in groups:
                # Each phyto group contributes to TN, TP, TOC
                toc_vars.append(f"'PHY_{g}'")

        nml += f"""
&aed2_totals
   TN_vars = {','.join(tn_vars)}
   TN_varscale = {', '.join(['1.0'] * len(tn_vars))}
   TP_vars = {','.join(tp_vars)}
   TP_varscale = {', '.join(['1.0'] * len(tp_vars))}
   TOC_vars = {','.join(toc_vars)}
   TOC_varscale = {', '.join(['1.0'] * len(toc_vars))}
/
"""

    if 'carbon' in modules:
        nml += """
&aed2_carbon
   dic_initial = 2000.0  ! mmol/m3
   Fsed_dic = 10.0       ! sediment DIC flux
   ch4_initial = 5.0
   Rch4ox = 0.01
   atmco2 = 410.0        ! atmospheric CO2 (ppm)
/
"""

    return nml


def process(args):
    """Generate AED configuration."""
    modules = list(args.modules_list)
    auto_added = []

    # If phytoplankton is enabled, ensure all dependencies are present
    if 'phytoplankton' in modules:
        modules, auto_added = ensure_phyto_dependencies(modules)
        # If diatoms are in the groups, also need silica
        phyto_groups = getattr(args, 'phyto_groups_list', None) or \
            ['diatom', 'green', 'cyano']
        if 'diatom' in phyto_groups and 'silica' not in modules:
            modules.append('silica')
            auto_added.append('silica')
    else:
        phyto_groups = None

    # Ensure module ordering: noncohesive must come before phytoplankton
    # so that NCS_resus variable is registered before phyto needs it
    if 'noncohesive' in modules and 'phytoplankton' in modules:
        nc_idx = modules.index('noncohesive')
        ph_idx = modules.index('phytoplankton')
        if nc_idx > ph_idx:
            modules.remove('noncohesive')
            modules.insert(ph_idx, 'noncohesive')

    # Remove sedflux if present (libaed2 v1.3.5 has strict parsing issues)
    if 'sedflux' in modules:
        modules.remove('sedflux')

    nml_content = generate_aed2_nml(modules, phyto_groups)

    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    with open(args.output, 'w') as f:
        f.write(nml_content)

    # Generate phytoplankton parameter database file if needed
    phyto_pars_file = None
    if phyto_groups:
        groups = [PHYTO_GROUP_DEFAULTS[g] for g in phyto_groups]
        phyto_pars_content = generate_phyto_pars_nml(groups)
        phyto_pars_file = os.path.join(
            os.path.dirname(args.output) or '.', 'aed2_phyto_pars.nml')
        with open(phyto_pars_file, 'w') as f:
            f.write(phyto_pars_content)

    result = {
        "status": "success",
        "output_file": args.output,
        "modules_enabled": modules,
        "num_modules": len(modules),
    }

    if auto_added:
        result["auto_added_dependencies"] = auto_added
        result["note_dependencies"] = (
            f"Modules {auto_added} were auto-added as phytoplankton dependencies")

    if phyto_groups:
        result["phyto_groups"] = phyto_groups
        result["phyto_pars_file"] = phyto_pars_file
        result["phyto_key_outputs"] = {
            "PHY_TCHLA": "Total chlorophyll-a (ug/L)",
        }
        for g in phyto_groups:
            result["phyto_key_outputs"][f"PHY_{g}"] = \
                f"{g} biomass (mmol C/m3)"

    result["note"] = (
        "To enable AED2 in GLM, add a &wq_setup block to glm3.nml "
        "with wq_lib='aed2' and wq_nml_file='aed2.nml'")

    if 'phytoplankton' in modules:
        result["inflow_wq_note"] = (
            "Inflow CSV must include WQ columns for AED2 variables. "
            "Use configure_inflow_wq.py to add nutrient columns to inflow CSV.")
        result["glm_nml_changes_needed"] = [
            "Add: aed_filename = 'aed2.nml'  (in &glm_setup)",
            "Set: inflow_varnum = <number of vars including WQ>",
            "Add WQ vars to inflow_vars list",
            "Add WQ init values to &init_profiles (num_wq_vars, wq_names, wq_init_vals)",
        ]

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate AED2 water quality configuration for GLM")
    parser.add_argument("--modules", type=str,
                        default=','.join(DEFAULT_MODULES),
                        help=f"Comma-separated AED modules "
                             f"(default: {','.join(DEFAULT_MODULES)})")
    parser.add_argument("--phyto_groups", type=str, default=None,
                        help="Phytoplankton functional groups, comma-separated "
                             "(default: diatom,green,cyano). "
                             f"Options: {','.join(PHYTO_GROUP_DEFAULTS.keys())}")
    parser.add_argument("--output", type=str, default="aed2.nml",
                        help="Output aed2.nml path")
    args = parser.parse_args()

    args.modules_list = [m.strip() for m in args.modules.split(',')]
    args.phyto_groups_list = (
        [g.strip() for g in args.phyto_groups.split(',')]
        if args.phyto_groups else None
    )
    validate_inputs(args)
    result = process(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
