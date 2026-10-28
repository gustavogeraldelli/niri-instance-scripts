"""Read client coordinates for focused XWayland windows."""

import ctypes as C


class X11Pointer:
    def __init__(self, title):
        self.display = None
        self.title = title
        self.window = C.c_ulong()
        self.lib = x = C.CDLL("libX11.so.6")
        P, W, I, U = C.c_void_p, C.c_ulong, C.c_int, C.c_uint
        x.XOpenDisplay.argtypes = [C.c_char_p]
        x.XOpenDisplay.restype = P
        x.XCloseDisplay.argtypes = [P]
        x.XGetInputFocus.argtypes = [P, C.POINTER(W), C.POINTER(I)]
        x.XFetchName.argtypes = [P, W, C.POINTER(P)]
        x.XFree.argtypes = [P]
        x.XGetGeometry.argtypes = [
            P, W, C.POINTER(W), C.POINTER(I), C.POINTER(I),
            C.POINTER(U), C.POINTER(U), C.POINTER(U), C.POINTER(U),
        ]
        x.XQueryPointer.argtypes = [
            P, W, C.POINTER(W), C.POINTER(W), C.POINTER(I),
            C.POINTER(I), C.POINTER(I), C.POINTER(I), C.POINTER(U),
        ]
        self.display = x.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError("não foi possível consultar o cursor no XWayland")
        try:
            self.check_focus()
            root, px, py = W(), I(), I()
            width, height, border, depth = U(), U(), U(), U()
            if not x.XGetGeometry(
                self.display, self.window, C.byref(root), C.byref(px), C.byref(py),
                C.byref(width), C.byref(height), C.byref(border), C.byref(depth),
            ):
                raise RuntimeError("não foi possível medir a janela X11")
            self.width, self.height = width.value, height.value
        except Exception:
            self.close()
            raise

    def check_focus(self):
        window, revert = C.c_ulong(), C.c_int()
        self.lib.XGetInputFocus(self.display, C.byref(window), C.byref(revert))
        if window.value in (0, 1):
            raise RuntimeError("nenhum cliente X11 está focado")
        name = C.c_void_p()
        self.lib.XFetchName(self.display, window, C.byref(name))
        try:
            title = C.string_at(name).decode("utf-8", errors="replace") if name else ""
        finally:
            if name:
                self.lib.XFree(name)
        if title != self.title or (self.window.value and window.value != self.window.value):
            raise RuntimeError("foco X11 não corresponde à janela solicitada")
        self.window = window

    def position(self):
        self.check_focus()
        root, child = C.c_ulong(), C.c_ulong()
        rx, ry, wx, wy, mask = C.c_int(), C.c_int(), C.c_int(), C.c_int(), C.c_uint()
        if not self.lib.XQueryPointer(
            self.display, self.window, C.byref(root), C.byref(child), C.byref(rx),
            C.byref(ry), C.byref(wx), C.byref(wy), C.byref(mask),
        ):
            raise RuntimeError("ponteiro não está na tela esperada")
        return wx.value, wy.value

    def close(self):
        if self.display:
            self.lib.XCloseDisplay(self.display)
            self.display = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def aim(pointer, target, move, sleep, check):
    """Correct small relative moves until the measured position reaches the target."""
    x, y = target
    if not (0 <= x < pointer.width and 0 <= y < pointer.height):
        raise RuntimeError("alvo fora da janela; clique cancelado")
    for _ in range(14):
        check()
        px, py = pointer.position()
        if not (0 <= px < pointer.width and 0 <= py < pointer.height):
            raise RuntimeError("cursor saiu da janela; clique cancelado")
        dx, dy = x - px, y - py
        if abs(dx) <= 1 and abs(dy) <= 1:
            return
        move(max(-40, min(40, dx)), max(-40, min(40, dy)))
        sleep(0.04)
    raise RuntimeError("cursor não atingiu o alvo; clique cancelado")
