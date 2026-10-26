"""Operationen der eigenen Befehle auf Rasterlayern (ohne Widgets).

Wie ``layer_ops``: jede Änderung setzt die QGIS-Eigenschaft, die auch die
Layereigenschaften bzw. das Bedienfeld Layergestaltung setzen, und meldet sie
wie QGIS (neu zeichnen, ``styleChanged``, Projekt geändert).

Rasterlayer mit Farbdaten (WMS, XYZ, WMTS: Datentyp ARGB) haben genau eine
sinnvolle Darstellung; für sie bietet der Ribbon keine Darstellungsarten und
keine Kanalkombinationen an.
"""

from qgis.core import (Qgis, QgsBilinearRasterResampler, QgsCubicRasterResampler,
                       QgsHillshadeRenderer, QgsMultiBandColorRenderer,
                       QgsRasterContourRenderer, QgsRasterLayer, QgsRasterRendererRegistry,
                       QgsSingleBandPseudoColorRenderer, QgsStyle)

from .layer_ops import changed
from ..core.i18n import tr

# Wertebereiche wie im Bedienfeld Layergestaltung
BRIGHTNESS_RANGE = (-255, 255)
CONTRAST_RANGE = (-100, 100)
GAMMA_RANGE = (0.1, 10.0)

# Darstellungsart (QGIS-Renderer-Typ) -> Beschriftung; Mehrkanal nur ab 2 Kanälen
RENDERERS = (
    ("multibandcolor", tr("Multiband color")),
    ("singlebandgray", tr("Singleband gray")),
    ("singlebandpseudocolor", tr("Singleband pseudocolor")),
    ("hillshade", tr("Hillshade")),
    ("contour", tr("Contours")),
)
PSEUDOCOLOR_RAMPS = ("Spectral", "Viridis")
STATS_SAMPLE = 250000
# Wertebereich der Pseudofarben wie QGIS-Standard: kumulativer Schnitt 2–98 %
CUMULATIVE_CUT = (0.02, 0.98)

# Resampling (wie in den Layereigenschaften, Seite Symbolisierung)
RESAMPLING = (
    ("nearest", tr("Nearest neighbor")),
    ("bilinear", tr("Bilinear")),
    ("cubic", tr("Cubic")),
)
_PROVIDER_METHODS = {
    "nearest": "Nearest", "bilinear": tr("Bilinear"), "cubic": "Cubic",
}


def is_raster(layer):
    return isinstance(layer, QgsRasterLayer) and layer.isValid()


def is_color_data(layer):
    """Farbdaten (WMS, XYZ ...): nur eine sinnvolle Darstellung."""
    if not is_raster(layer):
        return False
    return layer.dataProvider().dataType(1) in (Qgis.DataType.ARGB32,
                                                Qgis.DataType.ARGB32_Premultiplied)


# -- Helligkeit, Kontrast, Gamma ---------------------------------------------

def enhancement(layer):
    """(Helligkeit, Kontrast, Gamma) des Rasterlayers."""
    f = layer.brightnessFilter()
    return f.brightness(), f.contrast(), f.gamma()


def _clamp(value, bounds):
    return max(bounds[0], min(bounds[1], value))


def set_brightness(layer, value):
    layer.brightnessFilter().setBrightness(int(_clamp(round(value), BRIGHTNESS_RANGE)))
    changed(layer)


def set_contrast(layer, value):
    layer.brightnessFilter().setContrast(int(_clamp(round(value), CONTRAST_RANGE)))
    changed(layer)


def set_gamma(layer, value):
    layer.brightnessFilter().setGamma(float(_clamp(value, GAMMA_RANGE)))
    changed(layer)


# -- Darstellungsart -----------------------------------------------------------

def renderer_type(layer):
    if not is_raster(layer) or layer.renderer() is None:
        return None
    return layer.renderer().type()


def renderer_choices(layer):
    """[(Typ, Beschriftung)] für den Layer; leer bei Farbdaten."""
    if not is_raster(layer) or is_color_data(layer):
        return []
    multi = layer.bandCount() >= 2
    return [(t, label) for t, label in RENDERERS if multi or t != "multibandcolor"]


def _style_ramp():
    style = QgsStyle.defaultStyle()
    for name in PSEUDOCOLOR_RAMPS:
        ramp = style.colorRamp(name)
        if ramp is not None:
            return ramp
    return None


def _pseudocolor(layer, band):
    provider = layer.dataProvider()
    low, high = provider.cumulativeCut(band, CUMULATIVE_CUT[0], CUMULATIVE_CUT[1], layer.extent(),
                                       STATS_SAMPLE)
    renderer = QgsSingleBandPseudoColorRenderer(provider, band)
    renderer.setClassificationMin(low)
    renderer.setClassificationMax(high)
    ramp = _style_ramp()
    if ramp is not None:
        renderer.createShader(ramp, Qgis.ShaderInterpolationMethod.Linear,
                              Qgis.ShaderClassificationMethod.Continuous, 5)
    return renderer


def set_renderer(layer, name):
    """Darstellungsart wechseln; Kanal 1 bzw. bisheriger Kanal, Streckung wie QGIS-Standard."""
    if renderer_type(layer) == name:
        return False
    provider = layer.dataProvider()
    old = layer.renderer()
    bands = old.usesBands() if old is not None else []
    band = bands[0] if bands else 1
    registry = QgsRasterRendererRegistry()
    stretch = False
    if name == "multibandcolor":
        renderer = registry.defaultRendererForDrawingStyle(Qgis.RasterDrawingStyle.MultiBandColor,
                                                           provider)
        stretch = True
    elif name == "singlebandgray":
        renderer = registry.defaultRendererForDrawingStyle(Qgis.RasterDrawingStyle.SingleBandGray,
                                                           provider)
        renderer.setInputBand(band)
        stretch = True
    elif name == "singlebandpseudocolor":
        renderer = _pseudocolor(layer, band)
    elif name == "hillshade":
        renderer = QgsHillshadeRenderer(provider, band, 315.0, 45.0)
    elif name == "contour":
        renderer = QgsRasterContourRenderer(provider)
        renderer.setInputBand(band)
    else:
        raise ValueError(tr("Unknown renderer: %s") % name)
    if renderer is None:
        return False
    layer.setRenderer(renderer)
    if stretch:
        layer.setDefaultContrastEnhancement()
    changed(layer)
    return True


# -- Kanalkombination ------------------------------------------------------------

def band_combinations(layer):
    """[(Beschriftung, (R, G, B), Abschnitt)] für Mehrkanal-Raster; leer sonst.

    Vorlagen nach üblicher Kanalfolge (1 Rot, 2 Grün, 3 Blau, 4 Nahes Infrarot
    wie bei Digitalen Orthophotos); dazu jede Folge dreier Nachbarkanäle.
    """
    if not is_raster(layer) or is_color_data(layer):
        return []
    n = layer.bandCount()
    if n < 3:
        return []
    out = [(tr("Natural color (1-2-3)"), (1, 2, 3), tr("Presets"))]
    if n >= 4:
        out.append((tr("Color infrared (4-1-2)"), (4, 1, 2), tr("Presets")))
    out.append((tr("Reversed (3-2-1)"), (3, 2, 1), tr("Presets")))
    for start in range(1, n - 1):
        combo = (start, start + 1, start + 2)
        if combo != (1, 2, 3):
            out.append((tr("Bands %d-%d-%d") % combo, combo, tr("More")))
    return out


def current_bands(layer):
    r = layer.renderer() if is_raster(layer) else None
    if isinstance(r, QgsMultiBandColorRenderer):
        return r.redBand(), r.greenBand(), r.blueBand()
    return None


def band_name(layer, band):
    return layer.dataProvider().displayBandName(band) or tr("Band %d") % band


def set_bands(layer, bands):
    """Mehrkanalfarbe mit den Kanälen (R, G, B); Streckung neu wie QGIS-Standard."""
    red, green, blue = bands
    renderer = layer.renderer()
    if isinstance(renderer, QgsMultiBandColorRenderer):
        renderer = renderer.clone()
        renderer.setRedBand(red)
        renderer.setGreenBand(green)
        renderer.setBlueBand(blue)
    else:
        renderer = QgsMultiBandColorRenderer(layer.dataProvider(), red, green, blue)
    layer.setRenderer(renderer)
    layer.setDefaultContrastEnhancement()
    changed(layer)


# -- Resampling --------------------------------------------------------------------

def _resampler_name(resampler):
    return resampler.type() if resampler is not None else "nearest"


def resampling(layer):
    """Methode beim Hineinzoomen (``nearest``, ``bilinear``, ``cubic`` oder QGIS-Name)."""
    if layer.resamplingStage() == Qgis.RasterResamplingStage.Provider:
        method = layer.dataProvider().zoomedInResamplingMethod()
        for name, enum_name in _PROVIDER_METHODS.items():
            if method == getattr(layer.dataProvider().ResamplingMethod, enum_name):
                return name
        return "other"
    return _resampler_name(layer.resampleFilter().zoomedInResampler())


def set_resampling(layer, name):
    """Gleiche Methode beim Hinein- und Herauszoomen (wie Pro)."""
    if name not in _PROVIDER_METHODS:
        raise ValueError(tr("Unknown resampling: %s") % name)
    if layer.resamplingStage() == Qgis.RasterResamplingStage.Provider:
        provider = layer.dataProvider()
        method = getattr(provider.ResamplingMethod, _PROVIDER_METHODS[name])
        provider.setZoomedInResamplingMethod(method)
        provider.setZoomedOutResamplingMethod(method)
    else:
        rf = layer.resampleFilter()
        rf.setZoomedInResampler(_new_resampler(name))
        rf.setZoomedOutResampler(_new_resampler(name))
    changed(layer)


def _new_resampler(name):
    if name == "bilinear":
        return QgsBilinearRasterResampler()
    if name == "cubic":
        return QgsCubicRasterResampler()
    return None
