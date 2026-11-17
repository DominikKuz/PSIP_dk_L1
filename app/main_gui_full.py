"""PSIP: samodzielny interfejs PyQGIS 3.x + Qt (uruchamiaj python-qgis-ltr.bat).
Bez ingerencji w app/main_gui.py. Uzywa obecnych logowanie.py i motywy.py.
"""
import json
import math
import subprocess
import sys
from pathlib import Path

from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal, QTimer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSlider,
    QSplitter, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsDataSourceUri, QgsDistanceArea, QgsFeature, QgsFeatureRequest,
    QgsFillSymbol, QgsGeometry, QgsGraduatedSymbolRenderer, QgsLayoutExporter,
    QgsLayoutItemMap, QgsLayoutSize, QgsLayoutPoint, QgsMarkerSymbol, QgsPointXY, QgsPrintLayout,
    QgsProject, QgsRendererCategory, QgsRendererRange,
    QgsCategorizedSymbolRenderer, QgsVectorLayer, QgsWkbTypes,
    QgsLayerTreeModel,
)
from qgis.gui import (
    QgsLayerTreeMapCanvasBridge, QgsLayerTreeView, QgsMapCanvas,
    QgsMapToolEmitPoint, QgsMapToolPan, QgsRubberBand,
)
from logowanie import OknoLogowania
from motywy import JASNY, CIEMNY

QGIS_PREFIX = r"D:\QGis_2026\apps\qgis-ltr"
ROOT = Path(__file__).resolve().parent.parent
WEIGHTS_FILE = ROOT / "app" / "wagi_przejezdnosci.json"
LOCAL_GPKG = ROOT / "data" / "hexagons_torun_z_miastem.gpkg"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
CRS = QgsCoordinateReferenceSystem("EPSG:2180")
COLORS = ["#c63131", "#ffffff", "#238b45"]


class Obliczenia(QThread):
    message = pyqtSignal(str)
    completed = pyqtSignal(bool, str)

    def __init__(self, password, parent=None):
        super().__init__(parent)
        self.password = password

    def run(self):
        tasks = [
            ("H3 r7", ["normalizuj_przejezdnosc.py", "--resolution", "7", "--no-map"]),
            ("H3 r8", ["normalizuj_przejezdnosc.py", "--resolution", "8", "--no-map"]),
            ("H3 r9", ["normalizuj_przejezdnosc.py", "--resolution", "9", "--no-map"]),
            ("Normalizacja wspolna", ["normalizacja_koncowa_iop.py"]),
        ]
        try:
            if not VENV_PY.is_file():
                raise RuntimeError(f"Nie znaleziono Pythona projektu: {VENV_PY}")
            for label, args in tasks:
                self.message.emit(f"Start: {label}")
                command = [str(VENV_PY), str(ROOT / "app" / "run_psip_job.py"),
                           str(ROOT / "app" / args[0])] + args[1:]
                result = subprocess.run(
                    command, input=self.password + "\n", text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    cwd=str(ROOT), timeout=3600,
                )
                if result.returncode:
                    raise RuntimeError(f"{label} - blad:\n{result.stdout[-3500:]}")
                self.message.emit(f"Zakonczono: {label}\n{result.stdout[-800:]}")
            self.completed.emit(True, "Wszystkie 4 etapy obliczen zakonczone.")
        except Exception as exc:
            self.completed.emit(False, str(exc))
        finally:
            self.password = ""


class PSIPWindow(QMainWindow):
    def __init__(self, on_logout):
        super().__init__()
        self.on_logout = on_logout
        self.logging_out = False
        self.dark = False
        self.db_password = None
        self.h3_layers = {}
        self.point_layer = None
        self.measure_start = None
        self.measure_band = None
        self.worker = None
        self.weight_controls = {}
        self.weight_doc = None
        self.weight_map = {}
        self.current_colors = COLORS.copy()
        self.setWindowTitle("PSIP | Analiza przejezdnosci terenu")
        self.resize(1500, 900)
        self.setStyleSheet(JASNY)
        self.build_ui()
        QTimer.singleShot(150, self.connect_db)

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 5)
        title = QLabel("PSIP  |  ANALIZA PRZEJEZDNOSCI TERENU")
        title.setStyleSheet("font-size:19px; font-weight:700")
        outer.addWidget(title)

        actions = QHBoxLayout()
        items = [
            ("PostGIS", self.connect_db), ("Wczytaj SHP", self.add_shp),
            ("Dodaj punkty", self.start_points), ("Pomiar 2 pkt", self.start_measure),
            ("Przesuwaj", self.pan), ("Zoom do obiektu", self.zoom_selected),
            ("Eksport PDF", self.export_pdf), ("Motyw", self.toggle_theme),
            ("Wyloguj", self.logout),
        ]
        for name, handler in items:
            btn = QPushButton(name)
            btn.clicked.connect(handler)
            actions.addWidget(btn)
        outer.addLayout(actions)

        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter, 1)

        # Panel lewy: hierarchia + legenda (z rzeczywistych styli warstw).
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("WARSTWY I LEGENDA"))
        left_layout.addWidget(QLabel("Widocznosc warstw zmienisz checkboxami."))
        self.resolution = QComboBox()
        self.resolution.addItems(["H3 r7", "H3 r8", "H3 r9"])
        self.resolution.setCurrentIndex(2)
        self.resolution.currentIndexChanged.connect(self.change_resolution)
        left_layout.addWidget(self.resolution)

        root = QgsProject.instance().layerTreeRoot()
        self.tree_model = QgsLayerTreeModel(root, self)
        self.tree_model.setFlag(QgsLayerTreeModel.ShowLegend, True)
        self.tree_model.setFlag(QgsLayerTreeModel.ShowLegendAsTree, True)
        self.tree = QgsLayerTreeView()
        self.tree.setModel(self.tree_model)
        left_layout.addWidget(self.tree, 1)
        splitter.addWidget(left)

        # Prawdziwy canvas mapowy.
        self.canvas = QgsMapCanvas()
        self.canvas.setDestinationCrs(CRS)
        self.canvas.setCanvasColor(QColor("#ffffff"))
        self.pan_tool = QgsMapToolPan(self.canvas)
        self.click_tool = QgsMapToolEmitPoint(self.canvas)
        self.click_tool.canvasClicked.connect(self.map_clicked)
        self.mode = "pan"
        self.canvas.setMapTool(self.pan_tool)
        self.canvas.xyCoordinates.connect(self.coords_changed)
        self.canvas.scaleChanged.connect(self.scale_changed)
        self.bridge = QgsLayerTreeMapCanvasBridge(root, self.canvas)
        self.bridge.setAutoSetupOnFirstLayer(False)
        splitter.addWidget(self.canvas)

        # Prawy panel: wyszukiwanie, styl i wagi.
        tabs = QTabWidget()
        tabs.addTab(self.make_search_panel(), "Wyszukaj")
        tabs.addTab(self.make_style_panel(), "Styl")
        tabs.addTab(self.make_weights_panel(), "Wagi")
        splitter.addWidget(tabs)
        splitter.setSizes([295, 840, 350])

        self.coordinates = QLabel("X: --   Y: -- (EPSG:2180)")
        self.map_scale = QLabel("Skala: --")
        self.statusBar().addPermanentWidget(self.coordinates)
        self.statusBar().addPermanentWidget(self.map_scale)
        self.statusBar().showMessage("Mapa gotowa")

    def make_search_panel(self):
        panel = QWidget()
        f = QFormLayout(panel)
        self.search_layer = QComboBox()
        self.search_field = QComboBox()
        self.search_op = QComboBox()
        self.search_op.addItems(["=", "zawiera", ">", "<"])
        self.search_value = QLineEdit()
        self.search_layer.currentIndexChanged.connect(self.update_fields)
        f.addRow("Warstwa", self.search_layer)
        f.addRow("Atrybut", self.search_field)
        f.addRow("Operator", self.search_op)
        f.addRow("Wartosc", self.search_value)
        btn = QPushButton("Wyszukaj i zaznacz")
        btn.clicked.connect(self.search_features)
        f.addRow(btn)
        hint = QLabel("Wyniki zostana zaznaczone na mapie.\n"
                      "Zoom do obiektu: pierwszy znaleziony\n"
                      "lub pierwszy zaznaczony element.")
        hint.setWordWrap(True)
        f.addRow(hint)
        return panel

    def make_style_panel(self):
        panel = QWidget()
        f = QFormLayout(panel)
        self.lower = QDoubleSpinBox()
        self.upper = QDoubleSpinBox()
        for widget in (self.lower, self.upper):
            widget.setRange(-1, 1)
            widget.setDecimals(3)
            widget.setSingleStep(0.05)
        self.lower.setValue(-0.333)
        self.upper.setValue(0.333)
        f.addRow("Granica niska/srednia", self.lower)
        f.addRow("Granica srednia/wysoka", self.upper)
        self.color_buttons = []
        for idx, name in enumerate(("Niska", "Srednia", "Wysoka")):
            btn = QPushButton(name + " - wybierz kolor")
            btn.clicked.connect(lambda _, i=idx: self.pick_color(i))
            self.color_buttons.append(btn)
            f.addRow(btn)
        apply_btn = QPushButton("Zastosuj styl")
        apply_btn.clicked.connect(self.apply_style)
        f.addRow(apply_btn)
        f.addRow(QLabel("Styl modyfikuje tylko wyswietlanie.\n"
                        "Nie zmienia wsp_iop_norm w bazie."))
        return panel

    def make_weights_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("Wagi [-1, +1] - dane z JSON"))
        self.show_zero = QCheckBox("Pokaz tez wagi zerowe")
        self.show_zero.toggled.connect(self.draw_weights)
        layout.addWidget(self.show_zero)
        self.weight_scroll = QScrollArea()
        self.weight_scroll.setWidgetResizable(True)
        layout.addWidget(self.weight_scroll, 1)
        save_btn = QPushButton("Zapisz wagi JSON")
        save_btn.clicked.connect(self.save_weights)
        layout.addWidget(save_btn)
        run_btn = QPushButton("Przelicz r7, r8, r9 + klasy")
        run_btn.clicked.connect(self.run_calculations)
        layout.addWidget(run_btn)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        layout.addWidget(self.log)
        self.read_weights()
        return panel

    def read_weights(self):
        try:
            self.weight_doc = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
            if not isinstance(self.weight_doc, dict):
                raise ValueError("Korzen JSON nie jest obiektem")
            if isinstance(self.weight_doc.get("weights"), dict):
                self.weight_map = self.weight_doc["weights"]
            elif isinstance(self.weight_doc.get("wagi"), dict):
                self.weight_map = self.weight_doc["wagi"]
            else:
                self.weight_map = self.weight_doc
            if not all(isinstance(v, (int, float)) for v in self.weight_map.values()):
                raise ValueError("Oczekiwano slownika nazwa_parametru: waga")
            self.draw_weights()
        except Exception as exc:
            self.log.append(f"Wagi: {exc}")

    def draw_weights(self):
        # Slidery maja skale 0.01; aktualny stan zapisujemy przy przesunieciu.
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.weight_controls = {}
        for name, weight in sorted(self.weight_map.items()):
            if not self.show_zero.isChecked() and abs(weight) < 1e-12:
                continue
            row = QHBoxLayout()
            name_label = QLabel(name)
            name_label.setToolTip(name)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(-100, 100)
            slider.setValue(int(round(weight * 100)))
            value_label = QLabel(f"{weight:+.2f}")
            value_label.setMinimumWidth(48)
            slider.valueChanged.connect(
                lambda v, n=name, label=value_label: self.weight_changed(n, v, label)
            )
            row.addWidget(name_label, 2)
            row.addWidget(slider, 3)
            row.addWidget(value_label, 1)
            layout.addLayout(row)
            self.weight_controls[name] = slider
        layout.addStretch()
        self.weight_scroll.setWidget(widget)

    def weight_changed(self, name, slider_value, label):
        value = round(slider_value / 100, 2)
        self.weight_map[name] = value
        label.setText(f"{value:+.2f}")

    def save_weights(self):
        try:
            if not self.weight_doc:
                raise RuntimeError("Brak odczytanych wag")
            WEIGHTS_FILE.write_text(
                json.dumps(self.weight_doc, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            self.log.append("Zapisano wagi do " + str(WEIGHTS_FILE))
        except Exception as exc:
            QMessageBox.warning(self, "Wagi", str(exc))

    def run_calculations(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Obliczenia", "Obliczenia juz trwaja")
            return
        if not self.db_password or len(self.h3_layers) != 3:
            QMessageBox.warning(self, "PostGIS", "Najpierw polacz 3 siatki z PostGIS")
            return
        reply = QMessageBox.question(
            self, "Przeliczenie przejezdnosci",
            "Zastapic wszystkie trzy tabele wynikowe przejezdnosci w env-test?\n"
            "Wagi z panelu zostana zapisane przed obliczeniami.\n"
            "Nie zamykaj aplikacji w trakcie obliczen.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.save_weights()
        self.log.clear()
        self.worker = Obliczenia(self.db_password, self)
        self.worker.message.connect(self.log.append)
        self.worker.completed.connect(self.calculations_finished)
        self.worker.start()

    def calculations_finished(self, success, info):
        self.log.append(info)
        if success:
            QMessageBox.information(
                self, "PSIP",
                "Przeliczono przejezdnosc r7/r8/r9. "
                "Odswiezymy teraz polaczenie PostGIS.")
            QTimer.singleShot(50, self.connect_db)
        else:
            QMessageBox.warning(self, "Problem z obliczeniami", info)

    def connect_db(self):
        password, ok = QInputDialog.getText(
            self, "PostGIS env-test", "Haslo uzytkownika psip (port 5434):",
            QLineEdit.Password,
        )
        if not ok:
            if not self.h3_layers:
                self.load_local()
            return
        # Nie usuwamy starego dzialajacego projektu przed sprawdzeniem nowych warstw.
        loaded = {}
        try:
            for r in (7, 8, 9):
                uri = QgsDataSourceUri()
                uri.setConnection("127.0.0.1", "5434", "psip", "psip", password)
                uri.setDataSource("grid", f"h3_przejezdnosc_r{r}", "geometry", "", "h3_id")
                layer = QgsVectorLayer(uri.uri(False), f"Przejezdnosc H3 r{r}", "postgres")
                if not layer.isValid():
                    raise RuntimeError(f"Nie mozna wczytac PostGIS H3 r{r}")
                if layer.fields().indexFromName("klasa_przejezdnosci") < 0:
                    raise RuntimeError(f"H3 r{r} nie ma pola klasa_przejezdnosci")
                self.style_categorized(layer)
                loaded[r] = layer
            self.clear_h3()
            self.h3_layers = loaded
            self.db_password = password
            group = QgsProject.instance().layerTreeRoot().insertGroup(0, "Przejezdnosc H3")
            for r in (9, 8, 7):
                layer = loaded[r]
                QgsProject.instance().addMapLayer(layer, False)
                node = group.addLayer(layer)
                node.setItemVisibilityChecked(r == self.current_resolution())
            self.tree.expandAll()
            self.populate_layers()
            self.zoom_to_layer(self.h3_layers[self.current_resolution()])
            self.statusBar().showMessage("PostGIS env-test: 3 siatki zaladowane")
        except Exception as exc:
            QMessageBox.warning(self, "PostGIS", str(exc))
            if not self.h3_layers:
                self.load_local()

    def load_local(self):
        if not LOCAL_GPKG.is_file():
            QMessageBox.warning(self, "Dane", f"Brak {LOCAL_GPKG}")
            return
        loaded = {}
        for r in (7, 8, 9):
            layer = QgsVectorLayer(
                str(LOCAL_GPKG) + f"|layername=h3_r{r}",
                f"Siatka H3 r{r} (bez przejezdnosci)", "ogr")
            if layer.isValid():
                loaded[r] = layer
        if not loaded:
            return
        self.clear_h3()
        self.h3_layers = loaded
        group = QgsProject.instance().layerTreeRoot().insertGroup(0, "Siatka H3 - offline")
        for r in sorted(loaded, reverse=True):
            QgsProject.instance().addMapLayer(loaded[r], False)
            node = group.addLayer(loaded[r])
            node.setItemVisibilityChecked(r == 9)
        self.populate_layers()
        self.zoom_to_layer(loaded[9])
        self.statusBar().showMessage("Tryb offline: tylko geometria H3")

    def clear_h3(self):
        root = QgsProject.instance().layerTreeRoot()
        for layer in self.h3_layers.values():
            if QgsProject.instance().mapLayer(layer.id()):
                QgsProject.instance().removeMapLayer(layer.id())
        for name in ("Przejezdnosc H3", "Siatka H3 - offline"):
            node = root.findGroup(name)
            if node:
                root.removeChildNode(node)
        self.h3_layers.clear()

    def current_resolution(self):
        return (7, 8, 9)[self.resolution.currentIndex()]

    def change_resolution(self):
        if self.current_resolution() not in self.h3_layers:
            return
        root = QgsProject.instance().layerTreeRoot()
        for r, layer in self.h3_layers.items():
            node = root.findLayer(layer.id())
            if node:
                node.setItemVisibilityChecked(r == self.current_resolution())
        self.zoom_to_layer(self.h3_layers[self.current_resolution()])

    def style_categorized(self, layer):
        desc = ["Niska (-1 do -0,333)", "Srednia (-0,333 do +0,333)",
                "Wysoka (+0,333 do +1)"]
        categories = []
        for idx, (color, label) in enumerate(zip(COLORS, desc), 1):
            symbol = QgsFillSymbol.createSimple({
                "color": color, "outline_color": "#777777",
                "outline_width": "0.08", "outline_width_unit": "MM",
            })
            categories.append(QgsRendererCategory(idx, symbol, label))
        layer.setRenderer(QgsCategorizedSymbolRenderer("klasa_przejezdnosci", categories))

    def pick_color(self, index):
        picked = QColorDialog.getColor(QColor(self.current_colors[index]), self)
        if picked.isValid():
            self.current_colors[index] = picked.name()

    def apply_style(self):
        a, b = self.lower.value(), self.upper.value()
        if a >= b:
            QMessageBox.warning(self, "Styl", "Dolna granica musi byc mniejsza od gornej")
            return
        layer = self.h3_layers.get(self.current_resolution())
        if not layer or layer.fields().indexFromName("wsp_iop_norm") < 0:
            QMessageBox.warning(self, "Styl", "Wybierz warstwe H3 z PostGIS z polem wsp_iop_norm")
            return
        ranges = []
        edges = [(-1.0, a), (a, b), (b, 1.0)]
        names = ["Niska", "Srednia", "Wysoka"]
        for (lo, hi), color, name in zip(edges, self.current_colors, names):
            symbol = QgsFillSymbol.createSimple({
                "color": color, "outline_color": "#777777",
                "outline_width": "0.08", "outline_width_unit": "MM",
            })
            ranges.append(QgsRendererRange(lo, hi, symbol, f"{name}: {lo:.3f} do {hi:.3f}"))
        layer.setRenderer(QgsGraduatedSymbolRenderer("wsp_iop_norm", ranges))
        layer.triggerRepaint()
        self.tree_model.refreshLayerLegend(QgsProject.instance().layerTreeRoot().findLayer(layer.id()))
        self.canvas.refresh()
        self.statusBar().showMessage("Styl H3 r%d zmieniony" % self.current_resolution())

    def add_shp(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Wczytaj warstwe SHP", str(ROOT / "data"), "Shapefile (*.shp)")
        if not filename:
            return
        layer = QgsVectorLayer(filename, Path(filename).stem, "ogr")
        if not layer.isValid():
            QMessageBox.warning(self, "SHP", "Nie mozna otworzyc wskazanego SHP")
            return
        QgsProject.instance().addMapLayer(layer)
        self.populate_layers()
        self.zoom_to_layer(layer)

    def populate_layers(self):
        selected_id = self.search_layer.currentData()
        self.search_layer.blockSignals(True)
        self.search_layer.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                self.search_layer.addItem(layer.name(), layer.id())
        i = self.search_layer.findData(selected_id)
        if i >= 0:
            self.search_layer.setCurrentIndex(i)
        self.search_layer.blockSignals(False)
        self.update_fields()

    def update_fields(self):
        self.search_field.clear()
        layer = QgsProject.instance().mapLayer(self.search_layer.currentData())
        if layer:
            self.search_field.addItems([field.name() for field in layer.fields()])

    def search_features(self):
        layer = QgsProject.instance().mapLayer(self.search_layer.currentData())
        field = self.search_field.currentText()
        target = self.search_value.text().strip()
        op = self.search_op.currentText()
        if not layer or not field or not target:
            return
        found = []
        first_geometry = None
        try:
            for feature in layer.getFeatures():
                raw = feature[field]
                if raw is None:
                    continue
                if op == "zawiera":
                    match = target.casefold() in str(raw).casefold()
                elif op == "=":
                    match = str(raw).casefold() == target.casefold()
                    if not match:
                        try:
                            match = math.isclose(float(raw), float(target), abs_tol=1e-8)
                        except (TypeError, ValueError):
                            pass
                else:
                    try:
                        a, b = float(raw), float(target)
                        match = a > b if op == ">" else a < b
                    except (ValueError, TypeError):
                        match = False
                if match:
                    found.append(feature.id())
                    if first_geometry is None:
                        first_geometry = QgsGeometry(feature.geometry())
                    if len(found) >= 2000:
                        break
            layer.selectByIds(found)
            self.statusBar().showMessage(f"{layer.name()}: zaznaczono {len(found)} (limit 2000)")
            if first_geometry:
                self.zoom_geometry(first_geometry.boundingBox(), layer.crs())
            else:
                QMessageBox.information(self, "Wyszukiwanie", "Brak pasujacych obiektow")
        except Exception as exc:
            QMessageBox.warning(self, "Wyszukiwanie", str(exc))

    def zoom_selected(self):
        layer = QgsProject.instance().mapLayer(self.search_layer.currentData())
        if not layer or not layer.selectedFeatureIds():
            QMessageBox.information(self, "Zoom", "Najpierw wyszukaj lub zaznacz obiekt")
            return
        fid = next(iter(layer.selectedFeatureIds()))
        feature = next(layer.getFeatures(QgsFeatureRequest().setFilterFid(fid)), None)
        if feature:
            self.zoom_geometry(feature.geometry().boundingBox(), layer.crs())

    def zoom_to_layer(self, layer):
        self.zoom_geometry(layer.extent(), layer.crs())

    def zoom_geometry(self, extent, source_crs):
        try:
            transform = QgsCoordinateTransform(source_crs, self.canvas.mapSettings().destinationCrs(), QgsProject.instance())
            ext = transform.transformBoundingBox(extent)
            ext.scale(1.1)
            self.canvas.setExtent(ext)
            self.canvas.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Zoom", str(exc))

    def pan(self):
        self.mode = "pan"
        self.canvas.setMapTool(self.pan_tool)
        self.statusBar().showMessage("Tryb przesuwania")

    def start_measure(self):
        self.mode = "measure"
        self.measure_start = None
        if self.measure_band is not None:
            self.measure_band.reset(QgsWkbTypes.LineGeometry)
        self.canvas.setMapTool(self.click_tool)
        self.statusBar().showMessage("Pomiar: kliknij pierwszy i drugi punkt")

    def start_points(self):
        if self.point_layer is None:
            self.point_layer = QgsVectorLayer("Point?crs=EPSG:2180", "Punkty uzytkownika", "memory")
            symbol = QgsMarkerSymbol.createSimple({"name": "circle", "color": "#2463eb", "size": "3"})
            self.point_layer.renderer().setSymbol(symbol)
            QgsProject.instance().addMapLayer(self.point_layer)
            self.populate_layers()
        self.mode = "point"
        self.canvas.setMapTool(self.click_tool)
        self.statusBar().showMessage("Dodawanie punktow: klikaj na mapie, zakoncz przyciskiem Przesuwaj")

    def map_clicked(self, point, button):
        if button != Qt.LeftButton:
            return
        if self.mode == "point":
            point_layer = self.point_layer
            feature = QgsFeature(point_layer.fields())
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(point)))
            ok, _ = point_layer.dataProvider().addFeatures([feature])
            point_layer.updateExtents()
            point_layer.triggerRepaint()
            if not ok:
                QMessageBox.warning(self, "Punkty", "Nie udalo sie dodac punktu")
        elif self.mode == "measure":
            if self.measure_start is None:
                self.measure_start = QgsPointXY(point)
                self.statusBar().showMessage("Pomiar: kliknij punkt koncowy")
            else:
                end = QgsPointXY(point)
                measure = QgsDistanceArea()
                measure.setSourceCrs(self.canvas.mapSettings().destinationCrs(),
                                     QgsProject.instance().transformContext())
                measure.setEllipsoid("WGS84")
                distance = measure.measureLine(self.measure_start, end)
                if self.measure_band is None:
                    self.measure_band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
                    self.measure_band.setColor(QColor("#ff9600"))
                    self.measure_band.setWidth(3)
                self.measure_band.reset(QgsWkbTypes.LineGeometry)
                self.measure_band.addPoint(self.measure_start, False)
                self.measure_band.addPoint(end, True)
                self.measure_start = None
                self.statusBar().showMessage(f"Odleglosc: {distance:,.2f} m")
                QMessageBox.information(self, "Pomiar", f"Odleglosc miedzy punktami: {distance:,.2f} m")

    def coords_changed(self, point):
        self.coordinates.setText(f"X: {point.x():.2f}   Y: {point.y():.2f}  (EPSG:2180)")

    def scale_changed(self, scale):
        self.map_scale.setText(f"Skala: 1:{scale:,.0f}".replace(",", " "))

    def export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Eksport widocznej mapy", str(ROOT / "wyniki" / "mapa_PSIP.pdf"), "PDF (*.pdf)")
        if not path:
            return
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            layout = QgsPrintLayout(QgsProject.instance())
            layout.initializeDefaults()
            page = layout.pageCollection().pages()[0]
            page.setPageSize(QgsLayoutSize(297, 210))  # A4 poziomo, mm
            map_item = QgsLayoutItemMap(layout)
            layout.addLayoutItem(map_item)
            map_item.attemptMove(QgsLayoutPoint(7, 7))
            map_item.attemptResize(QgsLayoutSize(283, 196))
            map_item.setCrs(self.canvas.mapSettings().destinationCrs())
            map_item.setLayers(self.canvas.layers())
            map_item.setKeepLayerSet(True)
            map_item.zoomToExtent(self.canvas.extent())
            result = QgsLayoutExporter(layout).exportToPdf(path, QgsLayoutExporter.PdfExportSettings())
            if result != QgsLayoutExporter.Success:
                raise RuntimeError(f"Kod bledu eksportu: {result}")
            QMessageBox.information(self, "PDF", f"Zapisano: {path}")
        except Exception as exc:
            QMessageBox.warning(self, "Eksport PDF", str(exc))

    def toggle_theme(self):
        self.dark = not self.dark
        self.setStyleSheet(CIEMNY if self.dark else JASNY)
        self.canvas.setCanvasColor(QColor("#202938" if self.dark else "#ffffff"))
        self.canvas.refresh()

    def logout(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Obliczenia", "Nie mozna wylogowac podczas obliczen")
            return
        self.logging_out = True
        self.close()
        QTimer.singleShot(0, self.on_logout)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
            QMessageBox.warning(self, "Obliczenia", "Zakoncz najpierw obliczenia")
            return
        self.canvas.setLayers([])
        QgsProject.instance().removeAllMapLayers()
        event.accept()
        if not self.logging_out:
            QTimer.singleShot(0, QgsApplication.instance().quit)


class Controller:
    def __init__(self, app):
        self.app = app
        self.window = None

    def login(self):
        if OknoLogowania().exec_() != QDialog.Accepted:
            self.app.quit()
            return
        self.window = PSIPWindow(self.login)
        self.window.show()


def main():
    QgsApplication.setPrefixPath(QGIS_PREFIX, True)
    app = QgsApplication([arg.encode("utf-8") for arg in sys.argv], True)
    app.initQgis()
    app.setQuitOnLastWindowClosed(False)
    controller = Controller(app)
    QTimer.singleShot(0, controller.login)
    code = app.exec_()
    QgsProject.instance().removeAllMapLayers()
    app.exitQgis()
    sys.exit(code)


if __name__ == "__main__":
    main()
