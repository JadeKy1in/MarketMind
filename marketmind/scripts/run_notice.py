"""A small always-on-top "MarketMind is running" window while a scheduled run is
active (docs/AUTOMATION.md).

2026-10-02: the laptop was restarted by hand mid-run, which killed the run. The
window says a run is in progress and since when; it also registers a shutdown block
reason (ShutdownBlockReasonCreate) and answers WM_QUERYENDSESSION with FALSE, so the
Windows restart / shutdown screen lists MarketMind with that reason. "Restart
anyway" still works. Closing the window only minimises it.

Never part of the run's critical path: the window lives in its own thread, any
tkinter / ctypes failure is kept in `error` (scheduled_run writes it to the run log)
and the run goes on. Off outside Windows and with MARKETMIND_RUN_NOTICE=0 (the test
suite sets it); scheduled_run --dry-run never opens it.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime

ENV = "MARKETMIND_RUN_NOTICE"
REASON = "MarketMind 正在运行，请等它完成后再重启或关机"
POLL_MS = 500
JOIN_S = 5.0                     # bounded wait for the window thread at the end of a run

_GWLP_WNDPROC = -4
_WM_QUERYENDSESSION = 0x0011


def enabled() -> bool:
    return os.name == "nt" and os.getenv(ENV, "1").strip().lower() not in ("0", "false", "no", "off")


def notice_text(started: datetime) -> str:
    return (f"MarketMind 正在运行（{started.astimezone():%H:%M} 开始）\n"
            "请勿重启或关机，完成后此窗口自动关闭")


class run_notice:
    """Context manager: shows the notice on enter, closes it on exit."""

    def __init__(self, started: datetime):
        self.started = started
        self.error: str | None = None
        self.blocking = False            # shutdown reason registered
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        if not enabled():
            return self
        try:
            self._thread = threading.Thread(target=self._run, name="run-notice", daemon=True)
            self._thread.start()
        except Exception as e:                       # never block the run on this
            self.error = f"not shown ({type(e).__name__}: {e})"
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=JOIN_S)
            if self._thread.is_alive() and self.error is None:
                self.error = f"window thread still open after {JOIN_S:.0f} s"
        return False

    def _run(self) -> None:
        try:
            self._window()
        except Exception as e:
            self.error = f"not shown ({type(e).__name__}: {e})"
        # The Tcl interpreter must be freed on the thread that created it; left to the
        # main thread's exit it aborts the process ("Tcl_AsyncDelete ... wrong thread").
        self._keep_proc = None
        import gc
        gc.collect()

    def _window(self) -> None:
        import tkinter as tk
        root = tk.Tk()
        try:
            root.title("MarketMind")
            root.resizable(False, False)
            root.attributes("-topmost", True)
            tk.Label(root, text=notice_text(self.started), justify="left",
                     padx=14, pady=10).pack()
            root.protocol("WM_DELETE_WINDOW", root.iconify)     # the reason stays registered
            root.update_idletasks()
            x = root.winfo_screenwidth() - root.winfo_reqwidth() - 24
            y = root.winfo_screenheight() - root.winfo_reqheight() - 96
            root.geometry(f"+{max(x, 0)}+{max(y, 0)}")
            root.update()
            hwnd = int(root.wm_frame(), 16)                     # the top-level frame window
            try:
                self._keep_proc = _block_shutdown(hwnd)
                self.blocking = True
            except Exception as e:
                self.error = f"shutdown reason not registered ({type(e).__name__}: {e})"

            def poll():
                if self._stop.is_set():
                    if self.blocking:
                        _unblock_shutdown(hwnd)
                    root.destroy()
                else:
                    root.after(POLL_MS, poll)
            root.after(POLL_MS, poll)
            root.mainloop()
        except BaseException:
            try:
                root.destroy()
            except Exception:
                pass
            raise


def _user32():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    lresult = ctypes.c_ssize_t
    user32.ShutdownBlockReasonCreate.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    user32.ShutdownBlockReasonCreate.restype = wintypes.BOOL
    user32.ShutdownBlockReasonDestroy.argtypes = [wintypes.HWND]
    user32.ShutdownBlockReasonDestroy.restype = wintypes.BOOL
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
    user32.CallWindowProcW.restype = lresult
    wndproc = ctypes.WINFUNCTYPE(lresult, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                 wintypes.LPARAM)
    return ctypes, user32, wndproc


def _block_shutdown(hwnd: int):
    """Register the reason and answer WM_QUERYENDSESSION with FALSE (a reason alone is
    only shown for an application that blocks). Must run on the window's own thread.
    Returns the window procedure, which the caller must keep alive."""
    ctypes, user32, wndproc = _user32()
    old = None

    @wndproc
    def proc(h, msg, wparam, lparam):
        if msg == _WM_QUERYENDSESSION:
            return 0
        return user32.CallWindowProcW(old, h, msg, wparam, lparam)

    if not user32.ShutdownBlockReasonCreate(hwnd, REASON):
        raise OSError(ctypes.get_last_error(), "ShutdownBlockReasonCreate failed")
    ctypes.set_last_error(0)
    old = user32.SetWindowLongPtrW(hwnd, _GWLP_WNDPROC, ctypes.cast(proc, ctypes.c_void_p))
    if not old:
        err = ctypes.get_last_error()
        user32.ShutdownBlockReasonDestroy(hwnd)
        raise OSError(err, "window procedure not replaced")
    return proc


def _unblock_shutdown(hwnd: int) -> None:
    try:
        _ctypes, user32, _ = _user32()
        user32.ShutdownBlockReasonDestroy(hwnd)
    except Exception:
        pass                       # the window is destroyed next, which drops the reason too
