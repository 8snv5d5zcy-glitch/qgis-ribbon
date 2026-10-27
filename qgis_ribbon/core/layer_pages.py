"""Seiten der QGIS-Layereigenschaften je Layerart (ohne QGIS).

Objektnamen der Seiten wie in QGIS 3.44 (im echten QGIS erhoben). Manche Seiten heißen je Layerart anders
(Beschriftungen: ``mOptsPage_Labels`` bei Vektor und Netz,
``mOptsPage_Labeling`` bei Raster und Vektorkacheln); ``pick`` wählt die
passende. Unbekannte Layerarten (z. B. Punktwolken) bekommen die erste
genannte Seite.
"""

_COMMON = ("mOptsPage_Information", "mOptsPage_Source", "mOptsPage_Style", "mOptsPage_Rendering",
           "mOptsPage_Metadata")
_VECTOR = _COMMON + (
    "mOptsPage_Labels", "mOptsPage_Masks", "mOptsPage_3DView", "mOptsPage_Diagrams", "mOptsPage_SourceFields",
    "mOptsPage_AttributesForm", "mOptsPage_Joins", "mOptsPage_AuxiliaryStorage", "mOptsPage_Actions",
    "mOptsPage_Display", "mOptsPage_Temporal", "mOptsPage_Variables", "mOptsPage_Elevation",
    "mOptsPage_DataDependencies", "mOptsPage_Legend", "mOptsPage_Server", "mOptsPage_Digitizing")

PAGES = {
    "vector": _VECTOR,
    "table": _VECTOR,
    "raster": _COMMON + (
        "mOptsPage_Transparency", "mOptsPage_Labeling", "mOptsPage_Histogram", "mOptsPage_Temporal",
        "mOptsPage_Pyramids", "mOptsPage_Elevation", "mOptsPage_Legend", "mOptsPage_Display",
        "mOptsPage_RasterAttributeTable", "mOptsPage_Server"),
    "mesh": _COMMON + ("mOptsPage_Labels", "mOptsPage_3DView", "mOptsPage_Temporal", "mOptsPage_Elevation"),
    "vector_tile": _COMMON + ("mOptsPage_Labeling", "mOptsPage_Server"),
}


def pick(kind, candidates):
    """Erste der ``candidates``, die die Layerart hat; sonst die erste überhaupt."""
    candidates = [c for c in candidates if c]
    known = PAGES.get(kind)
    if known is not None:
        for page in candidates:
            if page in known:
                return page
    return candidates[0] if candidates else ""


def has_page(kind, page):
    known = PAGES.get(kind)
    return known is None or page in known
