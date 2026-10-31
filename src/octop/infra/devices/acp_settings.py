"""Owned device runner overrides; secrets always stay on the execution device."""

from __future__ import annotations

import json
from typing import Any

from octop.infra.agents.settings.acp import ACPSettingsStore


class DeviceACPSettings:
    def __init__(self, devices: Any, owner: int, device_id: str) -> None:
        devices.owned(owner, device_id)
        self.settings = devices.repos.settings_repo
        self.key = f"acp_device:user:{owner}:device:{device_id}"
        self.templates = ACPSettingsStore(
            settings_repo=self.settings, agents_repo=devices.repos.agent_repo
        ).load_runners(owner)

    def overrides(self) -> dict[str, Any]:
        raw = self.settings.get(self.key)
        return json.loads(raw) if raw else {}

    def runners(self) -> dict[str, Any]:
        merged = {**self.templates, **self.overrides()}
        return {name: {**runner, "env": {}} for name, runner in merged.items()}

    def save(self, name: str, runner: dict[str, Any]) -> None:
        if runner.get("env"):
            raise ValueError("Configure credentials and environment on the device itself")
        overrides = self.overrides()
        overrides[name] = {**runner, "env": {}}
        self.settings.set(self.key, json.dumps(overrides))

    def reset(self, name: str) -> None:
        overrides = self.overrides()
        overrides.pop(name, None)
        self.settings.set(self.key, json.dumps(overrides))
