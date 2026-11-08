"""Keep Agent foreground tools available for short work, not timed polling."""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterator
from typing import Any

from octop.i18n import tr


def shell_commands(command: str) -> Iterator[list[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        words: list[str] = []
        for token in lexer:
            if token and all(char in ";&|()\n" for char in token):
                if words:
                    yield words
                    words = []
            else:
                words.append(token)
        if words:
            yield words
    except ValueError:
        return


def foreground_wait_error(name: str, args: dict[str, Any], locale: str) -> str | None:
    name = name.rsplit("/", 1)[-1]
    params = args
    if name == "device_run" and args.get("action") == "command.run":
        params = args.get("params") or {}
    elif name != "execute":
        return None
    timeout = params.get("timeout", 60)
    reject = isinstance(timeout, (int, float)) and timeout > 60
    command = params.get("command")
    argv = params.get("argv")
    commands: list[list[str]] = []
    if isinstance(command, str):
        commands.extend(shell_commands(command))
    elif isinstance(argv, list) and all(isinstance(value, str) for value in argv):
        commands.append(argv)
        for index, value in enumerate(argv[:-1]):
            if value in {"-c", "-lc", "-Command"}:
                commands.extend(shell_commands(argv[index + 1]))
    for words in commands:
        while words and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*=.*", words[0]):
            words = words[1:]
        if not words:
            continue
        program = words[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        if program == "sleep":
            duration = 0.0
            for value in words[1:]:
                match = re.fullmatch(r"(\d+(?:\.\d+)?)([smhd]?)", value)
                if match:
                    duration += (
                        float(match[1]) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[match[2]]
                    )
            reject |= duration > 10
        elif program == "start-sleep":
            values = words[1:]
            for index, value in enumerate(values):
                if value.lower() in {"-seconds", "-s", "-milliseconds"} and index + 1 < len(values):
                    number = values[index + 1]
                    if re.fullmatch(r"\d+(?:\.\d+)?", number):
                        reject |= float(number) > (
                            10000 if value.lower() == "-milliseconds" else 10
                        )
            if values and re.fullmatch(r"\d+(?:\.\d+)?", values[0]):
                reject |= float(values[0]) > 10
    return tr("execution.foregroundWait", locale) if reject else None


def job_label_data(argv: Any) -> dict[str, str]:
    """Return bounded observations, never an invented task purpose or shell body."""
    if not isinstance(argv, list) or not argv or not all(isinstance(value, str) for value in argv):
        return {}
    program = argv[0].replace("\\", "/").rsplit("/", 1)[-1]
    if program.lower().removesuffix(".exe") in {"sh", "bash", "zsh"}:
        script = next(
            (
                arg
                for arg in argv[1:]
                if not any(char.isspace() for char in arg) and arg.endswith(".sh")
            ),
            None,
        )
        if script:
            program = script.replace("\\", "/").rsplit("/", 1)[-1]
    commands = [argv]
    for index, value in enumerate(argv[:-1]):
        if value in {"-c", "-lc", "-Command"}:
            commands.extend(shell_commands(argv[index + 1]))
    log = ""
    gpu = False
    for words in commands:
        for index, word in enumerate(words):
            base = word.replace("\\", "/").rsplit("/", 1)[-1]
            if base == "nvidia-smi":
                gpu = True
            if base in {"tail", "Get-Content"}:
                log = next(
                    (
                        value.replace("\\", "/").rsplit("/", 1)[-1]
                        for value in words[index + 1 :]
                        if value.lower().endswith(".log")
                    ),
                    log,
                )
            if re.fullmatch(r"(?:python[\d.]*|node)(?:\.exe)?", base, re.I):
                script = next(
                    (
                        value
                        for value in words[index + 1 :]
                        if value.lower().endswith((".py", ".js", ".mjs"))
                    ),
                    None,
                )
                if script:
                    program = script.replace("\\", "/").rsplit("/", 1)[-1]
    result = {"program": program[:100]}
    if log:
        result.update(job_kind="log_gpu" if gpu else "log", subject=log[:100])
    elif gpu:
        result["job_kind"] = "gpu"
    return result
