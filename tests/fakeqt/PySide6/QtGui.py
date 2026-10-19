from unittest.mock import MagicMock
from ._base import QPoint, QRect, _Anything

class QColor:
    def __init__(self, *a): self.a = a; self._alpha = 255
    def setAlpha(self, v): self._alpha = v
    def alpha(self): return self._alpha

class QFont:
    def __init__(self, other=None):
        self._px = getattr(other, "_px", 12); self._bold = False; self._fam = ["Fake"]
    def setPixelSize(self, v): assert isinstance(v, int), v; self._px = v
    def pixelSize(self): return self._px
    def pointSizeF(self): return 9.0
    def setPointSizeF(self, v): pass
    def setBold(self, b): self._bold = b
    def setFamilies(self, f): self._fam = f
    def family(self): return self._fam[0]
    def families(self): return list(self._fam)

class QFontMetricsF:
    def __init__(self, f): self.px = f.pixelSize()
    def horizontalAdvance(self, t): return 0.5 * self.px * len(t)
    def ascent(self): return 0.8 * self.px
    def descent(self): return 0.25 * self.px
    def height(self): return 1.05 * self.px
    def elidedText(self, t, mode, w): return t
    def xHeight(self): return 0.5 * self.px
QFontMetrics = QFontMetricsF

class _Screen:
    def __init__(self, r): self.r = r
    def availableGeometry(self): return self.r
    def geometry(self): return self.r

class QGuiApplication:
    _screens = [_Screen(QRect(0, 0, 1920, 1040))]
    @staticmethod
    def primaryScreen(): return QGuiApplication._screens[0]
    @staticmethod
    def screens(): return QGuiApplication._screens
    @staticmethod
    def screenAt(p):
        for s in QGuiApplication._screens:
            r = s.r
            if r.left() <= p.x() <= r.right() and r.top() <= p.y() <= r.bottom(): return s
        return None

class QCursor:
    _pos = QPoint(5, 5)
    @staticmethod
    def pos(): return QCursor._pos
    @staticmethod
    def setPos(p): QCursor._pos = p

class QPixmap(_Anything):
    def __init__(self, *a): pass
    def isNull(self): return True

class _M(MagicMock): pass
QPainter = MagicMock(name="QPainter")
QPainterPath = MagicMock(name="QPainterPath")
QPen = MagicMock(name="QPen")
QRegion = MagicMock(name="QRegion")
QTransform = MagicMock(name="QTransform")
QPolygonF = MagicMock(name="QPolygonF")
QIcon = MagicMock(name="QIcon")
QAction = MagicMock(name="QAction")
QActionGroup = MagicMock(name="QActionGroup")
QFontDatabase = MagicMock(name="QFontDatabase")
class QPalette:
    Window, PlaceholderText = 1, 2
QImage = MagicMock(name="QImage")


def __getattr__(name):
    from unittest.mock import MagicMock
    if name.startswith("__"): raise AttributeError(name)
    return type(name, (object,), {"__init__": lambda self, *a, **k: None})
