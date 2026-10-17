"""0028 AC-I03: dev must not share a production-marked OCTOP_HOME."""

from __future__ import annotations

from pathlib import Path

from octop.infra.isolation.home_guard import (
    PRODUCTION_MARKER_NAME,
    check_dev_prod_home_separation,
    is_production_home,
    write_production_marker,
)


def test_unmarked_home_ok(tmp_path: Path) -> None:
    result = check_dev_prod_home_separation(
        tmp_path,
        env={"OCTOP_ENV": "development"},
    )
    assert result.status == "ok"
    assert result.production_marked is False


def test_dev_against_marked_home_fails(tmp_path: Path) -> None:
    write_production_marker(tmp_path)
    assert is_production_home(tmp_path)
    assert (tmp_path / PRODUCTION_MARKER_NAME).is_file()
    result = check_dev_prod_home_separation(
        tmp_path,
        env={"OCTOP_ENV": "development"},
    )
    assert result.status == "fail"
    assert result.ok is False


def test_prod_env_with_marker_ok(tmp_path: Path) -> None:
    write_production_marker(tmp_path)
    result = check_dev_prod_home_separation(
        tmp_path,
        env={"OCTOP_ENV": "production"},
    )
    assert result.status == "ok"


def test_prod_env_without_marker_warns(tmp_path: Path) -> None:
    result = check_dev_prod_home_separation(
        tmp_path,
        env={"OCTOP_ENV": "production"},
    )
    assert result.status == "warn"


def test_guard_warn_mode(tmp_path: Path) -> None:
    write_production_marker(tmp_path)
    result = check_dev_prod_home_separation(
        tmp_path,
        env={"OCTOP_ENV": "dev", "OCTOP_HOME_GUARD": "warn"},
    )
    assert result.status == "warn"
