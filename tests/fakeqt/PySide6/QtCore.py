from ._base import Qt, Signal, QObject, QPoint, QPointF, QRect, QRectF, QTimer, QEvent, QUrl


def __getattr__(name):
    from unittest.mock import MagicMock
    if name.startswith("__"): raise AttributeError(name)
    return type(name, (object,), {"__init__": lambda self, *a, **k: None})
