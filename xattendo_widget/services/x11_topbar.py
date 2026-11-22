"""X11 XInput2 raw pointer listener and fullscreen/lock detector for GNOME Top Bar Mode.

On GNOME Shell (X11/Mutter), an override-redirect (Gtk.WindowType.POPUP) window
renders visually on top of the GNOME top bar, but Mutter's Composite Overlay
Window claims X11 pointer input for the top panel strip (y < panel_height).
Listening to XInput2 raw events on the X11 root window receives clicks, drags,
and pointer motion reliably without sudo, GNOME extensions, or extra packages.
"""

import ctypes
import ctypes.util
import os
from typing import Callable, Optional, Tuple

try:
    import gi
    gi.require_version('GLib', '2.0')
    gi.require_version('Gio', '2.0')
    from gi.repository import Gio, GLib
except (ImportError, ValueError):
    Gio = None
    GLib = None

# X11 & XInput2 constants
GENERIC_EVENT = 35
XI_ALL_MASTER_DEVICES = 1
XI_RAW_BUTTON_PRESS = 15
XI_RAW_BUTTON_RELEASE = 16
XI_RAW_MOTION = 17
XA_ATOM = 4
XA_WINDOW = 33
X_SUCCESS = 0
BUTTON1_MASK = 1 << 8
BUTTON2_MASK = 1 << 9
BUTTON3_MASK = 1 << 10


class XIEventMask(ctypes.Structure):
    _fields_ = [
        ('deviceid', ctypes.c_int),
        ('mask_len', ctypes.c_int),
        ('mask', ctypes.POINTER(ctypes.c_ubyte)),
    ]


class XGenericEventCookie(ctypes.Structure):
    _fields_ = [
        ('type', ctypes.c_int),
        ('serial', ctypes.c_ulong),
        ('send_event', ctypes.c_int),
        ('display', ctypes.c_void_p),
        ('extension', ctypes.c_int),
        ('evtype', ctypes.c_int),
        ('cookie', ctypes.c_uint),
        ('data', ctypes.c_void_p),
    ]


class XEvent(ctypes.Union):
    _fields_ = [
        ('type', ctypes.c_int),
        ('xcookie', XGenericEventCookie),
        ('pad', ctypes.c_long * 24),
    ]


class XIRawEvent(ctypes.Structure):
    _fields_ = [
        ('type', ctypes.c_int),
        ('serial', ctypes.c_ulong),
        ('send_event', ctypes.c_int),
        ('display', ctypes.c_void_p),
        ('extension', ctypes.c_int),
        ('evtype', ctypes.c_int),
        ('time', ctypes.c_ulong),
        ('deviceid', ctypes.c_int),
        ('sourceid', ctypes.c_int),
        ('detail', ctypes.c_int),
        ('flags', ctypes.c_int),
    ]


XErrorHandlerFunc = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


def _ignore_x11_error(_dpy, _err) -> int:
    return 0


_IGNORE_ERROR_CB = XErrorHandlerFunc(_ignore_x11_error)


def is_x11_session() -> bool:
    """Return True if running under an X11 display session."""
    session = (os.environ.get('XDG_SESSION_TYPE') or '').lower()
    if session == 'wayland':
        return False
    return bool(os.environ.get('DISPLAY'))


def set_xi_mask(mask_buf, event_id: int) -> None:
    """Set bit for an XInput2 event ID in a byte buffer (equivalent to XISetMask)."""
    mask_buf[event_id >> 3] |= 1 << (event_id & 7)


def _load_x11_libs() -> Tuple[Optional[ctypes.CDLL], Optional[ctypes.CDLL]]:
    x11_name = ctypes.util.find_library('X11') or 'libX11.so.6'
    xi_name = ctypes.util.find_library('Xi') or 'libXi.so.6'
    try:
        libx11 = ctypes.CDLL(x11_name)
        libxi = ctypes.CDLL(xi_name)
    except OSError:
        return (None, None)

    libx11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    libx11.XOpenDisplay.restype = ctypes.c_void_p

    libx11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    libx11.XCloseDisplay.restype = ctypes.c_int

    libx11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    libx11.XDefaultRootWindow.restype = ctypes.c_ulong

    libx11.XConnectionNumber.argtypes = [ctypes.c_void_p]
    libx11.XConnectionNumber.restype = ctypes.c_int

    libx11.XQueryExtension.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    libx11.XQueryExtension.restype = ctypes.c_int

    libx11.XFlush.argtypes = [ctypes.c_void_p]
    libx11.XFlush.restype = ctypes.c_int

    libx11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    libx11.XSync.restype = ctypes.c_int

    libx11.XPending.argtypes = [ctypes.c_void_p]
    libx11.XPending.restype = ctypes.c_int

    libx11.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.POINTER(XEvent)]
    libx11.XNextEvent.restype = ctypes.c_int

    libx11.XGetEventData.argtypes = [ctypes.c_void_p, ctypes.POINTER(XGenericEventCookie)]
    libx11.XGetEventData.restype = ctypes.c_int

    libx11.XFreeEventData.argtypes = [ctypes.c_void_p, ctypes.POINTER(XGenericEventCookie)]
    libx11.XFreeEventData.restype = None

    libx11.XQueryPointer.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_uint),
    ]
    libx11.XQueryPointer.restype = ctypes.c_int

    libx11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    libx11.XInternAtom.restype = ctypes.c_ulong

    libx11.XGetWindowProperty.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_long,
        ctypes.c_long,
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    libx11.XGetWindowProperty.restype = ctypes.c_int

    libx11.XFree.argtypes = [ctypes.c_void_p]
    libx11.XFree.restype = ctypes.c_int

    libx11.XSetErrorHandler.argtypes = [ctypes.c_void_p]
    libx11.XSetErrorHandler.restype = ctypes.c_void_p

    libxi.XIQueryVersion.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    libxi.XIQueryVersion.restype = ctypes.c_int

    libxi.XISelectEvents.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(XIEventMask),
        ctypes.c_int,
    ]
    libxi.XISelectEvents.restype = ctypes.c_int

    return (libx11, libxi)


class X11TopBarInputMonitor:
    """Watches global XInput2 pointer events and fullscreen/lock state on X11."""

    def __init__(
        self,
        on_button_press: Callable[[int, int, int], None],
        on_button_release: Callable[[int, int, int], None],
        on_motion: Callable[[int, int, int], None],
        on_screensaver_changed: Optional[Callable[[bool], None]] = None,
    ) -> None:
        self._on_button_press = on_button_press
        self._on_button_release = on_button_release
        self._on_motion = on_motion
        self._on_screensaver_changed = on_screensaver_changed

        self._libx11: Optional[ctypes.CDLL] = None
        self._libxi: Optional[ctypes.CDLL] = None
        self._dpy: Optional[int] = None
        self._root: int = 0
        self._xi_opcode: int = 0
        self._io_watch_id: Optional[int] = None

        self._atom_active_win: int = 0
        self._atom_wm_state: int = 0
        self._atom_fullscreen: int = 0

        self._dbus: Optional[object] = None
        self._dbus_sub_id: Optional[int] = None
        self._screensaver_active: bool = False

    @property
    def active(self) -> bool:
        return self._dpy is not None and self._io_watch_id is not None

    @property
    def screensaver_active(self) -> bool:
        return self._screensaver_active

    def start(self) -> bool:
        if GLib is None or not is_x11_session():
            return False

        libx11, libxi = _load_x11_libs()
        if not libx11 or not libxi:
            return False

        dpy = libx11.XOpenDisplay(None)
        if not dpy:
            return False

        xi_opcode = ctypes.c_int(0)
        ev_base = ctypes.c_int(0)
        err_base = ctypes.c_int(0)
        if not libx11.XQueryExtension(
            dpy,
            b'XInputExtension',
            ctypes.byref(xi_opcode),
            ctypes.byref(ev_base),
            ctypes.byref(err_base),
        ):
            libx11.XCloseDisplay(dpy)
            return False

        major = ctypes.c_int(2)
        minor = ctypes.c_int(2)
        if libxi.XIQueryVersion(dpy, ctypes.byref(major), ctypes.byref(minor)) != X_SUCCESS or major.value < 2:
            libx11.XCloseDisplay(dpy)
            return False

        root = libx11.XDefaultRootWindow(dpy)
        mask_buf = (ctypes.c_ubyte * 4)()
        set_xi_mask(mask_buf, XI_RAW_BUTTON_PRESS)
        set_xi_mask(mask_buf, XI_RAW_BUTTON_RELEASE)
        set_xi_mask(mask_buf, XI_RAW_MOTION)

        evmask = XIEventMask()
        evmask.deviceid = XI_ALL_MASTER_DEVICES
        evmask.mask_len = 4
        evmask.mask = ctypes.cast(mask_buf, ctypes.POINTER(ctypes.c_ubyte))

        libxi.XISelectEvents(dpy, root, ctypes.byref(evmask), 1)
        libx11.XFlush(dpy)

        self._libx11 = libx11
        self._libxi = libxi
        self._dpy = dpy
        self._root = root
        self._xi_opcode = xi_opcode.value

        self._atom_active_win = libx11.XInternAtom(dpy, b'_NET_ACTIVE_WINDOW', 0)
        self._atom_wm_state = libx11.XInternAtom(dpy, b'_NET_WM_STATE', 0)
        self._atom_fullscreen = libx11.XInternAtom(dpy, b'_NET_WM_STATE_FULLSCREEN', 0)

        fd = libx11.XConnectionNumber(dpy)
        self._io_watch_id = GLib.io_add_watch(
            fd,
            GLib.PRIORITY_DEFAULT,
            GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
            self._on_x11_io,
        )

        self._setup_screensaver_watch()
        return True

    def _setup_screensaver_watch(self) -> None:
        if Gio is None:
            return
        try:
            self._dbus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._dbus_sub_id = self._dbus.signal_subscribe(
                'org.gnome.ScreenSaver',
                'org.gnome.ScreenSaver',
                'ActiveChanged',
                '/org/gnome/ScreenSaver',
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_dbus_screensaver_signal,
            )
        except Exception:
            self._dbus = None
            self._dbus_sub_id = None

    def _on_dbus_screensaver_signal(
        self,
        _conn,
        _sender,
        _obj_path,
        _iface,
        _signal,
        params,
    ) -> None:
        try:
            is_active = bool(params.unpack()[0])
            self._screensaver_active = is_active
            if self._on_screensaver_changed:
                self._on_screensaver_changed(is_active)
        except Exception:
            pass

    def query_pointer(self) -> Optional[Tuple[int, int, int]]:
        """Return current root-window pointer position and button/modifier mask (x_px, y_px, mask)."""
        if not self._dpy or not self._libx11:
            return None
        root_ret = ctypes.c_ulong(0)
        child_ret = ctypes.c_ulong(0)
        rx = ctypes.c_int(0)
        ry = ctypes.c_int(0)
        wx = ctypes.c_int(0)
        wy = ctypes.c_int(0)
        mask = ctypes.c_uint(0)
        ok = self._libx11.XQueryPointer(
            self._dpy,
            self._root,
            ctypes.byref(root_ret),
            ctypes.byref(child_ret),
            ctypes.byref(rx),
            ctypes.byref(ry),
            ctypes.byref(wx),
            ctypes.byref(wy),
            ctypes.byref(mask),
        )
        if not ok:
            return None
        return (rx.value, ry.value, mask.value)

    def is_fullscreen_active(self) -> bool:
        """Return True if the currently focused X11 window has _NET_WM_STATE_FULLSCREEN."""
        if not self._dpy or not self._libx11 or not self._atom_active_win:
            return False

        libx11 = self._libx11
        dpy = self._dpy
        actual_type = ctypes.c_ulong(0)
        actual_format = ctypes.c_int(0)
        nitems = ctypes.c_ulong(0)
        bytes_after = ctypes.c_ulong(0)
        prop = ctypes.c_void_p(0)

        prev_handler = libx11.XSetErrorHandler(ctypes.cast(_IGNORE_ERROR_CB, ctypes.c_void_p))
        try:
            status = libx11.XGetWindowProperty(
                dpy,
                self._root,
                self._atom_active_win,
                0,
                1,
                0,
                XA_WINDOW,
                ctypes.byref(actual_type),
                ctypes.byref(actual_format),
                ctypes.byref(nitems),
                ctypes.byref(bytes_after),
                ctypes.byref(prop),
            )
            if status != X_SUCCESS or not prop.value or nitems.value < 1:
                if prop.value:
                    libx11.XFree(prop)
                return False

            active_win = ctypes.cast(prop, ctypes.POINTER(ctypes.c_ulong))[0]
            libx11.XFree(prop)
            prop = ctypes.c_void_p(0)

            if not active_win:
                return False

            status = libx11.XGetWindowProperty(
                dpy,
                active_win,
                self._atom_wm_state,
                0,
                64,
                0,
                XA_ATOM,
                ctypes.byref(actual_type),
                ctypes.byref(actual_format),
                ctypes.byref(nitems),
                ctypes.byref(bytes_after),
                ctypes.byref(prop),
            )
            libx11.XSync(dpy, 0)
            if status != X_SUCCESS or not prop.value or actual_format.value != 32:
                if prop.value:
                    libx11.XFree(prop)
                return False

            atoms = ctypes.cast(prop, ctypes.POINTER(ctypes.c_ulong))
            is_fs = any(atoms[i] == self._atom_fullscreen for i in range(nitems.value))
            libx11.XFree(prop)
            return is_fs
        except Exception:
            if prop.value:
                libx11.XFree(prop)
            return False
        finally:
            libx11.XSetErrorHandler(prev_handler)

    def _on_x11_io(self, _source, condition) -> bool:
        if not self._dpy or not self._libx11:
            return False
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            self.stop()
            return False

        libx11 = self._libx11
        dpy = self._dpy
        event = XEvent()
        pending_motion = False

        while self._dpy is not None and libx11.XPending(dpy) > 0:
            libx11.XNextEvent(dpy, ctypes.byref(event))
            if event.type != GENERIC_EVENT:
                continue
            cookie = event.xcookie
            if cookie.extension != self._xi_opcode:
                continue

            evtype = cookie.evtype
            if evtype == XI_RAW_MOTION:
                pending_motion = True
                continue

            if evtype not in (XI_RAW_BUTTON_PRESS, XI_RAW_BUTTON_RELEASE):
                continue

            if not libx11.XGetEventData(dpy, ctypes.byref(event.xcookie)):
                continue
            try:
                raw_ptr = ctypes.cast(event.xcookie.data, ctypes.POINTER(XIRawEvent))
                button = raw_ptr.contents.detail
            finally:
                libx11.XFreeEventData(dpy, ctypes.byref(event.xcookie))

            if button not in (1, 2, 3):
                continue

            pos = self.query_pointer()
            if pos is None:
                continue
            rx, ry, mask = pos
            if pending_motion:
                pending_motion = False
                self._on_motion(rx, ry, mask)
                if self._dpy is None:
                    return False

            if evtype == XI_RAW_BUTTON_PRESS:
                self._on_button_press(button, rx, ry)
            elif evtype == XI_RAW_BUTTON_RELEASE:
                self._on_button_release(button, rx, ry)
            if self._dpy is None:
                return False

        if pending_motion and self._dpy is not None:
            pos = self.query_pointer()
            if pos is not None:
                self._on_motion(pos[0], pos[1], pos[2])

        return self._dpy is not None

    def stop(self) -> None:
        if self._io_watch_id is not None:
            GLib.source_remove(self._io_watch_id)
            self._io_watch_id = None
        if self._dbus is not None and self._dbus_sub_id is not None:
            try:
                self._dbus.signal_unsubscribe(self._dbus_sub_id)
            except Exception:
                pass
            self._dbus_sub_id = None
            self._dbus = None
        if self._dpy is not None and self._libx11 is not None:
            try:
                self._libx11.XCloseDisplay(self._dpy)
            except Exception:
                pass
            self._dpy = None
