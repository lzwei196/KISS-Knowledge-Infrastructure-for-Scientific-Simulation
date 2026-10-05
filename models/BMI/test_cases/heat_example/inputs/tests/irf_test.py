#!/usr/bin/env python
from io import StringIO

import numpy as np
import yaml
from numpy.testing import assert_almost_equal
from numpy.testing import assert_array_equal
from numpy.testing import assert_array_less

from heat import BmiHeat


def test_component_name():
    model = BmiHeat()

    name = model.get_component_name()
    assert name == "The 2D Heat Equation"
    assert model.get_component_name() is name


def test_start_time():
    model = BmiHeat()
    model.initialize()

    assert_almost_equal(model.get_start_time(), 0.0)


def test_end_time():
    model = BmiHeat()
    model.initialize()

    assert_almost_equal(model.get_end_time(), np.finfo("d").max)


def test_initialize_defaults():
    model = BmiHeat()
    model.initialize()

    assert_almost_equal(model.get_current_time(), 0.0)
    z0 = model.get_value_ptr("plate_surface__temperature")
    assert_array_less(z0, 1.0)
    assert_array_less(0.0, z0)


def test_initialize_from_file_like():
    config = StringIO(yaml.dump({"shape": [7, 5]}))
    model = BmiHeat()
    model.initialize(config)

    ndim = model.get_grid_rank(0)
    shape = np.empty(ndim, dtype=np.int32)

    assert_array_equal(model.get_grid_shape(0, shape), (7, 5))


def test_initialize_from_file():
    import os
    import tempfile

    import yaml

    with tempfile.NamedTemporaryFile("w", delete=False) as fp:
        fp.write(yaml.dump({"shape": [7, 5]}))
        name = fp.name

    model = BmiHeat()
    model.initialize(name)

    os.remove(name)

    ndim = model.get_grid_rank(0)
    shape = np.empty(ndim, dtype=np.int32)

    assert_array_equal(model.get_grid_shape(0, shape), (7, 5))


def test_update():
    model = BmiHeat()
    model.initialize()

    for inc in range(10):
        model.update()
        assert_almost_equal(model.get_current_time(), (inc + 1) * model.get_time_step())


def test_update_until():
    model = BmiHeat()
    model.initialize()

    model.update_until(10.1)
    assert_almost_equal(model.get_current_time(), 10.1)


def test_finalize():
    model = BmiHeat()
    model.initialize()
    model.update()
    model.finalize()
