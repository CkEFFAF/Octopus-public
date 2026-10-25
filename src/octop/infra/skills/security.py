"""Bounded, local static checks before installing skill files.

This detects known risky patterns; it does not execute code or certify safety.
Diagnostics contain rule ids and locations, never matched file contents.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import PurePosixPath

from octop_harness.security.tool_guard.rule_guardian import RuleBasedToolGuardian

from octop.infra.agents.security.policy_store import SecuritySettingsStore
from octop.infra.db.repos.settings import SettingsRepo
from octop.infra.errors import ErrorCode, OctopError

logger = logging.getLogger(__name__)
MAX_SCAN_FILE_BYTES = 1024 * 1024
MAX_SCAN_BYTES = 4 * 1024 * 1024
MAX_FINDINGS = 20
_SCRIPT_SUFFIXES = {".md", ".py", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".js", ".ts"}
_OBFUSCATED_EXEC = re.compile(r"\b(?:exec|eval)\s*\(\s*(?:base64\.|b64decode\s*\()", re.I)
_PROMPT_OVERRIDE = re.compile(
    r"ignore\s+(?:all\s+)?(?:previous|system)\s+instructions|忽略(?:之前|先前|系统)的?(?:所有)?指令",
    re.I,
)


def configured_skill_scan_mode(settings_repo: SettingsRepo) -> str:
    return SecuritySettingsStore(settings_repo=settings_repo).load().skill_scan.mode


@dataclass(frozen=True)
class SkillScanFinding:
    path: str
    line: int
    rule_id: str


@lru_cache(maxsize=1)
def _guardian() -> RuleBasedToolGuardian:
    return RuleBasedToolGuardian()


def scan_skill_files(files: Sequence[tuple[str, bytes]]) -> list[SkillScanFinding]:
    findings: list[SkillScanFinding] = []
    scanned = 0
    for path, data in files:
        if path.endswith("/"):
            continue
        if data.startswith((b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf")):
            findings.append(SkillScanFinding(path, 1, "native_executable"))
        else:
            try:
                text = data.decode(
                    "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
                )
            except UnicodeDecodeError:
                if PurePosixPath(path).suffix.lower() in _SCRIPT_SUFFIXES:
                    findings.append(SkillScanFinding(path, 1, "unscannable_script"))
                if len(findings) >= MAX_FINDINGS:
                    return findings[:MAX_FINDINGS]
                continue
            if "\x00" in text:
                findings.append(SkillScanFinding(path, 1, "unscannable_text"))
                if len(findings) >= MAX_FINDINGS:
                    return findings[:MAX_FINDINGS]
                continue
            if len(data) > MAX_SCAN_FILE_BYTES or scanned + len(data) > MAX_SCAN_BYTES:
                findings.append(SkillScanFinding(path, 1, "scan_size_limit"))
            else:
                scanned += len(data)
                # A continuation must not hide a download-and-execute command.
                text = re.sub(r"[\\`^]\r?\n", "", text)
                for number, line in enumerate(text.splitlines(), 1):
                    if len(line) > 65536:
                        findings.append(SkillScanFinding(path, number, "scan_line_limit"))
                        if len(findings) >= MAX_FINDINGS:
                            return findings[:MAX_FINDINGS]
                        continue
                    rules = {
                        finding.rule_id for finding in _guardian().guard("bash", {"command": line})
                    }
                    if _OBFUSCATED_EXEC.search(line):
                        rules.add("obfuscated_execution")
                    if _PROMPT_OVERRIDE.search(line):
                        rules.add("instruction_override")
                    findings.extend(SkillScanFinding(path, number, rule) for rule in sorted(rules))
                    if len(findings) >= MAX_FINDINGS:
                        return findings[:MAX_FINDINGS]
        if len(findings) >= MAX_FINDINGS:
            return findings[:MAX_FINDINGS]
    return findings


def enforce_skill_scan(files: Sequence[tuple[str, bytes]], *, mode: str) -> None:
    if mode == "off":
        return
    findings = scan_skill_files(files)
    if not findings:
        return
    if mode == "block":
        raise OctopError(
            ErrorCode.SKILL_SCAN_BLOCKED,
            "Skill installation blocked by static security scan",
            details={"skill_scan": [asdict(finding) for finding in findings]},
        )
    # Do not include snippets or payloads, which can contain credentials.
    logger.warning("Skill static scan warning: %s", [asdict(finding) for finding in findings])
