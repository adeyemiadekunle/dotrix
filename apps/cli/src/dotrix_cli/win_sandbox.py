"""Windows AppContainer + Job Object process boundary for native local coding.

Import-safe on non-Windows platforms. On Windows, launches the sandboxed bridge inside a
zero-capability AppContainer (no internetClient / privateNetworkClientServer) attached to a
Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, passing an explicit inherited pipe pair
for the host relay.
"""
from __future__ import annotations

import asyncio
import ctypes
import functools
import os
import subprocess
import sys
import uuid
from pathlib import Path

PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
STARTF_USESTDHANDLES = 0x00000100
HANDLE_FLAG_INHERIT = 0x00000001
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
STILL_ACTIVE = 259
INFINITE = 0xFFFFFFFF


def _quote_windows_argv(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv)


def _format_env_block(env: dict[str, str]) -> str:
    items = [f"{k}={v}" for k, v in sorted(env.items())]
    return "\0".join(items) + "\0\0"


def _icacls_grant(path: Path, sid_str: str, rights: str) -> None:
    target = str(path)
    grant = f"*{sid_str}:(OI)(CI){rights}" if path.is_dir() else f"*{sid_str}:{rights}"
    subprocess.run(
        ["icacls", target, "/grant", grant, "/Q", "/C"],
        check=True,
        capture_output=True,
        timeout=30,
    )


def _icacls_remove(path: Path, sid_str: str) -> None:
    if not path.exists():
        return
    subprocess.run(
        ["icacls", str(path), "/remove", f"*{sid_str}", "/Q", "/C"],
        check=False,
        capture_output=True,
        timeout=30,
    )


if sys.platform == "win32":
    import msvcrt
    from ctypes import wintypes

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]

    class SECURITY_CAPABILITIES(ctypes.Structure):
        _fields_ = [
            ("AppContainerSid", wintypes.LPVOID),
            ("Capabilities", wintypes.LPVOID),
            ("CapabilityCount", wintypes.DWORD),
            ("Reserved", wintypes.DWORD),
        ]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [
            ("StartupInfo", STARTUPINFOW),
            ("lpAttributeList", wintypes.LPVOID),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _userenv = ctypes.WinDLL("userenv", use_last_error=True)

    _userenv.CreateAppContainerProfile.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID),
    ]
    _userenv.CreateAppContainerProfile.restype = ctypes.c_long
    _userenv.DeleteAppContainerProfile.argtypes = [wintypes.LPCWSTR]
    _userenv.DeleteAppContainerProfile.restype = ctypes.c_long
    _advapi32.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    _advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    _advapi32.FreeSid.argtypes = [wintypes.LPVOID]
    _advapi32.FreeSid.restype = wintypes.LPVOID
    _kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    _kernel32.LocalFree.restype = wintypes.HLOCAL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(SECURITY_ATTRIBUTES), wintypes.DWORD,
    ]
    _kernel32.CreatePipe.restype = wintypes.BOOL
    _kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    _kernel32.SetHandleInformation.restype = wintypes.BOOL
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.InitializeProcThreadAttributeList.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t),
    ]
    _kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    _kernel32.UpdateProcThreadAttribute.argtypes = [
        wintypes.LPVOID, wintypes.DWORD, ctypes.c_size_t, wintypes.LPVOID,
        ctypes.c_size_t, wintypes.LPVOID, wintypes.LPVOID,
    ]
    _kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    _kernel32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
    _kernel32.DeleteProcThreadAttributeList.restype = None
    _kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID,
        wintypes.BOOL, wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOEXW), ctypes.POINTER(PROCESS_INFORMATION),
    ]
    _kernel32.CreateProcessW.restype = wintypes.BOOL
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.ResumeThread.restype = wintypes.DWORD
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    _kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    _kernel32.GetStdHandle.restype = wintypes.HANDLE


class _AsyncPipeWriter:
    def __init__(self, fd: int):
        self._fd = fd
        self._closed = False

    def write(self, data: bytes) -> None:
        if self._closed:
            raise BrokenPipeError("Pipe closed")
        view = memoryview(data)
        total = 0
        while total < len(data):
            written = os.write(self._fd, view[total:])
            if written <= 0:
                raise BrokenPipeError("Short write on pipe")
            total += written

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                os.close(self._fd)
            except OSError:
                pass


class _AsyncPipeReader:
    def __init__(self, fd: int):
        self._fd = fd
        self._buf = bytearray()
        self._eof = False

    async def readline(self) -> bytes:
        while True:
            newline = self._buf.find(b"\n")
            if newline != -1:
                line = bytes(self._buf[: newline + 1])
                del self._buf[: newline + 1]
                return line
            if self._eof:
                rest = bytes(self._buf)
                self._buf.clear()
                return rest
            chunk = await asyncio.to_thread(os.read, self._fd, 65536)
            if not chunk:
                self._eof = True
            else:
                self._buf.extend(chunk)

    def close(self) -> None:
        try:
            os.close(self._fd)
        except OSError:
            pass


class WindowsSandboxProcess:
    """Async process wrapper matching the subset of asyncio.subprocess.Process fx_local uses."""

    def __init__(
        self,
        *,
        h_process,
        h_job,
        pid: int,
        stdin_fd: int,
        stdout_fd: int,
        relay_read_fd: int,
        relay_write_fd: int,
        profile_name: str,
        sid_str: str,
        acl_paths: list[Path],
    ):
        self._h_process = h_process
        self._h_job = h_job
        self.pid = pid
        self.stdin = _AsyncPipeWriter(stdin_fd)
        self.stdout = _AsyncPipeReader(stdout_fd)
        self.stderr = None
        self.relay_read_fd = relay_read_fd
        self.relay_write_fd = relay_write_fd
        self._profile_name = profile_name
        self._sid_str = sid_str
        self._acl_paths = acl_paths
        self._returncode: int | None = None
        self._cleaned = False

    @property
    def returncode(self) -> int | None:
        if self._returncode is not None:
            return self._returncode
        if sys.platform == "win32" and self._h_process:
            code = wintypes.DWORD(0)
            if _kernel32.GetExitCodeProcess(self._h_process, ctypes.byref(code)) and code.value != STILL_ACTIVE:
                self._returncode = int(code.value)
        return self._returncode

    def kill(self) -> None:
        if sys.platform == "win32" and self._h_job:
            _kernel32.TerminateJobObject(self._h_job, 1)

    async def wait(self) -> int:
        if self._returncode is not None:
            return self._returncode
        if sys.platform == "win32" and self._h_process:
            await asyncio.to_thread(_kernel32.WaitForSingleObject, self._h_process, INFINITE)
            code = wintypes.DWORD(1)
            _kernel32.GetExitCodeProcess(self._h_process, ctypes.byref(code))
            self._returncode = int(code.value)
        else:
            self._returncode = 0
        return self._returncode

    def cleanup(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        self.stdin.close()
        self.stdout.close()
        for fd in (self.relay_read_fd, self.relay_write_fd):
            try:
                os.close(fd)
            except OSError:
                pass
        if sys.platform == "win32":
            if self._h_job:
                _kernel32.TerminateJobObject(self._h_job, 1)
                _kernel32.CloseHandle(self._h_job)
                self._h_job = None
            if self._h_process:
                _kernel32.CloseHandle(self._h_process)
                self._h_process = None
            for path in reversed(self._acl_paths):
                _icacls_remove(path, self._sid_str)
            _userenv.DeleteAppContainerProfile(self._profile_name)


@functools.lru_cache(maxsize=1)
def available() -> bool:
    if sys.platform != "win32":
        return False
    probe_name = f"dotrix.fx.probe.{uuid.uuid4().hex[:12]}"
    sid = wintypes.LPVOID()
    try:
        hr = _userenv.CreateAppContainerProfile(probe_name, "Dotrix Sandbox Probe", "Dotrix probe", None, 0, ctypes.byref(sid))
        if hr != 0:
            return False
        if sid:
            _advapi32.FreeSid(sid)
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            return False
        _kernel32.CloseHandle(job)
        return True
    except OSError:
        return False
    finally:
        try:
            _userenv.DeleteAppContainerProfile(probe_name)
        except OSError:
            pass


def _create_inheritable_pipe() -> tuple[int, int]:
    sa = SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    sa.lpSecurityDescriptor = None
    sa.bInheritHandle = True
    h_read = wintypes.HANDLE()
    h_write = wintypes.HANDLE()
    if not _kernel32.CreatePipe(ctypes.byref(h_read), ctypes.byref(h_write), ctypes.byref(sa), 0):
        raise OSError(ctypes.get_last_error(), "CreatePipe failed")
    return h_read.value, h_write.value


def launch_appcontainer(
    *,
    python_exe: str,
    helper: Path,
    profile: Path,
    binary: Path,
    root: Path,
    temp_dir: Path,
    env: dict[str, str],
    extra_args: list[str] | None = None,
) -> WindowsSandboxProcess:
    if sys.platform != "win32":
        raise RuntimeError("Windows AppContainer isolation is only available on Windows")

    profile_name = f"dotrix.fx.{uuid.uuid4().hex[:16]}"
    sid = wintypes.LPVOID()
    hr = _userenv.CreateAppContainerProfile(
        profile_name,
        "Dotrix Local Coding Sandbox",
        "Zero-capability AppContainer for Dotrix native coding",
        None,
        0,
        ctypes.byref(sid),
    )
    if hr != 0:
        raise RuntimeError(f"CreateAppContainerProfile failed: 0x{hr & 0xFFFFFFFF:08x}")

    sid_ptr = wintypes.LPWSTR()
    acl_paths: list[Path] = []
    handles_to_close: list[int] = []
    h_job = None
    attr_buf = None
    try:
        if not _advapi32.ConvertSidToStringSidW(sid, ctypes.byref(sid_ptr)):
            raise OSError(ctypes.get_last_error(), "ConvertSidToStringSidW failed")
        sid_str = sid_ptr.value
        _kernel32.LocalFree(sid_ptr)

        rw_paths = [root.resolve(), profile.resolve(), temp_dir.resolve()]
        rx_paths = list({
            Path(python_exe).resolve().parent,
            Path(sys.base_prefix).resolve(),
            binary.resolve().parent,
            helper.resolve().parent,
        })
        for path in rw_paths:
            _icacls_grant(path, sid_str, "M")
            acl_paths.append(path)
        for path in rx_paths:
            if path not in acl_paths:
                _icacls_grant(path, sid_str, "RX")
                acl_paths.append(path)

        stdin_r, stdin_w = _create_inheritable_pipe()
        stdout_r, stdout_w = _create_inheritable_pipe()
        relay_to_child_r, relay_to_child_w = _create_inheritable_pipe()
        relay_to_host_r, relay_to_host_w = _create_inheritable_pipe()
        handles_to_close.extend([
            stdin_r, stdin_w, stdout_r, stdout_w,
            relay_to_child_r, relay_to_child_w, relay_to_host_r, relay_to_host_w,
        ])
        for host_end in (stdin_w, stdout_r, relay_to_child_w, relay_to_host_r):
            _kernel32.SetHandleInformation(host_end, HANDLE_FLAG_INHERIT, 0)

        h_stderr = _kernel32.GetStdHandle(wintypes.DWORD(-12 & 0xFFFFFFFF))
        inherit_list = [stdin_r, stdout_w, relay_to_child_r, relay_to_host_w]
        if h_stderr and h_stderr != wintypes.HANDLE(-1).value:
            inherit_list.append(int(h_stderr))

        caps = SECURITY_CAPABILITIES()
        caps.AppContainerSid = sid
        caps.Capabilities = None
        caps.CapabilityCount = 0
        caps.Reserved = 0

        attr_size = ctypes.c_size_t(0)
        _kernel32.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(attr_size))
        attr_buf = ctypes.create_string_buffer(attr_size.value)
        if not _kernel32.InitializeProcThreadAttributeList(attr_buf, 2, 0, ctypes.byref(attr_size)):
            raise OSError(ctypes.get_last_error(), "InitializeProcThreadAttributeList failed")

        if not _kernel32.UpdateProcThreadAttribute(
            attr_buf, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
            ctypes.byref(caps), ctypes.sizeof(caps), None, None,
        ):
            raise OSError(ctypes.get_last_error(), "UpdateProcThreadAttribute(SECURITY_CAPABILITIES) failed")

        handle_array = (wintypes.HANDLE * len(inherit_list))(*inherit_list)
        if not _kernel32.UpdateProcThreadAttribute(
            attr_buf, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            handle_array, ctypes.sizeof(handle_array), None, None,
        ):
            raise OSError(ctypes.get_last_error(), "UpdateProcThreadAttribute(HANDLE_LIST) failed")

        si = STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        si.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        si.StartupInfo.hStdInput = stdin_r
        si.StartupInfo.hStdOutput = stdout_w
        si.StartupInfo.hStdError = h_stderr
        si.lpAttributeList = ctypes.cast(attr_buf, wintypes.LPVOID)

        argv = [
            python_exe, str(helper),
            f"--pipe-fds={relay_to_child_r}:{relay_to_host_w}",
            str(profile), str(binary), *(extra_args or []),
        ]
        cmdline = ctypes.create_unicode_buffer(_quote_windows_argv(argv))
        env_block = ctypes.create_unicode_buffer(_format_env_block(env))
        pi = PROCESS_INFORMATION()
        flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW
        if not _kernel32.CreateProcessW(
            python_exe, cmdline, None, None, True, flags, env_block, str(root),
            ctypes.byref(si), ctypes.byref(pi),
        ):
            raise OSError(ctypes.get_last_error(), "CreateProcessW(AppContainer) failed")

        h_job = _kernel32.CreateJobObjectW(None, None)
        if not h_job:
            _kernel32.TerminateProcess(pi.hProcess, 1)
            _kernel32.CloseHandle(pi.hThread)
            _kernel32.CloseHandle(pi.hProcess)
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")

        limit_info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limit_info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _kernel32.SetInformationJobObject(
            h_job, JobObjectExtendedLimitInformation, ctypes.byref(limit_info), ctypes.sizeof(limit_info),
        ) or not _kernel32.AssignProcessToJobObject(h_job, pi.hProcess):
            _kernel32.TerminateJobObject(h_job, 1)
            _kernel32.CloseHandle(h_job)
            _kernel32.CloseHandle(pi.hThread)
            _kernel32.CloseHandle(pi.hProcess)
            raise OSError(ctypes.get_last_error(), "Failed to attach AppContainer process to Job Object")

        # Close child-side pipe ends in the host before resuming.
        for child_end in (stdin_r, stdout_w, relay_to_child_r, relay_to_host_w):
            _kernel32.CloseHandle(child_end)
            handles_to_close.remove(child_end)

        _kernel32.ResumeThread(pi.hThread)
        _kernel32.CloseHandle(pi.hThread)

        stdin_fd = msvcrt.open_osfhandle(stdin_w, os.O_WRONLY)
        stdout_fd = msvcrt.open_osfhandle(stdout_r, os.O_RDONLY)
        relay_write_fd = msvcrt.open_osfhandle(relay_to_child_w, os.O_WRONLY)
        relay_read_fd = msvcrt.open_osfhandle(relay_to_host_r, os.O_RDONLY)
        handles_to_close.clear()

        return WindowsSandboxProcess(
            h_process=pi.hProcess,
            h_job=h_job,
            pid=int(pi.dwProcessId),
            stdin_fd=stdin_fd,
            stdout_fd=stdout_fd,
            relay_read_fd=relay_read_fd,
            relay_write_fd=relay_write_fd,
            profile_name=profile_name,
            sid_str=sid_str,
            acl_paths=acl_paths,
        )
    except BaseException:
        for h in handles_to_close:
            _kernel32.CloseHandle(h)
        if h_job:
            _kernel32.CloseHandle(h_job)
        for path in reversed(acl_paths):
            _icacls_remove(path, sid_str)
        _userenv.DeleteAppContainerProfile(profile_name)
        raise
    finally:
        if attr_buf is not None:
            _kernel32.DeleteProcThreadAttributeList(attr_buf)
        if sid:
            _advapi32.FreeSid(sid)
