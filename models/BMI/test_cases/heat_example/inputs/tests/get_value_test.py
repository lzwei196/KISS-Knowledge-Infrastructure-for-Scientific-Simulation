#!/usr/bin/env python
import numpy as np
from numpy.testing import assert_array_almost_equal
from numpy.testing import assert_array_less

from heat import BmiHeat


def test_get_initial_value():
    model = BmiHeat()
    model.initialize()

    z0 = model.get_value_ptr("plate_surface__temperature")
    assert_array_less(z0, 1.0)
    assert_array_less(0.0, z0)


def test_get_value_copy():
    model = BmiHeat()
    model.initialize()

    dest0 = np.empty(model.get_grid_size(0), dtype=float)
    dest1 = np.empty(model.get_grid_size(0), dtype=float)

    z0 = model.get_value("plate_surface__temperature", dest0)
    z1 = model.get_value("plate_surface__temperature", dest1)

    assert z0 is not z1
    assert_array_almost_equal(z0, z1)


def test_get_value_pointer():
    model = BmiHeat()
    model.initialize()

    dest1 = np.empty(model.get_grid_size(0), dtype=float)

    z0 = model.get_value_ptr("plate_surface__temperature")
    z1 = model.get_value("plate_surface__temperature", dest1)

    assert z0 is not z1
    assert_array_almost_equal(z0.flatten(), z1)

    for _ in range(10):
        model.update()

    assert z0 is model.get_value_ptr("plate_surface__temperature")


def test_get_value_at_indices():
    model = BmiHeat()
    model.initialize()

    dest = np.empty(3, dtype=float)

    z0 = model.get_value_ptr("plate_surface__temperature")
    z1 = model.get_value_at_indices("plate_surface__temperature", dest, [0, 2, 4])

    assert_array_almost_equal(z0.take((0, 2, 4)), z1)


def test_value_size():
    model = BmiHeat()
    model.initialize()

    z = model.get_value_ptr("plate_surface__temperature")
    assert model.get_grid_size(0) == z.size


def test_value_nbytes():
    model = BmiHeat()
    model.initialize()

    z = model.get_value_ptr("plate_surface__temperature")
    assert model.get_var_nbytes("plate_surface__temperature") == z.nbytes
