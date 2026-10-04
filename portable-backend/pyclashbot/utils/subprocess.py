from os import name
from subprocess import PIPE, Popen, TimeoutExpired

# check if running on windows
WIN32 = name == "nt"
ST_INFO = None
CR_FLAGS = 0
if WIN32:
    from subprocess import (
        CREATE_NO_WINDOW,
        STARTF_USESHOWWINDOW,
        STARTF_USESTDHANDLES,
        STARTUPINFO,
        SW_HIDE,
    )

    ST_INFO = STARTUPINFO()
    ST_INFO.dwFlags |= STARTF_USESHOWWINDOW | STARTF_USESTDHANDLES
    ST_INFO.wShowWindow = SW_HIDE
    CR_FLAGS = CREATE_NO_WINDOW


def _terminate_process(
    process: Popen[str],
) -> None:
    """Terminate a process forcefully on Windows."""
    process.kill()


def run(
    args: list[str],
) -> tuple[int, str]:
    with Popen(
        args,
        shell=False,
        bufsize=-1,
        stdout=PIPE,
        stderr=PIPE,
        close_fds=True,
        text=True,
        startupinfo=ST_INFO,
        creationflags=CR_FLAGS,
    ) as process:
        try:
            result, _ = process.communicate(timeout=5)
        except TimeoutExpired:
            if WIN32:
                # pylint: disable=protected-access
                _terminate_process(process)
            process.kill()
            result, _ = process.communicate()
            raise

        assert process.returncode is not None
        return (process.returncode, result)
