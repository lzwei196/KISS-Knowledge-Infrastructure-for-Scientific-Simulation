#!/usr/bin/env python
import numpy as np
from numpy.testing import assert_array_equal

from heat import BmiHeat

grid_id = 0
invalid_grid_id = 12345


def test_grid_var_names():
    model = BmiHeat()
    model.initialize()

    names = model.get_input_var_names()
    assert names == ("plate_surface__temperature",)

    names = model.get_output_var_names()
    assert names == ("plate_surface__temperature",)


def test_grid_var_item_count():
    model = BmiHeat()
    model.initialize()

    count = model.get_input_item_count()
    assert count == 1

    count = model.get_output_item_count()
    assert count == 1


def test_grid_var_units():
    model = BmiHeat()
    model.initialize()
    assert model.get_var_units("plate_surface__temperature") == "K"


def test_grid_id():
    model = BmiHeat()
    model.initialize()
    assert model.get_var_grid("plate_surface__temperature") == grid_id


def test_grid_var_rank():
    model = BmiHeat()
    model.initialize()
    assert model.get_grid_rank(grid_id) == 2


def test_grid_var_size():
    model = BmiHeat()
    model.initialize()
    assert model.get_grid_size(grid_id) == 200


def test_grid_var_shape():
    model = BmiHeat()
    model.initialize()
    ndim = model.get_grid_rank(0)
    shape = np.empty(ndim, dtype=np.int32)
    assert_array_equal(model.get_grid_shape(grid_id, shape), (10, 20))


def test_grid_var_spacing():
    model = BmiHeat()
    model.initialize()
    ndim = model.get_grid_rank(0)
    spacing = np.empty(ndim, dtype=np.int32)
    assert_array_equal(model.get_grid_spacing(grid_id, spacing), (1.0, 1.0))


def test_grid_var_origin():
    model = BmiHeat()
    model.initialize()
    ndim = model.get_grid_rank(0)
    origin = np.empty(ndim, dtype=np.int32)
    assert_array_equal(model.get_grid_origin(grid_id, origin), (0.0, 0.0))


def test_grid_var_type():
    model = BmiHeat()
    model.initialize()
    assert model.get_var_type("plate_surface__temperature") == "float64"


def test_grid_type():
    model = BmiHeat()
    model.initialize()
    assert model.get_grid_type(grid_id) == "uniform_rectilinear"
