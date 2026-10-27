"""Seiten der Layereigenschaften je Layerart."""
from qgis_ribbon.core import layer_pages


def test_layer_pages_pick():
    assert layer_pages.pick("raster", ["mOptsPage_Labels", "mOptsPage_Labeling"]) == "mOptsPage_Labeling"
    assert layer_pages.pick("vector", ["mOptsPage_Labels", "mOptsPage_Labeling"]) == "mOptsPage_Labels"
    assert layer_pages.pick("point_cloud", ["mOptsPage_Labels", "mOptsPage_Labeling"]) == "mOptsPage_Labels"
    assert layer_pages.pick("mesh", ["mOptsPage_Pyramids"]) == "mOptsPage_Pyramids"
    assert layer_pages.has_page("raster", "mOptsPage_Pyramids")
    assert not layer_pages.has_page("mesh", "mOptsPage_Pyramids")
