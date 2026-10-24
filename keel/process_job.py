"""Windows job containment, assigned inside a trusted bootstrap before tools spawn."""
import ctypes
from ctypes import wintypes
import os
import subprocess
import sys


class WindowsJob:
    def __init__(self):
        self.api=ctypes.WinDLL('kernel32',use_last_error=True)
        api=self.api
        api.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
        api.CreateJobObjectW.restype=wintypes.HANDLE
        api.CloseHandle.argtypes=[wintypes.HANDLE]
        api.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
        api.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
        api.GetCurrentProcess.restype=wintypes.HANDLE
        api.TerminateJobObject.argtypes=[wintypes.HANDLE,wintypes.UINT]
        class Basic(ctypes.Structure):
            _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),
                ('flags',wintypes.DWORD),('min_working',ctypes.c_size_t),('max_working',ctypes.c_size_t),
                ('active_limit',wintypes.DWORD),('affinity',ctypes.c_size_t),
                ('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_=[(name,ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),
                ('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        self.handle=api.CreateJobObjectW(None,None)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        limits=Extended();limits.basic.flags=0x2000 # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            code=ctypes.get_last_error();self.close();raise ctypes.WinError(code)

    def command(self,command):
        # Assign from inside the bootstrap: even venv launcher redirection cannot
        # spawn the tool before job membership is established.
        startup=subprocess.STARTUPINFO()
        os.set_handle_inheritable(int(self.handle),True)
        startup.lpAttributeList={'handle_list':[int(self.handle)]}
        from pathlib import Path
        return [sys.executable,'-u',str(Path(__file__).resolve()),str(int(self.handle)),*map(str,command)],startup

    def finish_launch(self):
        os.set_handle_inheritable(int(self.handle),False)

    def terminate(self):
        sent=bool(self.api.TerminateJobObject(self.handle,1))
        result={'method':'windows_job','tree_signal_sent':sent,'descendants_verified':False}
        if not sent:result['job_error']=ctypes.get_last_error()
        self.close()
        return result

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle);self.handle=None


def bootstrap():
    handle=int(sys.argv[1]);api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
    api.GetCurrentProcess.restype=wintypes.HANDLE
    api.CloseHandle.argtypes=[wintypes.HANDLE]
    if not api.AssignProcessToJobObject(handle,api.GetCurrentProcess()):
        raise ctypes.WinError(ctypes.get_last_error())
    # Controller keeps the only owning handle. No tool inherits a job handle.
    api.CloseHandle(handle)
    child=subprocess.Popen(sys.argv[2:],stdin=subprocess.DEVNULL,shell=False,creationflags=subprocess.CREATE_NO_WINDOW)
    return child.wait()


if __name__=='__main__':
    raise SystemExit(bootstrap())
