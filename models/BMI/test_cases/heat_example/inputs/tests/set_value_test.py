#!/usr/bin/env python
import numpy as np
from numpy.testing import assert_array_almost_equal

from heat import BmiHeat


def test_set_value():
    model = BmiHeat()
    model.initialize()

    z0 = model.get_value_ptr("plate_surface__temperature")
    z1 = np.zeros_like(z0) - 1

    model.set_value("plate_surface__temperature", z1)

    new_z = model.get_value_ptr("plate_surface__temperature")

    assert new_z is z0
    assert new_z is not z1
    assert_array_almost_equal(new_z, z1)


def test_set_value_at_indices():
    model = BmiHeat()
    model.initialize()

    model.set_value_at_indices("plate_surface__temperature", [0, 2, 4], [-1, -1, -1])

    new_z = model.get_value_ptr("plate_surface__temperature")
    assert_array_almost_equal(new_z.take((0, 2, 4)), -1.0)
