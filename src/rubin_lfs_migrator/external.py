import subprocess
from dataclasses import dataclass
from logging import Logger
from shutil import which
from typing import List, Optional


@dataclass
class ProcessResult:
    stdout: str
    stderr: str
    rc: int


def run(
    args: List[str],
    logger: Optional[Logger] = None,
    timeout: Optional[int] = None,
) -> ProcessResult:
    cmd = args[0]
    if not check_exe(cmd):
        raise RuntimeError(f"{cmd} not found on path")
    argstr = " ".join(args)
    if logger:
        logger.info(f"Running command '{argstr}'")
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        if logger:
            logger.error(
                f"Command '{argstr}' timed out after {timeout} seconds"
            )
            return ProcessResult(stdout="", stderr="", rc=127)
    stdout = proc.stdout.decode()
    stderr = proc.stderr.decode()
    rc = proc.returncode
    if rc != 0:
        if logger:
            logger.warning(
                f"Command '{argstr}' failed: rc {rc}\n"
                + f" -> stdout: {stdout}\n"
                f" -> stderr: {stderr}"
            )
    else:
        if logger:
            logger.debug(
                f"Command '{argstr}' succeeded\n" + f" -> stdout: {stdout}\n"
                f" -> stderr: {stderr}"
            )
    return ProcessResult(stdout=stdout, stderr=stderr, rc=rc)


def check_exe(cmd: str) -> bool:
    if which(cmd):
        return True
    return False
