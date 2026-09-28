"""Process-tree cleanup shared by installation and model execution."""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess


def terminate_process_tree(proc: subprocess.Popen) -> None:
    """Stop a timed-out command and every process it started.

    ``Popen.communicate(timeout=...)`` only terminates the direct child when a
    caller reacts with ``proc.kill()``. Build wrappers commonly leave their
    compiler, ``find``, or network helper descendants alive with our output
    pipes still open. Tear down the Windows process tree, or the private
    process group created for this command on POSIX.
    """
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        taskkill = Path(system_root) / "System32" / "taskkill.exe"
        try:
            result = subprocess.run(
                [str(taskkill), "/PID", str(proc.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode:
                proc.kill()
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass
        return

    # ``start_new_session=True`` below guarantees that proc.pid is a process
    # group created by us, so killpg cannot target GeoForge's own group.
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # The wrapper may exit before a descendant that ignored SIGTERM. The
    # process group continues to exist until every member is gone, so always
    # issue the final bounded kill and harmlessly ignore a vanished group.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass

