"""SignalHub: Trennen beim Entladen, auch wenn C++ den Sender schon gelöscht hat; fremde Wrapper festhalten."""
import gc
import weakref
from functools import partial

from qgis.PyQt import sip
from qgis.PyQt.QtWidgets import QAction, QMainWindow, QMenu, QToolBar

from qgis_ribbon.qgis_integration.signals import SignalHub, keep_foreign_wrappers, keep_wrappers_from, kept_wrappers


def test_disconnect_all_separates_live_senders():
    hub, calls = SignalHub(), []
    action = QAction("a")
    hub.connect(action, "changed", lambda: calls.append(1))
    action.setText("b")
    hub.disconnect_all()
    action.setText("c")
    assert calls == [1] and len(hub) == 0


def test_disconnect_all_skips_senders_deleted_by_cpp():
    # Wie eine Aktion eines C++-Plugins, das QGIS beim Beenden vor dem Ribbon
    # entlädt: QMenu.clear() löscht die Aktion in C++. Ein disconnect darauf
    # stürzte ab (Zugriffsverletzung) statt eine Ausnahme zu werfen.
    hub = SignalHub()
    menu = QMenu()
    action = menu.addAction("x")
    hub.connect(action, "changed", lambda: None)
    hub.connect(menu, "aboutToShow", lambda: None)
    menu.clear()
    hub.disconnect_all()
    assert len(hub) == 0


def _foreign_action(window):
    """Aktion, die C++ erzeugt hat und deren Wrapper niemand festhält (wie die Aktionen von QGIS)."""
    return window.findChild(QToolBar, "fremd").toggleViewAction()


def test_kept_wrappers_protect_slots_of_others_from_garbage_collection():
    # Gemeldet von Paul (QGIS 3.44.14): Klick auf „Bearbeiten“ stürzte ab. Das Plugin
    # Verarbeitung hängt ein partial an mActionToggleEditing.triggered. Hält nur noch
    # ein Zyklus des abgebauten Ribbons den Wrapper der Aktion, gibt die
    # Speicherbereinigung mit ihm das partial frei; das nächste triggered stürzt ab.
    window = QMainWindow()
    window.addToolBar("fremd").setObjectName("fremd")
    calls = []
    slot = partial(calls.append, "fremd")       # Slot eines anderen Plugins
    _foreign_action(window).triggered.connect(slot)
    alive = weakref.ref(slot)
    del slot
    assert not sip.ispycreated(_foreign_action(window))

    class Rest(object):                          # Rest des Ribbons: Zyklus mit dem Wrapper
        pass

    rest = Rest()
    rest.me = rest
    rest.action = _foreign_action(window)
    keep_foreign_wrappers()
    assert any(obj is rest.action for obj in kept_wrappers().values())
    del rest
    gc.collect()
    assert alive() is not None and alive().func is not None
    _foreign_action(window).trigger()
    assert calls == ["fremd"]


def test_keep_foreign_wrappers_leaves_own_objects_and_drops_deleted_ones():
    window = QMainWindow()
    window.addToolBar("fremd").setObjectName("fremd")
    foreign = _foreign_action(window)
    own = QAction("eigen", window)
    keep_foreign_wrappers()
    kept = kept_wrappers()
    assert id(foreign) in kept and id(own) not in kept and id(window) not in kept
    key = id(foreign)
    sip.delete(window)                           # C++ löscht Leiste und Aktion mit
    assert sip.isdeleted(foreign)
    keep_foreign_wrappers()
    assert key not in kept_wrappers()


def test_keep_wrappers_from_finds_wrappers_reachable_from_the_ribbon():
    """Leichter Weg beim Neuaufbau: Wrapper in Attributen, Closures, partials und eigenen Qt-Objekten."""
    window = QMainWindow()
    for name in ("a", "b", "c", "d"):
        window.addToolBar(name).setObjectName(name)

    def foreign(name):
        return window.findChild(QToolBar, name).toggleViewAction()

    class Rest(object):
        pass

    rest = Rest()
    rest.me = rest
    rest.items = {"x": [foreign("a")]}
    held = foreign("b")
    rest.slot = lambda: held.text()            # Closure
    rest.call = partial(print, foreign("c"))
    own = QAction("eigen")                      # eigenes Qt-Objekt mit fremdem Wrapper im Attribut
    own.target = foreign("d")
    rest.own = own
    kept = kept_wrappers()
    for key in [k for k, o in kept.items() if o in [foreign(n) for n in "abcd"]]:
        del kept[key]
    keep_wrappers_from([rest])
    for name in "abcd":
        assert any(obj is foreign(name) for obj in kept_wrappers().values()), name
    assert not any(obj is own for obj in kept_wrappers().values())


def test_keep_wrappers_from_protects_slots_like_the_full_walk():
    window = QMainWindow()
    window.addToolBar("fremd").setObjectName("fremd")
    calls = []
    slot = partial(calls.append, "fremd")
    _foreign_action(window).triggered.connect(slot)
    del slot

    class Rest(object):
        pass

    rest = Rest()
    rest.me = rest
    rest.action = _foreign_action(window)
    keep_wrappers_from([rest])
    del rest
    gc.collect()
    _foreign_action(window).trigger()
    assert calls == ["fremd"]


class _UnhashableMeta(type):
    """Metaklasse ohne Hash, wie sie manche Pakete für Proxy-Typen verwenden."""

    def __eq__(cls, other):
        return cls is other

    __hash__ = None


class _Proxy(metaclass=_UnhashableMeta):
    pass


def test_keep_foreign_wrappers_skips_types_without_hash():
    proxy = _Proxy()
    assert keep_foreign_wrappers() >= 0
    del proxy


def test_keep_wrappers_from_skips_types_without_hash():
    class Rest(object):
        pass

    rest = Rest()
    rest.proxy = _Proxy()
    assert keep_wrappers_from([rest]) >= 0
