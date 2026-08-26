"""Tests for landcover.py — IGBP/USGS classification crosswalks."""
import numpy as np
import pytest
from ki_tools_common.landcover import (
    igbp_to_usgs, usgs_to_igbp, get_canopy_height, IGBP_NAMES, USGS_NAMES,
)


class TestIgbpToUsgs:
    """Test all 17 IGBP classes map correctly."""

    def test_water(self):
        assert igbp_to_usgs(0) == 16

    def test_enf(self):
        assert igbp_to_usgs(1) == 14

    def test_ebf(self):
        assert igbp_to_usgs(2) == 13

    def test_dnf(self):
        assert igbp_to_usgs(3) == 12

    def test_dbf(self):
        assert igbp_to_usgs(4) == 11

    def test_mixed_forest(self):
        assert igbp_to_usgs(5) == 15

    def test_cropland(self):
        assert igbp_to_usgs(12) == 2  # Dryland Crop

    def test_urban(self):
        assert igbp_to_usgs(13) == 1

    def test_snow_ice(self):
        assert igbp_to_usgs(15) == 24

    def test_barren(self):
        assert igbp_to_usgs(16) == 19

    def test_all_17_classes_mapped(self):
        for i in range(17):
            result = igbp_to_usgs(i)
            assert 1 <= result <= 24, f"IGBP {i} mapped to invalid USGS {result}"


class TestNoDataHandling:
    """Test that NoData values are preserved, not converted to Barren."""

    def test_nodata_255_preserved(self):
        arr = np.array([12, 255, 4, 255, 0])
        result = igbp_to_usgs(arr, nodata=255)
        assert result[1] == 255
        assert result[3] == 255
        assert result[0] == 2  # Cropland → Dryland Crop

    def test_negative_values_preserved(self):
        arr = np.array([12, -1, 4])
        result = igbp_to_usgs(arr, nodata=255)
        assert result[1] == 255  # -1 treated as nodata

    def test_out_of_range_preserved(self):
        arr = np.array([12, 99, 4])
        result = igbp_to_usgs(arr, nodata=255)
        assert result[1] == 255

    def test_scalar_nodata(self):
        assert igbp_to_usgs(255) == 255
        assert igbp_to_usgs(-1) == 255


class TestReverseMappingLossiness:
    """Test that usgs_to_igbp is documented as lossy."""

    def test_multiple_usgs_to_same_igbp(self):
        # USGS 2, 3, 4 all map back to IGBP 12 (Cropland)
        assert usgs_to_igbp(2) == 12
        # Round-trip: IGBP 12 → USGS 2 → IGBP 12 (OK)
        assert usgs_to_igbp(igbp_to_usgs(12)) == 12

    def test_round_trip_for_forests(self):
        for igbp in [1, 2, 3, 4, 5]:
            usgs = igbp_to_usgs(igbp)
            igbp_back = usgs_to_igbp(usgs)
            assert igbp_back == igbp, f"IGBP {igbp} → USGS {usgs} → IGBP {igbp_back}"


class TestCanopyHeight:
    def test_cropland_low(self):
        assert get_canopy_height(2) < 2.0  # Crop should be short

    def test_forest_tall(self):
        assert get_canopy_height(14) >= 15.0  # ENF should be tall

    def test_sanity_check_pattern(self):
        """If cropland gets 20m canopy, the mapping is wrong."""
        igbp_cropland = 12
        usgs = igbp_to_usgs(igbp_cropland)
        height = get_canopy_height(usgs)
        assert height < 5.0, f"Cropland got {height}m canopy — mapping is wrong"
