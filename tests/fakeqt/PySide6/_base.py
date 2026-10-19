"""假的 PySide6：只夠跑狀態機和版面計算（畫面不會真的畫）。"""
from unittest.mock import MagicMock
import itertools

_ids = itertools.count(1)

class _QtNS:
    def __getattr__(self, name):
        v = 1 << (next(_ids) % 60)
        setattr(self, name, v)
        return v
Qt = _QtNS()

class _Bound:
    def __init__(self): self.slots = []
    def connect(self, fn): self.slots.append(fn)
    def disconnect(self, *a): self.slots.clear()
    def emit(self, *a):
        for f in list(self.slots): f(*a)
    def __call__(self, *a): self.emit(*a)

class Signal:
    def __init__(self, *types): self.name = None
    def __set_name__(self, owner, name): self.name = "_sig_" + name
    def __get__(self, obj, owner=None):
        if obj is None: return self
        b = obj.__dict__.get(self.name)
        if b is None:
            b = obj.__dict__[self.name] = _Bound()
        return b

class _Anything:
    """未知的方法：什麼都不做，回傳 MagicMock。"""
    def __getattr__(self, name):
        if name.startswith("__"): raise AttributeError(name)
        m = MagicMock(name=name)
        return m

class QObject(_Anything):
    def __init__(self, *a, **k): pass

class QPoint:
    def __init__(self, x=0, y=0): self._x, self._y = int(x), int(y)
    def x(self): return self._x
    def y(self): return self._y
    def __sub__(self, o): return QPoint(self._x - o.x(), self._y - o.y())
    def __add__(self, o): return QPoint(self._x + o.x(), self._y + o.y())
    def manhattanLength(self): return abs(self._x) + abs(self._y)
    def toPoint(self): return self
    def __repr__(self): return f"QPoint({self._x},{self._y})"

class QPointF(QPoint):
    def __init__(self, x=0.0, y=0.0):
        if isinstance(x, QPoint): x, y = x.x(), x.y()
        self._x, self._y = float(x), float(y)
    def __sub__(self, o): return QPointF(self._x - o.x(), self._y - o.y())
    def toPoint(self): return QPoint(round(self._x), round(self._y))

class QRect:
    def __init__(self, x=0, y=0, w=0, h=0): self._x, self._y, self._w, self._h = x, y, w, h
    def x(self): return self._x
    def y(self): return self._y
    def left(self): return self._x
    def top(self): return self._y
    def width(self): return self._w
    def height(self): return self._h
    def right(self): return self._x + self._w - 1
    def bottom(self): return self._y + self._h - 1
    def center(self): return QPoint(self._x + self._w // 2, self._y + self._h // 2)
    def isEmpty(self): return self._w <= 0 or self._h <= 0

class QRectF:
    def __init__(self, *a):
        if len(a) == 1:
            r = a[0]; a = (r.x(), r.y(), r.width(), r.height())
        elif len(a) == 0:
            a = (0, 0, 0, 0)
        self._x, self._y, self._w, self._h = (float(v) for v in a)
    def x(self): return self._x
    def y(self): return self._y
    def left(self): return self._x
    def top(self): return self._y
    def width(self): return self._w
    def height(self): return self._h
    def right(self): return self._x + self._w
    def bottom(self): return self._y + self._h
    def center(self): return QPointF(self._x + self._w / 2, self._y + self._h / 2)
    def contains(self, p): return self._x <= p.x() <= self.right() and self._y <= p.y() <= self.bottom()
    def adjusted(self, a, b, c, d): return QRectF(self._x + a, self._y + b, self._w - a + c, self._h - b + d)
    def translated(self, dx, dy): return QRectF(self._x + dx, self._y + dy, self._w, self._h)
    def isEmpty(self): return self._w <= 0 or self._h <= 0
    def __repr__(self): return f"QRectF({self._x:.1f},{self._y:.1f},{self._w:.1f},{self._h:.1f})"

class QTimer(QObject):
    timeout = Signal()
    pending = []
    def __init__(self, *a):
        self._active = False; self._interval = 0; self._single = False
    def start(self, ms=None):
        if ms is not None: self._interval = ms
        self._active = True
    def stop(self): self._active = False
    def isActive(self): return self._active
    def setInterval(self, ms): self._interval = ms
    def interval(self): return self._interval
    def setSingleShot(self, b): self._single = b
    @staticmethod
    def singleShot(ms, fn): QTimer.pending.append((ms, fn))

class QEvent:
    FocusIn, FocusOut, KeyPress, MouseButtonPress = 8, 9, 6, 2

class QUrl:
    @staticmethod
    def fromLocalFile(p): return p
