from unittest.mock import MagicMock
from ._base import Signal, _Anything, QRect
from .QtGui import QFont

class QApplication:
    _font = QFont()
    @staticmethod
    def font(): return QApplication._font
    @staticmethod
    def doubleClickInterval(): return 400

class QWidget(_Anything):
    def __init__(self, parent=None, flags=None, *a):
        self._g = [0, 0, 100, 100]; self._vis = False; self.raised = 0
    def move(self, x, y): self._g[0], self._g[1] = int(x), int(y); self.moveEvent(None)
    def moveEvent(self, e): pass
    def x(self): return self._g[0]
    def y(self): return self._g[1]
    def width(self): return self._g[2]
    def height(self): return self._g[3]
    def resize(self, w, h): self._g[2], self._g[3] = int(w), int(h)
    def setFixedSize(self, w, h): self.resize(w, h)
    def setGeometry(self, x, y, w, h): self._g = [int(x), int(y), int(w), int(h)]; self.moveEvent(None)
    def geometry(self): return QRect(*self._g)
    def show(self): self._vis = True
    def hide(self): self._vis = False; self.hideEvent(None)
    def hideEvent(self, e): pass
    def isVisible(self): return self._vis
    def raise_(self): self.raised += 1
    def update(self, *a): pass
    def palette(self): return MagicMock()

class QLineEdit(QWidget):
    returnPressed = Signal()
    def __init__(self, *a): super().__init__(); self._t = ""; self._f = False
    def text(self): return self._t
    def setText(self, t): self._t = t
    def clear(self): self._t = ""
    def hasFocus(self): return self._f
    def setFocus(self): self._f = True
    def clearFocus(self): self._f = False

class QDialog(QWidget):
    def exec(self): return 0
    def accept(self): pass
    def reject(self): pass

class _Item:
    def __init__(self, w=None, l=None): self._w, self._l = w, l
    def widget(self): return self._w
    def layout(self): return self._l

class _Layout(_Anything):
    def __init__(self, *a): self._items = []
    def addWidget(self, w, *a): self._items.append(_Item(w=w))
    def addLayout(self, l, *a): self._items.append(_Item(l=l))
    def addStretch(self, *a): self._items.append(_Item())
    def count(self): return len(self._items)
    def takeAt(self, i): return self._items.pop(i)

QHBoxLayout = _Layout
QVBoxLayout = _Layout
QFormLayout = MagicMock(name="QFormLayout")
QDialogButtonBox = MagicMock(name="QDialogButtonBox")
QLabel = MagicMock(name="QLabel")
QComboBox = MagicMock(name="QComboBox")
QSpinBox = MagicMock(name="QSpinBox")
QMenu = MagicMock(name="QMenu")
QSystemTrayIcon = MagicMock(name="QSystemTrayIcon")
QInputDialog = MagicMock(name="QInputDialog")
QMessageBox = MagicMock(name="QMessageBox")
QPushButton = MagicMock(name="QPushButton")
QTextBrowser = MagicMock(name="QTextBrowser")


def __getattr__(name):
    from unittest.mock import MagicMock
    if name.startswith("__"): raise AttributeError(name)
    return type(name, (object,), {"__init__": lambda self, *a, **k: None})
