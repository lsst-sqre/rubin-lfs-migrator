import subprocess
from logging import Logger
from typing import List, Optional


def run(
    args: List[str],
    logger: Optional[Logger] = None,
    timeout: Optional[int] = None,
) -> None:
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
            return
    if proc.returncode != 0:
        if logger:
            logger.warning(
                f"Command '{argstr}' failed: rc {proc.returncode}\n"
                + f" -> stdout: {proc.stdout.decode()}\n"
                f" -> stderr: {proc.stderr.decode()}"
            )
    else:
        if logger:
            logger.debug(
                f"Command '{argstr}' succeeded\n"
                + f" -> stdout: {proc.stdout.decode()}\n"
                f" -> stderr: {proc.stderr.decode()}"
            )
