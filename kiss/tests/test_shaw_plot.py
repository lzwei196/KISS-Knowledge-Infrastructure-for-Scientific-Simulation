"""SHAW profile images must retain the genuine soil-node depths."""
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "models/SHAW/s6_execution/tools"
FIXTURES = Path(__file__).parent / "fixtures/shaw_trial"
TRIAL_DEPTHS = [0, .05, .10, .15, .20, .30, .50, .70, 1, 1.25, 1.50]


@pytest.fixture
def plotter(monkeypatch):
    pytest.importorskip("matplotlib")
    monkeypatch.syspath_prepend(str(TOOLS))
    for name in ("parse_shaw_output", "plot_shaw_profiles"):
        spec = importlib.util.spec_from_file_location(name, TOOLS / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        monkeypatch.setitem(sys.modules, name, module)
    yield module
    module.plt.close("all")


def test_both_official_profile_panels_use_nonuniform_header_depths(plotter, tmp_path, monkeypatch):
    from matplotlib.axes import Axes
    recorded = []
    original = Axes.pcolormesh

    def capture(self, *args, **kwargs):
        if len(args) >= 3 and plotter.np.asarray(args[1]).ndim == 1:
            recorded.append(plotter.np.asarray(args[1]).tolist())
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "pcolormesh", capture)
    for name in ("temp", "moist"):
        shutil.copy2(FIXTURES / (name + ".txt"), tmp_path / (name + ".out"))
    output = tmp_path / "profiles.png"
    plotter.plot_all(tmp_path, output)
    assert recorded == [TRIAL_DEPTHS, TRIAL_DEPTHS]
    assert output.is_file() and output.stat().st_size > 1000


def test_missing_depth_header_requires_explicit_values(plotter, tmp_path):
    profile = tmp_path / "temp.out"
    profile.write_text("338 12 86 2.7 2.1\n338 13 86 2.9 2.6\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no soil-depth header; supply --depths"):
        plotter.plot_all(tmp_path, tmp_path / "missing.png")
    assert not (tmp_path / "missing.png").exists()
    assert plotter._profile_depths(profile, 2, [0, .05]).tolist() == [0, .05]


@pytest.mark.parametrize("depths", [[0], [0, .05, .10], [0, 0], [.1, 0], [-.1, .2], [0, float("nan")]])
def test_explicit_depths_must_match_finite_increasing_nodes(plotter, tmp_path, depths):
    with pytest.raises(ValueError, match="depths must"):
        plotter._profile_depths(tmp_path / "temp.out", 2, depths)


def test_header_count_cannot_be_silently_sliced(plotter):
    with pytest.raises(ValueError, match="exactly 10 node values"):
        plotter._profile_depths(FIXTURES / "temp.txt", 10)


def test_cli_exposes_explicit_depths(plotter, monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(plotter, "plot_all", lambda *args: captured.append(args))
    monkeypatch.setattr(sys, "argv", ["plot_shaw_profiles.py", "--workdir", str(tmp_path),
                                    "--output", str(tmp_path / "plot.png"), "--depths", "0", "0.05"])
    plotter.main()
    assert captured == [(str(tmp_path), str(tmp_path / "plot.png"), [0, .05])]
