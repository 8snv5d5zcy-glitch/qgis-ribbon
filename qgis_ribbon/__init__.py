def classFactory(iface):
    # Sprache vor dem Import der übrigen Module setzen: Texte auf Modulebene
    # werden beim Import übersetzt (core/i18n.py)
    from qgis.core import QgsApplication

    from .core import i18n

    i18n.set_language(QgsApplication.locale())
    from .plugin import RibbonPlugin

    return RibbonPlugin(iface)
