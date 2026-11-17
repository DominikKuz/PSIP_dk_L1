
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame
)


# Domyslny schemat kolorow przejezdnosci.
# Pozniej bedzie odczytywany ze stylu warstwy.
KLASY = [
    ("Niska przejezdnosc", "-1 do -0,333", "#c63131"),
    ("Srednia przejezdnosc", "-0,333 do +0,333", "#ffffff"),
    ("Wysoka przejezdnosc", "+0,333 do +1", "#238b45"),
]


class LegendaWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.rozdzielczosc = 9
        self.klasy = KLASY.copy()

        self.uklad = QVBoxLayout(self)
        self.uklad.setContentsMargins(12, 12, 12, 12)
        self.uklad.setSpacing(12)

        naglowek = QLabel("LEGENDA MAPY")
        naglowek.setStyleSheet(
            "font-size: 16px; font-weight: bold;"
        )
        self.uklad.addWidget(naglowek)

        self.nazwa_warstwy = QLabel()
        self.nazwa_warstwy.setStyleSheet(
            "font-weight: bold; font-size: 13px;"
        )
        self.uklad.addWidget(self.nazwa_warstwy)

        self.kontener = QVBoxLayout()
        self.kontener.setSpacing(12)
        self.uklad.addLayout(self.kontener)

        self.uklad.addStretch()
        self.odswiez()

    def ustaw_rozdzielczosc(self, rozdzielczosc):
        self.rozdzielczosc = int(rozdzielczosc)
        self.odswiez()

    def ustaw_klasy(self, klasy):
        """Pozwala zaktualizowac symbole z przyszlego modulu stylow."""
        self.klasy = list(klasy)
        self.odswiez()

    def odswiez(self):
        self.nazwa_warstwy.setText(
            f"Przejezdnosc terenu - H3 r{self.rozdzielczosc}"
        )

        while self.kontener.count():
            element = self.kontener.takeAt(0)
            widget = element.widget()
            if widget is not None:
                widget.deleteLater()

        for nazwa, zakres, kolor in self.klasy:
            wiersz = QWidget()
            uklad_wiersza = QHBoxLayout(wiersz)
            uklad_wiersza.setContentsMargins(0, 0, 0, 0)
            uklad_wiersza.setSpacing(10)

            symbol = QFrame()
            symbol.setFixedSize(25, 25)
            symbol.setStyleSheet(
                f"background-color: {kolor};"
                "border: 1px solid #666666;"
                "border-radius: 3px;"
            )

            tekst = QLabel(f"{nazwa}\n{zakres}")
            tekst.setWordWrap(True)

            uklad_wiersza.addWidget(symbol)
            uklad_wiersza.addWidget(tekst, 1)

            self.kontener.addWidget(wiersz)
