from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from octop.infra.utils.process_lock import ProcessLock


def launcher() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "desktop"
        / "portable"
        / "templates"
        / "portable-start.py"
    )
    spec = importlib.util.spec_from_file_location("portable_start", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_remembers_bind_and_shows_usable_loopback_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = launcher()
    module.__file__ = str(tmp_path / "portable-start.py")
    home = tmp_path / "custom home"
    home.mkdir()
    (home / "config.json").write_text(
        json.dumps({"bind_host": "0.0.0.0", "port": 8188}), encoding="utf-8"
    )
    monkeypatch.setenv("OCTOP_HOME", str(home))
    monkeypatch.delenv("OCTOP_PORT", raising=False)
    monkeypatch.delenv("OCTOP_BIND_HOST", raising=False)
    monkeypatch.setattr(sys, "argv", [module.__file__])
    invocations = []
    monkeypatch.setattr(
        module.runpy, "run_path", lambda path, **kwargs: invocations.append((path, sys.argv.copy()))
    )
    assert module.main() == 0
    assert invocations[0][1] == [str(tmp_path / "launch.py"), "run"]
    assert "http://127.0.0.1:8188" in capsys.readouterr().out
    assert json.loads((home / "config.json").read_text())["bind_host"] == "0.0.0.0"


def test_corrupt_config_does_not_start_or_replace_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = launcher()
    module.__file__ = str(tmp_path / "portable-start.py")
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [module.__file__])
    target = tmp_path / "config.json"
    target.write_text("{broken")
    assert module.main() == 1
    assert target.read_text() == "{broken"


@pytest.mark.parametrize("matching_home", [False, True])
def test_background_reuses_only_a_manager_holding_selected_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, matching_home: bool
) -> None:
    module = launcher()
    module.__file__ = str(tmp_path / "portable-start.py")
    monkeypatch.setenv("OCTOP_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "argv", [module.__file__, "--background", "--open"])
    monkeypatch.setattr(module.runpy, "run_path", lambda path: {"_bootstrap": lambda: None})

    class Healthy:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *args, **kwargs: Healthy())
    opened = []
    monkeypatch.setattr(module.webbrowser, "open", opened.append)
    if matching_home:
        with ProcessLock(tmp_path / ".host.lock"):
            assert module.main() == 0
        assert len(opened) == 1
    else:
        assert module.main() == 1
        assert opened == []
