"""
provenance.py -- standardized run identifier and provenance manifest
(Framework §13). Pure metadata construction -- no file I/O beyond writing
the manifest itself, safe to import alongside ki_tools_common.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ClimateProvenance:
    """Framework §13 standardized run identifier and metadata block.

    Example::

        >>> p = ClimateProvenance(
        ...     model_name="SHAW", model_version="git_abc123", parameter_set="paramset03",
        ...     primary_source="HiCPC", auxiliary_source="ISIMIP3b",
        ...     hicpc_dataset_version="v1.0", isimip_dataset_version="ISIMIP3b_w5e5",
        ...     gcm="ACCESS-CM2", member="r1i1p1f1", scenario="ssp585",
        ...     forcing_mode="direct_hybrid", baseline="1995-2014",
        ...     regridding="conservative_precip_bilinear_other",
        ...     calendar_conversion="none_both_gregorian",
        ...     humidity_derivation="huss_ps_tas_to_hurs",
        ...     snowfall_derivation="fraction_transfer_from_isimip",
        ...     temporal_disaggregation="none_daily",
        ...     spinup_method="convergence", initial_state_id="state_checksum_abc",
        ...     run_start="1979-01-01", run_end="2100-12-31",
        ... )
        >>> p.run_id()
        'SHAW__HiCPC-Hybrid__ACCESS-CM2__r1i1p1f1__ssp585__direct_hybrid__1979-2100__paramset03__v1'
    """

    model_name: str
    model_version: str
    parameter_set: str

    primary_source: str
    auxiliary_source: str | None
    hicpc_dataset_version: str | None
    isimip_dataset_version: str | None

    gcm: str
    member: str
    scenario: str
    forcing_mode: str   # e.g. direct_transient | delta_perturbation | warming_level | direct_hybrid
    baseline: str        # e.g. "1995-2014"

    regridding: str
    calendar_conversion: str
    humidity_derivation: str
    snowfall_derivation: str
    temporal_disaggregation: str

    spinup_method: str
    initial_state_id: str
    run_start: str
    run_end: str

    manifest_version: str = "v1"
    extra: dict[str, Any] = field(default_factory=dict)

    def run_id(self) -> str:
        """Framework §13 example: SHAW__HiCPC-Hybrid__ACCESS-CM2__r1i1p1f1__ssp585__direct_hybrid__1995-2100__paramset03__v1"""
        y0 = self.run_start[:4]
        y1 = self.run_end[:4]
        source_label = self.primary_source if not self.auxiliary_source else f"{self.primary_source}-Hybrid"
        parts = [
            self.model_name, source_label, self.gcm, self.member, self.scenario,
            self.forcing_mode, f"{y0}-{y1}", self.parameter_set, self.manifest_version,
        ]
        return "__".join(parts)

    def to_manifest(self) -> dict[str, Any]:
        """Framework §13 manifest structure (model/climate/processing/simulation blocks)."""
        return {
            "run_id": self.run_id(),
            "model": {
                "name": self.model_name,
                "version": self.model_version,
                "parameter_set": self.parameter_set,
            },
            "climate": {
                "primary_source": self.primary_source,
                "auxiliary_source": self.auxiliary_source,
                "source_versions": {
                    "hicpc": self.hicpc_dataset_version,
                    "isimip": self.isimip_dataset_version,
                },
                "gcm": self.gcm,
                "member": self.member,
                "scenario": self.scenario,
                "forcing_mode": self.forcing_mode,
                "baseline": self.baseline,
            },
            "processing": {
                "regridding": self.regridding,
                "calendar_conversion": self.calendar_conversion,
                "humidity_derivation": self.humidity_derivation,
                "snowfall_derivation": self.snowfall_derivation,
                "temporal_disaggregation": self.temporal_disaggregation,
            },
            "simulation": {
                "spinup_method": self.spinup_method,
                "initial_state_id": self.initial_state_id,
                "run_start": self.run_start,
                "run_end": self.run_end,
            },
            "extra": self.extra,
        }

    def write(self, path: str | Path) -> Path:
        """Write the manifest as JSON next to the model outputs (Framework §13: 'metadata should
        travel with the model outputs rather than being stored only in external notes')."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_manifest(), indent=2, ensure_ascii=False))
        return path
