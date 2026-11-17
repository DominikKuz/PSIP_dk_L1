
import sys
from pathlib import Path

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QDialog, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QComboBox, QPushButton,
    QGroupBox, QInputDialog, QLineEdit, QMessageBox
)

from qgis.core import (
    QgsApplication, QgsProject, QgsVectorLayer,
    QgsDataSourceUri, QgsFillSymbol,
    QgsRendererCategory, QgsCategorizedSymbolRenderer
)
from qgis.gui import QgsMapCanvas, QgsMapToolPan

from legenda import LegendaWidget
from logowanie import OknoLogowania
from motywy import JASNY, CIEMNY


QGIS_PATH = r"D:\QGis_2026\apps\qgis-ltr"
ROOT = Path(__file__).resolve().parent.parent
GPKG = ROOT / "data" / "hexagons_torun_z_miastem.gpkg"


class AplikacjaPSIP(QMainWindow):
    def __init__(self, po_wylogowaniu):
        super().__init__()

        self.po_wylogowaniu = po_wylogowaniu
        self.czy_wylogowano = False
        self.ciemny_motyw = False
        self.haslo_bazy = None
        self.warstwy = {}

        self.setWindowTitle(
            "PSIP - System analizy przejezdnosci terenu"
        )
        self.resize(1350, 800)
        self.setMinimumSize(1000, 650)

        self.setStyleSheet(JASNY)

        centralny = QWidget()
        self.setCentralWidget(centralny)

        calosc = QVBoxLayout(centralny)
        calosc.setContentsMargins(12, 12, 12, 8)
        calosc.setSpacing(10)

        # NAGLOWEK
        tytul = QLabel(
            "PSIP | SYSTEM ANALIZY PRZEJEZDNOSCI TERENU"
        )
        tytul.setStyleSheet(
            "font-size: 20px; font-weight: bold;"
        )
        calosc.addWidget(tytul)

        # PASEK NARZEDZI
        pasek = QHBoxLayout()

        narzedzia = [
            ("Polacz PostGIS", self.polacz_postgis, True),
            ("Przesuwaj", self.wlacz_przesuwanie, True),
            ("Zoom +", self.przybliz, True),
            ("Zoom -", self.oddal, True),
            ("Wczytaj SHP", None, False),
            ("Pomiar", None, False),
            ("Dodaj punkt", None, False),
            ("Eksport PDF", None, False),
            ("Zmien motyw", self.zmien_motyw, True),
            ("Wyloguj", self.wyloguj, True)
        ]

        for napis, funkcja, aktywny in narzedzia:
            przycisk = QPushButton(napis)
            przycisk.setEnabled(aktywny)

            if funkcja is not None:
                przycisk.clicked.connect(funkcja)

            pasek.addWidget(przycisk)

        calosc.addLayout(pasek)

        # GLOWNE TRZY PANELE
        kolumny = QHBoxLayout()
        kolumny.setSpacing(10)

        # LEWY PANEL - LEGENDA
        lewy_panel = QGroupBox("WARSTWY I LEGENDA")
        lewy_uklad = QVBoxLayout(lewy_panel)

        lewy_uklad.addWidget(
            QLabel("Rozdzielczosc H3:")
        )

        self.wybor_h3 = QComboBox()
        self.wybor_h3.addItems([
            "H3 r7", "H3 r8", "H3 r9"
        ])
        self.wybor_h3.setCurrentIndex(2)

        lewy_uklad.addWidget(self.wybor_h3)

        self.legenda = LegendaWidget()
        lewy_uklad.addWidget(self.legenda, 1)

        kolumny.addWidget(lewy_panel, 2)

        # SRODEK - PRAWDZIWA MAPA PYQGIS
        mapa_panel = QGroupBox("MAPA INTERAKTYWNA")
        mapa_uklad = QVBoxLayout(mapa_panel)

        self.mapa = QgsMapCanvas()
        self.mapa.setCanvasColor(Qt.white)
        self.mapa.setMinimumSize(350, 350)

        # Narzedzie przesuwania - musi pozostac
        # zapisane jako atrybut obiektu.
        self.narzedzie_pan = QgsMapToolPan(self.mapa)
        self.mapa.setMapTool(self.narzedzie_pan)

        mapa_uklad.addWidget(self.mapa, 1)

        kolumny.addWidget(mapa_panel, 6)

        # PRAWY PANEL - PRZYSZLE FUNKCJE
        prawy_panel = QGroupBox("ANALIZA I STYL")
        prawy_uklad = QVBoxLayout(prawy_panel)

        prawy_uklad.addWidget(QLabel(
            "Planowane funkcje:\n\n"
            "- Suwaki wag\n\n"
            "- Przeliczanie przejezdnosci\n\n"
            "- Edycja kolorow i zakresow\n\n"
            "- Wyszukiwanie atrybutow\n\n"
            "- Statystyki"
        ))
        prawy_uklad.addStretch()

        kolumny.addWidget(prawy_panel, 2)

        calosc.addLayout(kolumny, 1)

        self.statusBar().showMessage(
            "PSIP | Mapa gotowa do wczytania"
        )

        self.wybor_h3.currentIndexChanged.connect(
            self.zmien_rozdzielczosc
        )

        # Po otwarciu okna probujemy polaczyc PostGIS.
        QTimer.singleShot(100, self.polacz_postgis)

    def aktualna_rozdzielczosc(self):
        return [7, 8, 9][self.wybor_h3.currentIndex()]

    def utworz_styl(self, warstwa):
        klasy = [
            (1, "#c63131",
             "Nieprzejezdny (-1 do -0,333)"),
            (2, "#ffffff",
             "Sredni (-0,333 do +0,333)"),
            (3, "#238b45",
             "Przejezdny (+0,333 do +1)")
        ]

        kategorie = []

        for numer, kolor, opis in klasy:
            symbol = QgsFillSymbol.createSimple({
                "color": kolor,
                "outline_color": "#777777",
                "outline_width": "0.08",
                "outline_width_unit": "MM"
            })

            kategorie.append(
                QgsRendererCategory(
                    numer, symbol, opis
                )
            )

        warstwa.setRenderer(
            QgsCategorizedSymbolRenderer(
                "klasa_przejezdnosci",
                kategorie
            )
        )

    def polacz_postgis(self):
        if self.haslo_bazy is None:
            haslo, ok = QInputDialog.getText(
                self,
                "Polaczenie PostGIS",
                "Podaj haslo bazy env-test (psip):",
                QLineEdit.Password
            )

            if not ok:
                self.wczytaj_lokalna_siatke()
                return

            self.haslo_bazy = haslo

        try:
            self.usun_warstwy()

            for rozdzielczosc in (7, 8, 9):
                uri = QgsDataSourceUri()

                uri.setConnection(
                    "127.0.0.1",
                    "5434",
                    "psip",
                    "psip",
                    self.haslo_bazy
                )

                uri.setDataSource(
                    "grid",
                    f"h3_przejezdnosc_r{rozdzielczosc}",
                    "geometry",
                    "",
                    "h3_id"
                )

                warstwa = QgsVectorLayer(
                    uri.uri(False),
                    f"Przejezdnosc H3 r{rozdzielczosc}",
                    "postgres"
                )

                if not warstwa.isValid():
                    raise RuntimeError(
                        f"Nie mozna wczytac H3 r{rozdzielczosc}"
                    )

                if warstwa.fields().indexFromName(
                    "klasa_przejezdnosci"
                ) == -1:
                    raise RuntimeError(
                        "Brak pola klasa_przejezdnosci"
                    )

                self.utworz_styl(warstwa)

                QgsProject.instance().addMapLayer(
                    warstwa, False
                )
                self.warstwy[rozdzielczosc] = warstwa

            self.pokaz_warstwe()

            self.statusBar().showMessage(
                "PSIP | Polaczono z PostGIS env-test | "
                "Wczytano H3 r7, r8 i r9"
            )

        except Exception as blad:
            self.usun_warstwy()
            self.haslo_bazy = None

            QMessageBox.warning(
                self,
                "Problem z PostGIS",
                str(blad) +
                "\n\nWczytam lokalna siatke H3."
            )
            self.wczytaj_lokalna_siatke()

    def wczytaj_lokalna_siatke(self):
        self.usun_warstwy()

        if not GPKG.exists():
            self.statusBar().showMessage(
                "Brak lokalnego pliku H3"
            )
            return

        for rozdzielczosc in (7, 8, 9):
            sciezka = (
                f"{GPKG.as_posix()}|"
                f"layername=h3_r{rozdzielczosc}"
            )

            warstwa = QgsVectorLayer(
                sciezka,
                f"Siatka H3 r{rozdzielczosc}",
                "ogr"
            )

            if not warstwa.isValid():
                continue

            QgsProject.instance().addMapLayer(
                warstwa, False
            )
            self.warstwy[rozdzielczosc] = warstwa

        self.pokaz_warstwe()

        self.statusBar().showMessage(
            "PSIP | Tryb lokalny: sama siatka H3, "
            "bez wynikow przejezdnosci"
        )

    def pokaz_warstwe(self):
        rozdzielczosc = self.aktualna_rozdzielczosc()

        if rozdzielczosc not in self.warstwy:
            return

        warstwa = self.warstwy[rozdzielczosc]

        self.mapa.setDestinationCrs(warstwa.crs())
        self.mapa.setLayers([warstwa])
        self.mapa.setExtent(warstwa.extent())
        self.mapa.refresh()

    def zmien_rozdzielczosc(self):
        rozdzielczosc = self.aktualna_rozdzielczosc()

        self.legenda.ustaw_rozdzielczosc(
            rozdzielczosc
        )
        self.pokaz_warstwe()

    def wlacz_przesuwanie(self):
        self.mapa.setMapTool(self.narzedzie_pan)

    def przybliz(self):
        self.mapa.zoomIn()

    def oddal(self):
        self.mapa.zoomOut()

    def zmien_motyw(self):
        self.ciemny_motyw = not self.ciemny_motyw

        if self.ciemny_motyw:
            self.setStyleSheet(CIEMNY)
        else:
            self.setStyleSheet(JASNY)

    def usun_warstwy(self):
        self.mapa.setLayers([])

        for warstwa in self.warstwy.values():
            QgsProject.instance().removeMapLayer(
                warstwa.id()
            )

        self.warstwy.clear()

    def wyloguj(self):
        self.czy_wylogowano = True
        self.close()

        # Ponowne logowanie po zamknieciu okna.
        QTimer.singleShot(0, self.po_wylogowaniu)

    def closeEvent(self, event):
        self.usun_warstwy()
        event.accept()

        if not self.czy_wylogowano:
            QTimer.singleShot(
                0, QgsApplication.instance().quit
            )


class KontrolerAplikacji:
    def __init__(self, app):
        self.app = app
        self.okno = None

    def zaloguj(self):
        logowanie = OknoLogowania()

        if logowanie.exec_() != QDialog.Accepted:
            self.app.quit()
            return

        self.okno = AplikacjaPSIP(
            po_wylogowaniu=self.zaloguj
        )
        self.okno.show()


def main():
    QgsApplication.setPrefixPath(QGIS_PATH, True)

    # W tej instalacji QGIS argumenty sa bajtami.
    argumenty = [
        arg.encode("utf-8")
        for arg in sys.argv
    ]

    app = QgsApplication(argumenty, True)
    app.initQgis()

    # Wylogowanie nie powinno konczyc programu.
    app.setQuitOnLastWindowClosed(False)

    kontroler = KontrolerAplikacji(app)
    QTimer.singleShot(0, kontroler.zaloguj)

    kod = app.exec_()

    QgsProject.instance().removeAllMapLayers()
    app.exitQgis()

    sys.exit(kod)


if __name__ == "__main__":
    main()
