
from qgis.core import (
    QgsProject,
    QgsCategorizedSymbolRenderer,
    QgsRendererCategory,
    QgsFillSymbol
)

# Szukamy warstwy H3 r9 otwartej w QGIS
project = QgsProject.instance()

layers = [
    layer for layer in project.mapLayers().values()
    if "h3_przejezdnosc_r9" in layer.name()
    and layer.isValid()
]

if not layers:
    raise RuntimeError(
        "Najpierw dodaj do QGIS warstwe h3_przejezdnosc_r9"
    )

layer = layers[0]

if layer.fields().indexFromName("klasa_przejezdnosci") == -1:
    raise RuntimeError("Brak kolumny klasa_przejezdnosci")

# Kolory i opisy klas
klasy = [
    (1, "#c63131", "Nieprzejezdny (-1 do -0,333)"),
    (2, "#ffffff", "Sredni (-0,333 do +0,333)"),
    (3, "#238b45", "Przejezdny (+0,333 do +1)")
]

kategorie = []

for numer, kolor, opis in klasy:
    symbol = QgsFillSymbol.createSimple({
        "color": kolor,
        "outline_color": "#666666",
        "outline_width": "0.08",
        "outline_width_unit": "MM"
    })

    kategorie.append(
        QgsRendererCategory(numer, symbol, opis)
    )

renderer = QgsCategorizedSymbolRenderer(
    "klasa_przejezdnosci",
    kategorie
)

layer.setRenderer(renderer)
layer.triggerRepaint()

iface.layerTreeView().refreshLayerSymbology(layer.id())
iface.setActiveLayer(layer)
iface.mapCanvas().setExtent(layer.extent())
iface.mapCanvas().refresh()

print("GOTOWE: H3 r9 pokolorowane automatycznie!")
