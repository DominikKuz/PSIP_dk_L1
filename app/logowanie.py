
import hashlib
import hmac

from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox
)


class OknoLogowania(QDialog):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("PSIP - Logowanie")
        self.setFixedSize(350, 220)

        uklad = QVBoxLayout(self)

        tytul = QLabel("Logowanie do systemu PSIP")
        tytul.setStyleSheet(
            "font-size: 18px; font-weight: bold;"
        )
        uklad.addWidget(tytul)

        self.haslo = QLineEdit()
        self.haslo.setPlaceholderText("Wpisz haslo")
        self.haslo.setEchoMode(QLineEdit.Password)
        uklad.addWidget(self.haslo)

        self.przycisk = QPushButton("Zaloguj")
        self.przycisk.clicked.connect(self.sprawdz_haslo)
        uklad.addWidget(self.przycisk)

        self.haslo.returnPressed.connect(
            self.sprawdz_haslo
        )

    def sprawdz_haslo(self):
        # Tymczasowe haslo demonstracyjne.
        # Pozniej przeniesiemy konfiguracje poza kod.
        poprawny_hash = hashlib.sha256(
            b"PSIP2026"
        ).digest()

        wpisany_hash = hashlib.sha256(
            self.haslo.text().encode("utf-8")
        ).digest()

        if hmac.compare_digest(
            wpisany_hash, poprawny_hash
        ):
            self.accept()
        else:
            QMessageBox.warning(
                self,
                "Blad logowania",
                "Nieprawidlowe haslo!"
            )
            self.haslo.clear()
