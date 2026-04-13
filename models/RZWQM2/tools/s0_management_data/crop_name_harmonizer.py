#!/usr/bin/env python3
"""
crop_name_harmonizer.py
=======================
Central crop name mapping across all datasets and DSSAT model files.

Maps between: DSSAT prefixes, CROPGRIDS/NPKGRIDS FAO names, Sacks Crop Calendar
file names, SPAM 4-letter codes, and China Phenology GeoTIFF prefixes.

Usage:
    from crop_name_harmonizer import harmonize
    crop = harmonize("maize")
    print(crop.dssat_prefix)           # "MZCER040"
    print(crop.crop_calendar_file)     # "Maize.crop.calendar.fill.nc.gz"
    print(crop.spam_code)              # "MAIZ"
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class HarmonizedCrop:
    """Unified crop identity across all dataset naming conventions."""
    canonical_name: str
    dssat_prefix: str
    cropgrids_name: str                 # filename fragment in CROPGRIDSv1.08_{name}.nc
    crop_calendar_file: Optional[str]   # filename in ALL_CROPS_netCDF_0.5deg_filled/
    spam_code: Optional[str]            # 4-letter SPAM code (uppercase)
    china_pheno_prefix: Optional[str]   # prefix in CHN_{prefix}_{phase}_{year}.tif
    default_row_spacing_cm: float
    default_density_seeds_ha: int
    default_planting_depth_layer: int = 7


# Master mapping table.
# Each entry: (dssat_prefix, cropgrids_name, crop_calendar_file, spam_code,
#              china_pheno_prefix, row_spacing_cm, density_seeds_ha)
_CROP_TABLE = {
    'maize': (
        'MZCER040', 'maize', 'Maize.crop.calendar.fill.nc.gz', 'MAIZ',
        'Maize', 76.0, 72000,
    ),
    'wheat': (
        'WHCER040', 'wheat', 'Wheat.crop.calendar.fill.nc.gz', 'WHEA',
        'Wheat', 20.0, 3500000,
    ),
    'winter_wheat': (
        'WHCER040', 'wheat', 'Wheat.Winter.crop.calendar.fill.nc.gz', 'WHEA',
        'Wheat', 20.0, 3500000,
    ),
    'rice': (
        'RICER040', 'rice', 'Rice.crop.calendar.fill.nc.gz', 'RICE',
        'Rice(SR&ER)', 25.0, 75000,
    ),
    'rice_late': (
        'RICER040', 'rice', 'Rice.2.crop.calendar.fill.nc.gz', 'RICE',
        'Rice(LR)', 25.0, 75000,
    ),
    'soybean': (
        'SBGRO040', 'soybean', 'Soybeans.crop.calendar.fill.nc.gz', 'SOYB',
        None, 76.0, 350000,
    ),
    'barley': (
        'BACER040', 'barley', 'Barley.crop.calendar.fill.nc.gz', 'BARL',
        None, 18.0, 3000000,
    ),
    'winter_barley': (
        'BACER040', 'barley', 'Barley.Winter.crop.calendar.fill.nc.gz', 'BARL',
        None, 18.0, 3000000,
    ),
    'sorghum': (
        'SGCER040', 'sorghum', 'Sorghum.crop.calendar.fill.nc.gz', 'SORG',
        None, 76.0, 120000,
    ),
    'millet': (
        'MLCER040', 'millet', 'Millet.crop.calendar.fill.nc.gz', 'MILL',
        None, 45.0, 200000,
    ),
    'cotton': (
        'COGRO040', 'cotton', 'Cotton.crop.calendar.fill.nc.gz', 'COTT',
        None, 96.0, 100000,
    ),
    'potato': (
        'PTSUB040', 'potato', 'Potatoes.crop.calendar.fill.nc.gz', 'POTA',
        None, 90.0, 45000,
    ),
    'peanut': (
        'PNGRO040', 'groundnut', 'Groundnuts.crop.calendar.fill.nc.gz', 'GROU',
        None, 90.0, 150000,
    ),
    'sunflower': (
        'SUOIL040', 'sunflower', 'Sunflower.crop.calendar.fill.nc.gz', 'SUNF',
        None, 76.0, 60000,
    ),
    'sugarcane': (
        'SCCAN040', 'sugarcane', None, 'SUGC',
        None, 150.0, 10000,
    ),
    'chickpea': (
        'CHGRO040', 'chickpea', 'Pulses.crop.calendar.fill.nc.gz', 'CHIC',
        None, 45.0, 300000,
    ),
    'cowpea': (
        'CPGRO040', 'cowpea', 'Pulses.crop.calendar.fill.nc.gz', 'COWP',
        None, 75.0, 60000,
    ),
    'bean': (
        'BNGRO040', 'bean', 'Pulses.crop.calendar.fill.nc.gz', 'BEAN',
        None, 76.0, 250000,
    ),
    'canola': (
        'CNGRO040', 'rapeseed', 'Rapeseed.Winter.crop.calendar.fill.nc.gz', 'RAPE',
        None, 30.0, 500000,
    ),
    'alfalfa': (
        'ALFRM040', 'alfalfa', None, None,
        None, 18.0, 450000,
    ),
    'beet_sugar': (
        'BSCER040', 'sugarbeet', 'Sugarbeets.crop.calendar.fill.nc.gz', 'SUGB',
        None, 50.0, 100000,
    ),
    'tomato': (
        'TMGRO040', 'tomato', None, 'TOMA',
        None, 150.0, 20000,
    ),
    'pepper': (
        'PRGRO040', 'pepper', None, None,
        None, 90.0, 30000,
    ),
    'cabbage': (
        'CBGRO040', 'cabbage', None, None,
        None, 60.0, 40000,
    ),
    'faba_bean': (
        'FBGRO040', 'broadbean', 'Pulses.crop.calendar.fill.nc.gz', 'BEAN',
        None, 30.0, 300000,
    ),
    'triticale': (
        'TRCER040', 'triticale', 'Rye.Winter.crop.calendar.fill.nc.gz', None,
        None, 18.0, 3500000,
    ),
    'bermudagrass': (
        'BMFRM040', 'bermudagrass', None, None,
        None, 18.0, 500000,
    ),
    'oats': (
        'BACER040', 'oat', 'Oats.crop.calendar.fill.nc.gz', 'OCER',
        None, 18.0, 3000000,
    ),
    'winter_oats': (
        'BACER040', 'oat', 'Oats.Winter.crop.calendar.fill.nc.gz', 'OCER',
        None, 18.0, 3000000,
    ),
    'cassava': (
        'CSCRP040', 'cassava', 'Cassava.crop.calendar.fill.nc.gz', 'CASS',
        None, 100.0, 10000,
    ),
    'sweet_potato': (
        'PTSUB040', 'sweetpotato', 'Sweet.Potatoes.crop.calendar.fill.nc.gz', 'SWPO',
        None, 100.0, 35000,
    ),
}

# Alias resolution: alternative names → canonical names
_ALIASES = {
    'corn':            'maize',
    'groundnut':       'peanut',
    'rapeseed':        'canola',
    'dry_bean':        'bean',
    'foxtail_millet':  'millet',
    'proso_millet':    'millet',
    'sugarbeet':       'beet_sugar',
    'sugar_beet':      'beet_sugar',
    'sugar_cane':      'sugarcane',
    'paddy':           'rice',
    'paddy_rice':      'rice',
    'spring_wheat':    'wheat',
    'spring_barley':   'barley',
    'velvetbean':      'bean',
    'yam':             'sweet_potato',
}


def harmonize(crop_name: str) -> HarmonizedCrop:
    """
    Resolve a crop name (case-insensitive, alias-aware) to a HarmonizedCrop
    with all dataset-specific identifiers filled.

    Raises ValueError if the crop cannot be resolved.
    """
    key = crop_name.strip().lower().replace(' ', '_')

    # Resolve alias
    if key in _ALIASES:
        key = _ALIASES[key]

    if key not in _CROP_TABLE:
        available = sorted(set(list(_CROP_TABLE.keys()) + list(_ALIASES.keys())))
        raise ValueError(
            f"Unknown crop: '{crop_name}'. "
            f"Supported crops and aliases: {available}"
        )

    entry = _CROP_TABLE[key]
    return HarmonizedCrop(
        canonical_name=key,
        dssat_prefix=entry[0],
        cropgrids_name=entry[1],
        crop_calendar_file=entry[2],
        spam_code=entry[3],
        china_pheno_prefix=entry[4],
        default_row_spacing_cm=entry[5],
        default_density_seeds_ha=entry[6],
    )


def list_supported_crops():
    """Return sorted list of all canonical crop names."""
    return sorted(_CROP_TABLE.keys())


def list_all_names():
    """Return sorted list of all accepted names (canonical + aliases)."""
    return sorted(set(list(_CROP_TABLE.keys()) + list(_ALIASES.keys())))


# China phenology phase → management event mapping
CHINA_PHENOLOGY_PHASES = {
    'Maize': {
        'planting': 'V3',      # third-leaf stage as planting proxy
        'harvest':  'MA',      # maturity
        'other':    ['HE'],    # heading (intermediate validation)
    },
    'Rice(SR&ER)': {
        'planting': 'TR',      # transplanting
        'harvest':  'MA',
        'other':    ['HE'],
    },
    'Rice(LR)': {
        'planting': 'TR',
        'harvest':  'MA',
        'other':    ['HE'],
    },
    'Wheat': {
        'planting': 'GR&EM',   # greening/emergence
        'harvest':  'MA',
        'other':    ['HE'],
    },
}
