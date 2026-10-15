"""Compatibility exports for the shared native Git workbench implementation."""

from octop.infra.utils.git_workbench import git_snapshot, restore_file

__all__ = ["git_snapshot", "restore_file"]
