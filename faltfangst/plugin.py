"""Knappen, dialogen och traden.

En knapp, ett lansval, en mapp. Nar korningen ar klar oppnas projektet, sa
att inventeraren kan borja arbeta utan att leta reda pa nagon fil.

Korningen ligger i en QThread. Ett lansuttag ar 45-290 MB och tar en stund;
utan trad fryser QGIS och det ser ut som om nagot gatt sonder.
"""

from __future__ import annotations

import os
from pathlib import Path

from qgis.core import QgsProject
from qgis.PyQt.QtCore import QSettings, Qt, QThread, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from arkstod import lan as lansmodul
from arkstod.faltdel import blankettkod
from arkstod.faltdel.mall import ARBETSFIL, ar_faltuppsattning
from arkstod.faltdel.projekt import relativisera
from arkstod.faltdel.uttag import foreslagen_mapp, nytt_uttag

HAR = os.path.dirname(__file__)
DATABAS = os.path.join(HAR, "data", "lamningstyper.db")

# Verktygets namn. Det hette Lamningsdatabas, men det ar vad uttaget heter --
# en databas over lamningar. Verktyget som gor den ar nagot annat, och menyn
# lases nu "Faltfangst -> Lamningsdatabas - nytt uttag": verktyget, och sedan
# vad det gor.
MENY = "Fältfångst"


class Korning(QThread):
    """Uttaget i egen trad. QGIS ska inte frysa medan 45 MB hamtas."""

    framsteg = pyqtSignal(int)
    besked = pyqtSignal(str)
    klar = pyqtSignal(bool, str, object)

    def __init__(self, lansnamn: str, mapp: str, grannlan=()) -> None:
        super().__init__()
        self._lan = lansnamn
        self._mapp = mapp
        self._grannlan = list(grannlan)

    def run(self) -> None:  # noqa: D102
        try:
            def aterkoppling(hamtat: int, totalt: int) -> None:
                self.framsteg.emit(int(100 * hamtat / totalt))

            rapport = nytt_uttag(
                self._lan,
                self._mapp,
                DATABAS,
                None,
                aterkoppling,
                grannlan=self._grannlan,
                meddela=self.besked.emit,
            )
            self.framsteg.emit(100)
            self.klar.emit(True, "", rapport)
        except Exception as fel:  # noqa: BLE001  (allt ska nå dialogen)
            self.klar.emit(False, str(fel), None)


class Dialog(QDialog):
    def __init__(self, foralder=None) -> None:
        super().__init__(foralder)
        self.setWindowTitle("Lämningsdatabas — nytt uttag")
        self.setMinimumWidth(560)
        self._tråd: Korning | None = None
        self.rapport = None

        installningar = QSettings()
        senaste_lan = installningar.value("arkstod/lan", "jämtland")
        # Forr sparades hela arbetsmappen. Den ar per definition upptagen
        # nasta gaang, sa det ar foraldern som ar vard att minnas -- och
        # dess forra varde duger som utgangslage.
        forald = installningar.value("arkstod/foraldermapp")
        if not forald:
            gammal = installningar.value("arkstod/mapp")
            forald = (
                os.path.dirname(gammal)
                if gammal
                else os.path.expanduser("~/Lamningsdatabas")
            )

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Län"))
        self.lanval = QComboBox()
        for namn in lansmodul.LAN:
            self.lanval.addItem(namn.title(), namn)
        index = self.lanval.findData(senaste_lan)
        if index >= 0:
            self.lanval.setCurrentIndex(index)
        layout.addWidget(self.lanval)

        # Nar arbetet gaar over lansgransen -- en kraftledning, en vag. Bada
        # lanens lamningar hamnar i samma arbetsfil. Valet minns inte: ett
        # gransarbete ar ett undantag, och ett grannlan som foljer med av sig
        # sjalvt till nasta uttag ar en nedladdning ingen bett om.
        layout.addWidget(QLabel("Grannlän — om arbetet går över länsgränsen"))
        self.grannval = QComboBox()
        self.grannval.addItem("Inget", "")
        for namn in lansmodul.LAN:
            self.grannval.addItem(namn.title(), namn)
        layout.addWidget(self.grannval)

        layout.addWidget(QLabel("Spara i"))
        rad = QHBoxLayout()
        self.foraldfalt = QLineEdit(forald)
        self.foraldfalt.textChanged.connect(self._visa_sokvag)
        rad.addWidget(self.foraldfalt)
        bladdra = QPushButton("Välj …")
        bladdra.clicked.connect(self._valj_mapp)
        rad.addWidget(bladdra)
        layout.addLayout(rad)

        layout.addWidget(QLabel("Mappnamn"))
        self.mappfalt = QLineEdit()
        self.mappfalt.textEdited.connect(self._eget_namn)
        self.mappfalt.textChanged.connect(self._visa_sokvag)
        layout.addWidget(self.mappfalt)

        # Registrerar man tjugo kolbottnar pa rad skiljer sig bara matten.
        # Avstangd som forval: den hor till det slaget av arbete och inte
        # till en vanlig dag. Glommer man att andra matten star forra
        # lamningens matt kvar -- risken ar kand och inventerarens.
        self.forklaring = QLabel("")
        self.forklaring.setWordWrap(True)
        layout.addWidget(self.forklaring)

        # Etiketten maste finnas innan forslaget skrivs: setText pa mappfaltet
        # utloser _visa_sokvag, som skriver i den.
        #
        # Sant sa lange namnet ar verktygets forslag. Skriver inventeraren
        # nagot eget ska ett lansbyte inte kasta bort det.
        self._forslaget_namn = True
        self.lanval.currentIndexChanged.connect(self._foresla_namn)
        self.grannval.currentIndexChanged.connect(self._foresla_namn)
        self._foresla_namn()
        self._visa_sokvag()

        self.matare = QProgressBar()
        self.matare.setRange(0, 100)
        layout.addWidget(self.matare)

        self.logg = QTextEdit()
        self.logg.setReadOnly(True)
        self.logg.setMinimumHeight(140)
        layout.addWidget(self.logg)

        self.knappar = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok().setText("Hämta och öppna")
        self.knappar.accepted.connect(self._starta)
        self.knappar.rejected.connect(self.reject)
        layout.addWidget(self.knappar)

    def _ok(self):
        """Knappen som startar uttaget.

        Uppraknade varden skrivs med hela namnet -- StandardButton.Ok, inte
        bara Ok. Det korta skrivsattet finns bara i Qt 5, det langa i bade
        Qt 5 och Qt 6 (QGIS 4).
        """
        return self.knappar.button(QDialogButtonBox.StandardButton.Ok)

    def _valj_mapp(self) -> None:
        vald = QFileDialog.getExistingDirectory(
            self, "Välj var lämningsdatabasen ska sparas", self.foraldfalt.text()
        )
        if vald:
            self.foraldfalt.setText(vald)

    def _eget_namn(self) -> None:
        """Inventeraren har skrivit ett eget namn. Sluta foresla."""
        self._forslaget_namn = False

    def _foresla_namn(self) -> None:
        """Lan och dagens datum, i den gamla uppsattningens egen form."""
        if not self._forslaget_namn:
            return
        forslag = foreslagen_mapp(
            self.lanval.currentData(),
            self.foraldfalt.text().strip() or ".",
            grannlan=self._grannlan(),
        )
        self.mappfalt.setText(forslag.name)
        self._forslaget_namn = True

    def _grannlan(self) -> list[str]:
        """Grannlanet, om ett ar valt och inte ar samma som lanet."""
        granne = self.grannval.currentData()
        if not granne or granne == self.lanval.currentData():
            return []
        return [granne]

    def _mapp(self) -> str:
        return os.path.join(
            self.foraldfalt.text().strip(), self.mappfalt.text().strip()
        )

    def _visa_sokvag(self) -> None:
        mapp = self._mapp()
        if os.path.exists(os.path.join(mapp, ARBETSFIL)):
            self.forklaring.setText(
                f"{mapp}\n\nDär ligger redan ett uttag. Ett nytt arbete får en "
                "egen mapp — verktyget rör aldrig en uppsättning du arbetat i."
            )
        else:
            self.forklaring.setText(
                f"{mapp}\n\nEtt uttag hör till ett arbete. Namnet är ett "
                "förslag — har arbetet ett eget namn är det bättre."
            )

    def _skriv(self, rad: str) -> None:
        self.logg.append(rad)
        self.logg.ensureCursorVisible()

    def _starta(self) -> None:
        lansnamn = self.lanval.currentData()
        if not self.foraldfalt.text().strip() or not self.mappfalt.text().strip():
            QMessageBox.warning(
                self, "Mapp saknas", "Fyll i både var den ska sparas och namnet."
            )
            return
        mapp = self._mapp()

        installningar = QSettings()
        installningar.setValue("arkstod/lan", lansnamn)
        installningar.setValue("arkstod/foraldermapp", self.foraldfalt.text().strip())

        self._ok().setEnabled(False)
        self.lanval.setEnabled(False)
        self.grannval.setEnabled(False)
        self.foraldfalt.setEnabled(False)
        self.mappfalt.setEnabled(False)
        self.logg.clear()

        self._tråd = Korning(lansnamn, mapp, self._grannlan())
        self._tråd.framsteg.connect(self.matare.setValue)
        self._tråd.besked.connect(self._skriv)
        self._tråd.klar.connect(self._avslutad)
        self._tråd.start()

    def _avslutad(self, lyckades: bool, fel: str, rapport) -> None:
        self._ok().setEnabled(True)
        self.lanval.setEnabled(True)
        self.grannval.setEnabled(True)
        self.foraldfalt.setEnabled(True)
        self.mappfalt.setEnabled(True)

        if not lyckades:
            self._skriv("")
            self._skriv(f"Det gick fel: {fel}")
            self._skriv(
                "Ingenting är skrivet i mappen — arbetsfilen tas i bruk först "
                "när allt annat lyckats."
            )
            return

        self.rapport = rapport
        self._skriv(f"Hämtat: {rapport.hamtade_byte / 1e6:.0f} MB")
        for tabell, antal in rapport.migrerade.items():
            self._skriv(f"  {tabell}: {antal} lämningar")
        for granne, fogning in rapport.fogning.items():
            self._skriv(
                f"{granne.title()}: {fogning.lamningar} lämningar tillagda,"
                f" {fogning.gemensamma} på gränsen fanns redan med"
            )
        # Varningarna i en egen ruta. Loggen ovanfor stangs med dialogen i
        # samma ogonblick som projektet oppnas, och en varning ingen hinner
        # lasa ar ingen varning.
        varningar = [
            f"{projekt} nämner lager som saknas i arbetsfilen: " + ", ".join(lager)
            for projekt, lager in rapport.saknade_lager.items()
        ] + [
            f"{projekt} pekar på en blankett som saknas i mappen: "
            + ", ".join(blanketter)
            + ". Klickar du på en lämning öppnas ingenting."
            for projekt, blanketter in rapport.saknade_blanketter.items()
        ]
        for varning in varningar:
            self._skriv("")
            self._skriv(f"VARNING: {varning}")
        if varningar:
            QMessageBox.warning(
                self,
                "Uttaget är inte helt",
                "\n\n".join(varningar)
                + "\n\nProjektet öppnas ändå. Installera om pluginen från"
                " zipen via QGIS och gör ett nytt uttag.",
            )
        self._skriv("")
        self._skriv("Öppnar projektet …")
        self.accept()


def _visa_i_utforskaren(fil) -> None:
    """Oppnar mappen med filen markerad.

    Att bara oppna mappen lases som "valj var du vill spara" -- filen ar
    redan skriven, och bland tio filer syns inte vilken som ar den nya.
    Rapporterat fran falt: "utforskaren oppnar projektfoldern men det finns
    ingen sparaknapp".
    """
    import sys as systemet

    fil = str(fil)
    if systemet.platform.startswith("win"):
        # Explorer vill ha citattecknen EFTER kommat: /select,"C:\en mapp\fil".
        # Citeras hela argumentet -- "/select,C:\en mapp\fil", vilket en
        # argumentlista till subprocess eller QProcess blir sa fort sokvagen
        # har ett mellanslag -- forstar Explorer det inte och oppnar Dokument
        # i stallet. Arbetsmappar har alltid mellanslag i namnet, sa filen
        # blev i praktiken aldrig markerad.
        #
        # os.startfile lamnar argumenten ordagrant till Windows, och lamnar
        # inget processobjekt efter sig. Med subprocess.Popen blev ett kvar
        # som ingen vantade pa, och Python skrev "ResourceWarning: subprocess
        # is still running" i loggen. QProcess.setNativeArguments hade gjort
        # samma sak men finns inte i Qt 5:s Python-bindningar.
        os.startfile("explorer.exe", "open", f'/select,"{fil}"')
        return
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(fil).parent)))


class Lamningsdatabas:
    """Verktygsknapparna."""

    def __init__(self, iface) -> None:
        self.iface = iface
        self.action: QAction | None = None
        self.leverans: QAction | None = None
        self.uppslagsbok: QAction | None = None
        self.rattelser: QAction | None = None
        self.aterstar: QAction | None = None
        self.om: QAction | None = None

    systemforslag = None
    systemvalda = None
    geometrier = None

    def initGui(self) -> None:  # noqa: N802
        # Knappen till uppslagsboken i falformularet. Funktionen maste ligga
        # i tolkens namnrymd innan ett formular oppnas -- projektet bar bara
        # namnet. Se blankettkod.py: python som ligger i en projektfil ar
        # sparrad bakom Qgis.PythonEmbeddedMode, pluginets ar det inte.
        blankettkod.registrera()
        # Tomma falt ska vara tomma. Se blankettkod.dolj_nulltexten: QGIS
        # egen installning, och den rors bara om den staar orord.
        blankettkod.dolj_nulltexten()
        # Och ett tryck pa en lamning ska oppna blanketten,
        # inte en resultatlista att klicka vidare i.
        blankettkod.oppna_formularet_vid_identifiering()

        ikon = os.path.join(HAR, "icon.png")
        self.action = QAction(
            QIcon(ikon) if os.path.exists(ikon) else QIcon(),
            "Lämningsdatabas — nytt uttag",
            self.iface.mainWindow(),
        )
        self.action.triggered.connect(self.kor)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu(MENY, self.action)

        self.leverans = QAction(
            QIcon(ikon) if os.path.exists(ikon) else QIcon(),
            "Leveranslista — inför registrering i Fornreg",
            self.iface.mainWindow(),
        )
        self.leverans.triggered.connect(self.skriv_leveranslista)
        self.iface.addToolBarIcon(self.leverans)
        self.iface.addPluginToMenu(MENY, self.leverans)

        self.uppslagsbok = QAction(
            QIcon(ikon) if os.path.exists(ikon) else QIcon(),
            "Uppslagsbok — lämningstypslistan att läsa",
            self.iface.mainWindow(),
        )
        self.uppslagsbok.triggered.connect(self.skriv_uppslagsbok)
        self.iface.addToolBarIcon(self.uppslagsbok)
        self.iface.addPluginToMenu(MENY, self.uppslagsbok)

        self.geometrier = QAction(
            QIcon(ikon) if os.path.exists(ikon) else QIcon(),
            "Geometrier till Fornreg — zippade shapefiler",
            self.iface.mainWindow(),
        )
        self.geometrier.triggered.connect(self.skriv_geometrier)
        self.iface.addPluginToMenu(MENY, self.geometrier)

        # Sammansatta lamningstyper hor till kontoret och inte till falt, sa
        # de ligger i menyn och inte i verktygsraden.
        self.systemforslag = QAction(
            "Sammansatta lämningar — föreslå ur punkterna",
            self.iface.mainWindow(),
        )
        self.systemforslag.triggered.connect(self.foresla_system)
        self.iface.addPluginToMenu(MENY, self.systemforslag)

        self.systemvalda = QAction(
            "Sammansatt lämning — av markerade",
            self.iface.mainWindow(),
        )
        self.systemvalda.triggered.connect(self.system_av_valda)
        self.iface.addPluginToMenu(MENY, self.systemvalda)

        # I verktygsraden: den ar till for att koras medan man staar kvar i
        # omradet, och da ska den ga att naa utan att leta i en meny.
        self.aterstar = QAction(
            QIcon(ikon) if os.path.exists(ikon) else QIcon(),
            "Vad återstår? — innan du lämnar området",
            self.iface.mainWindow(),
        )
        self.aterstar.triggered.connect(self.visa_aterstaende)
        self.iface.addToolBarIcon(self.aterstar)
        self.iface.addPluginToMenu(MENY, self.aterstar)

        # Bara i menyn. Den anvands en gaang per sittning, och en fjarde
        # likadan ikon i verktygsraden hjalper ingen att hitta den.
        self.rattelser = QAction(
            "Skriv in rättelser från leveranslistan …",
            self.iface.mainWindow(),
        )
        self.rattelser.triggered.connect(self.skriv_in_rattelser)
        self.iface.addPluginToMenu(MENY, self.rattelser)

        self.om = QAction(f"Om {MENY} …", self.iface.mainWindow())
        self.om.triggered.connect(self.visa_om)
        self.iface.addPluginToMenu(MENY, self.om)

        # Sokvagarna maste hallas relativa vid VARJE sparning, inte bara vid
        # uttaget. Se _relativisera_efter_sparning.
        QgsProject.instance().projectSaved.connect(self._efter_sparning)

    def unload(self) -> None:
        blankettkod.avregistrera()
        try:
            QgsProject.instance().projectSaved.disconnect(self._efter_sparning)
        except TypeError:
            pass
        for action in (self.action, self.leverans, self.uppslagsbok,
                       self.aterstar):
            if action is not None:
                self.iface.removeToolBarIcon(action)
                self.iface.removePluginMenu(MENY, action)
        for action in (self.rattelser, self.systemforslag, self.systemvalda,
                       self.geometrier, self.om):
            if action is not None:
                self.iface.removePluginMenu(MENY, action)

    # ------------------------------------------------------------- sokvagar
    def _efter_sparning(self) -> None:
        """Haller sokvagarna relativa varje gaang projektet sparas.

        **Varfor det behovs.** QGIS skriver ett `ProjectGpsSettings`-block i
        varje projekt, aven dar ingen GPS finns. Forvalet ar att destinationen
        foljer aktivt lager, och da cachas det aktiva lagrets kalla dar -- med
        absolut sokvag, for blocket gaar inte genom projektets
        sokvagsupplosare. Ett uttag som var flyttbart nar det skrevs slutar
        vara det sa fort nagon sparar i QGIS. Uppmatt: mallen ar ren, forsta
        sparningen ger `C:/.../lamningar.gpkg`, och en tomning av
        destinationen haller bara tills nasta lager blir aktivt.

        **Varfor uppskjutet.** `projectSaved` kommer INNAN filen ar
        fardigskriven. Kors rattningen direkt skriver QGIS over den igen --
        uppmatt pa filens andringstid. Ett varv i handelsekon racker.

        Bara uppsattningar som ar vara egna ror vi: kannetecknet ar
        arbetsfilen bredvid projektet. Ett annat projekt som rakar vara oppet
        ska verktyget halla fingrarna fran.

        **Inte `ARBETSFIL`.** Det namnet galler bara medan uttaget byggs --
        sist av allt ger `namnge_efter_lan` filen lanets namn och uttagets
        datum, och efter det heter den `lamningar_lan_<lan>_<datum>.gpkg`.
        Forsta versionen av den har kontrollen letade efter `lamningar.gpkg`
        och slog darfor aldrig till pa en fardig uppsattning. Mata mot det
        som faktiskt ligger dar, inte mot ett mellanlages namn.
        """
        sokvag = QgsProject.instance().fileName()
        if not sokvag:
            return
        if not ar_faltuppsattning(Path(sokvag).parent):
            return
        QTimer.singleShot(0, lambda: self._relativisera(sokvag))

    @staticmethod
    def _relativisera(sokvag: str) -> None:
        """Sjalva rattningen. En misslyckad rattning far aldrig stora sparningen."""
        try:
            if os.path.exists(sokvag):
                relativisera(sokvag)
        except Exception:          # noqa: BLE001
            pass

    def visa_om(self) -> None:
        """Namn, version, upphovsman -- och vad verktyget svarar utifran.

        Den sista uppgiften ar den som betyder nagot. Verktyget sager att en
        fangstgrop mats i bottenplan for att lamningstypslistan och
        exempelsamlingen sager sa, och de svaren galler bara sa lange de
        dokumenten galler. Da ska det ga att se vilka versioner man bar med
        sig ut, utan att oppna en databas.
        """
        import sqlite3

        from arkstod.faltdel.om import korpuskallor, las_metadata, om_texten

        metadata = las_metadata(os.path.join(HAR, "metadata.txt"))
        kallor = []
        if os.path.exists(DATABAS):
            try:
                anslutning = sqlite3.connect(f"file:{DATABAS}?mode=ro", uri=True)
            except sqlite3.Error:
                anslutning = None
            if anslutning is not None:
                try:
                    anslutning.text_factory = str
                    kallor = korpuskallor(anslutning)
                finally:
                    anslutning.close()
        QMessageBox.about(
            self.iface.mainWindow(), f"Om {MENY}", om_texten(metadata, kallor)
        )

    def visa_aterstaende(self) -> None:
        """Listar det som aterstar pa jobbets egna lamningar.

        Leveranslistan hittar samma saker men laeses pa kontoret, och da ar
        det for sent for allt som bara gaar att se pa platsen: matmetoden man
        anvande, traditionen nagon berattade, geometrisorten man ritade i.
        """
        import sqlite3

        from arkstod.faltdel.kontroller import granska_egna, sammanfatta_aterstaende

        sokvag = self._arbetsfil("Vad återstår?")
        if sokvag is None:
            return
        anslutning = sqlite3.connect(f"file:{sokvag}?mode=ro", uri=True)
        try:
            anslutning.text_factory = str
            rader = granska_egna(anslutning)
        finally:
            anslutning.close()

        text, nagot = sammanfatta_aterstaende(rader)
        visning = QMessageBox.warning if nagot else QMessageBox.information
        visning(self.iface.mainWindow(), "Vad återstår?", text)

    def skriv_geometrier(self) -> None:
        """Zippar geometrierna for leveransen och visar vad som kom med.

        Bara geometrier: Fornreg lagrar inte attributen ur filen, sa
        beskrivning och bedomning skrivs in for hand ur leveranslistan. Se
        fornreg.py -- handledningen sager det uttryckligen.
        """
        from arkstod.faltdel import fornreg

        gpkg = self._arbetsfil("Geometrier till Fornreg")
        if gpkg is None:
            return
        try:
            resultat = fornreg.skriv(gpkg)
        except fornreg.SaknarUtgangslage:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Geometrier till Fornreg",
                "Arbetsfilen saknar utgångsläge, så det går inte att veta"
                " vad som är ändrat sedan uttaget.",
            )
            return
        except Exception as fel:  # noqa: BLE001  (allt ska nå dialogen)
            QMessageBox.critical(
                self.iface.mainWindow(), "Geometrier till Fornreg", str(fel)
            )
            return

        rader = []
        if resultat.fil:
            # Sokvagen och inte bara namnet: filen ar redan skriven, och
            # det ska framgaa att det inte finns nagot mer att gora med den
            # an att ladda upp den.
            rader.append(f"Skriven: {resultat.fil}")
            rader.append(f"{resultat.totalt} geometrier")
            rader += [
                f"  {tabell}: {antal}"
                for tabell, antal in sorted(resultat.antal.items())
            ]
            rader += [
                "",
                "Fornreg sparar inga attribut ur filen. Beskrivning och"
                " bedömning skrivs in ur leveranslistan — TID är detsamma i"
                " båda.",
            ]
        if resultat.anmarkningar:
            rader += ["", "Detta kom inte med:"]
            rader += [f"  {rad}" for rad in resultat.anmarkningar]

        QMessageBox.information(
            self.iface.mainWindow(),
            "Geometrier till Fornreg",
            chr(10).join(rader) or "Ingenting att leverera.",
        )
        if resultat.fil:
            _visa_i_utforskaren(resultat.fil)

    # -- Sammansatta lamningstyper ------------------------------------

    RUBRIK = "Sammansatta lämningar"

    def _systemlager(self):
        """Punktlagret och ytlagret, eller besked om vad som saknas."""
        projekt = QgsProject.instance()
        punkt = projekt.mapLayersByName("point")
        yta = projekt.mapLayersByName("polygon")
        if not punkt or not yta:
            QMessageBox.warning(
                self.iface.mainWindow(),
                self.RUBRIK,
                "Lagren point och polygon måste finnas i projektet.",
            )
            return None, None
        return punkt[0], yta[0]

    def foresla_system(self) -> None:
        """Kedjar delarna vid listans egna avstand och lagger ytorna.

        Reglerna kommer ur lamningstypslistan i arbetsfilen -- antal, avstand
        och ingaende typer. Bara de typer jobbets egna lamningar kan bilda
        provas; har man inte prickat en fangstgrop finns inget system att
        foresla.

        Undantaget -- avstand over listans tal dar topografin visar att
        lamningarna hor ihop -- gors inte har utan med markering.
        """
        from arkstod.faltdel import systemyta

        punktlager, ytlager = self._systemlager()
        if punktlager is None:
            return

        try:
            regler = systemyta.aktuella_regler(punktlager, ytlager)
        except Exception as fel:  # noqa: BLE001
            QMessageBox.critical(self.iface.mainWindow(), self.RUBRIK, str(fel))
            return

        if not regler:
            QMessageBox.information(
                self.iface.mainWindow(),
                self.RUBRIK,
                "Inga av jobbets egna lämningar är av en typ som kan ingå i"
                " en sammansatt lämning.",
            )
            return

        rader: list[str] = []
        for regel in regler:
            try:
                resultat = systemyta.foresla(punktlager, ytlager, regel)
            except Exception as fel:  # noqa: BLE001
                QMessageBox.critical(self.iface.mainWindow(), self.RUBRIK, str(fel))
                return

            rader.append(f"{regel.sammansatt} — minst {regel.minsta_antal},"
                         f" kedjat vid {regel.normalt_avstand} m")
            rader.append(f"  Listan: {regel.kalla}")
            if resultat.skapade:
                rader += [f"  {rad}" for rad in resultat.skapade]
            else:
                rader.append("  inga klungor nådde antalet")
            if resultat.for_faa:
                rader.append(
                    "  klungor med för få: "
                    + ", ".join(str(a) for a in sorted(resultat.for_faa, reverse=True))
                )
            if resultat.narliggande:
                rader.append(
                    "  ligger nära varandra — topografin avgör; markera dem"
                    " och använd ”Sammansatt lämning — av markerade”:"
                )
                for en, tva, meter in resultat.narliggande[:6]:
                    rader.append(f"    klunga {en + 1} och {tva + 1}: {meter} m")
            rader.append("")

        rader += ["Ytorna är utkast: beskrivningen har en lucka och den"
                  " antikvariska bedömningen är tom."]
        QMessageBox.information(
            self.iface.mainWindow(), self.RUBRIK, chr(10).join(rader)
        )
        self.iface.mapCanvas().refresh()

    def system_av_valda(self) -> None:
        """Gor en sammansatt lamning av det som ar markerat i kartan.

        Ingen avstandsprovning: den som markerat har sett terrangen. Antalet
        provas daremot -- listans minimum ar ett tal och ingen bedomning.
        """
        from arkstod.faltdel import systemyta

        punktlager, ytlager = self._systemlager()
        if punktlager is None:
            return

        try:
            regler = systemyta.aktuella_regler(punktlager, ytlager)
        except Exception as fel:  # noqa: BLE001
            QMessageBox.critical(self.iface.mainWindow(), self.RUBRIK, str(fel))
            return

        markta = {
            post["lamningstyp"]
            for post in punktlager.selectedFeatures()
            if post["lamningstyp"]
        }
        passande = [
            regel for regel in regler if markta & set(regel.ingaende)
        ]
        if not passande:
            QMessageBox.warning(
                self.iface.mainWindow(),
                self.RUBRIK,
                "De markerade lämningarna hör inte till någon sammansatt"
                " lämningstyp i listan.",
            )
            return
        if len(passande) > 1:
            namn = [regel.sammansatt for regel in passande]
            valt, ok = QInputDialog.getItem(
                self.iface.mainWindow(),
                self.RUBRIK,
                "De markerade lämningarna kan ingå i flera sammansatta typer."
                " Vilken gäller?",
                namn,
                0,
                False,
            )
            if not ok:
                return
            passande = [r for r in passande if r.sammansatt == valt]

        try:
            besked = systemyta.skapa_av_valda(punktlager, ytlager, passande[0])
        except (systemyta.ForFaa, systemyta.UtanYta) as fel:
            QMessageBox.warning(self.iface.mainWindow(), self.RUBRIK, str(fel))
            return
        except Exception as fel:  # noqa: BLE001
            QMessageBox.critical(self.iface.mainWindow(), self.RUBRIK, str(fel))
            return

        self.iface.messageBar().pushSuccess(self.RUBRIK, besked)
        self.iface.mapCanvas().refresh()

    def _arbetsfil(self, rubrik: str) -> str | None:
        """Sokvagen till projektets lamningsdatabas, eller None med besked."""
        lager = self.iface.activeLayer()
        if lager is None or not hasattr(lager, "source"):
            traffar = QgsProject.instance().mapLayersByName("point")
            lager = traffar[0] if traffar else None
        if lager is None:
            QMessageBox.information(
                self.iface.mainWindow(),
                rubrik,
                "Öppna först ett projekt med en lämningsdatabas.",
            )
            return None
        return lager.source().split("|")[0]

    def skriv_in_rattelser(self) -> None:
        """Laeser andringsfilen fran leveranslistan och skriver in den.

        Sidan kan inte skriva i GeoPackagen -- den lamnar ifran sig en fil,
        och det haer ar dorren in. Efterat skrivs listan om, sa att det man
        ser stammer med det som star i arbetsfilen.
        """
        from arkstod.faltdel.leverans import skriv as skriv_leverans
        from arkstod.faltdel.rattelse import FILNAMN, Andringsfil, tillampa_fil

        gpkg = self._arbetsfil("Rättelser")
        if gpkg is None:
            return

        # Webblasaren lagger filen i nedladdningsmappen. Bor den redan i
        # arbetsmappen ar det den som menas.
        bredvid = os.path.join(os.path.dirname(gpkg), FILNAMN)
        start = bredvid if os.path.exists(bredvid) else os.path.join(
            os.path.expanduser("~"), "Downloads", FILNAMN
        )
        vald, _ = QFileDialog.getOpenFileName(
            self.iface.mainWindow(),
            "Välj ändringsfilen från leveranslistan",
            start,
            "Ändringsfil (*.json)",
        )
        if not vald:
            return

        try:
            rapport = tillampa_fil(gpkg, vald)
        except Andringsfil as fel:
            QMessageBox.warning(self.iface.mainWindow(), "Rättelser", str(fel))
            return
        except Exception as fel:  # noqa: BLE001  (allt ska nå dialogen)
            QMessageBox.critical(self.iface.mainWindow(), "Rättelser", str(fel))
            return

        rader = [f"{rapport.antal} rättelser skrevs in i arbetsfilen."]
        if rapport.hoppade:
            rader.append("")
            rader.append("Följande hoppades över:")
            for andring, skal in rapport.hoppade:
                rader.append(f"  {andring.kolumn} i {andring.tabell}:{andring.fid} — {skal}")
        QMessageBox.information(
            self.iface.mainWindow(), "Rättelser", "\n".join(rader)
        )

        if rapport.antal:
            # Lagren maste laesa om, annars visar kartan den gamla texten.
            for lager in QgsProject.instance().mapLayers().values():
                if hasattr(lager, "reload"):
                    lager.reload()
            self.iface.mapCanvas().refresh()
            skriv_leverans(gpkg, QgsProject.instance().baseName())

    def skriv_uppslagsbok(self) -> None:
        """Skriver uppslagsboken bredvid arbetsfilen och oppnar den.

        Uttaget skriver den redan. Knappen finns for att skriva om den nar
        arbetsfilen bytt uppslag, och for att hitta tillbaka till den.
        """
        from arkstod.faltdel.uppslagsbok import skriv

        gpkg = self._arbetsfil("Uppslagsbok")
        if gpkg is None:
            return
        try:
            fil = skriv(gpkg)
        except Exception as fel:  # noqa: BLE001  (allt ska nå dialogen)
            QMessageBox.critical(self.iface.mainWindow(), "Uppslagsbok", str(fel))
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(fil)))
        self.iface.messageBar().pushSuccess(
            "Uppslagsbok", f"{os.path.basename(str(fil))} skriven och öppnad"
        )

    def skriv_leveranslista(self) -> None:
        """Skriver leveranslistan bredvid arbetsfilen och oppnar den.

        Sidan ar en fristaende HTML-fil. Den foljer med nar arbetsmappen
        kopieras till kontorsdatorn och oppnas dar utan QGIS.
        """
        from arkstod.faltdel.leverans import SaknarUtgangslage, skriv

        gpkg = self._arbetsfil("Leveranslista")
        if gpkg is None:
            return
        try:
            fil = skriv(gpkg, QgsProject.instance().baseName())
        except SaknarUtgangslage as fel:
            QMessageBox.warning(self.iface.mainWindow(), "Leveranslista", str(fel))
            return
        except Exception as fel:  # noqa: BLE001  (allt ska nå dialogen)
            QMessageBox.critical(self.iface.mainWindow(), "Leveranslista", str(fel))
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(fil)))
        self.iface.messageBar().pushSuccess(
            "Leveranslista", f"{os.path.basename(str(fil))} skriven och öppnad"
        )

    def kor(self) -> None:
        dialog = Dialog(self.iface.mainWindow())
        # exec() och DialogCode.Accepted: skrivsatten som finns i bade Qt 5
        # och Qt 6. exec_() och QDialog.Accepted finns bara i Qt 5.
        if (
            dialog.exec() != QDialog.DialogCode.Accepted
            or dialog.rapport is None
        ):
            return
        self._oppna(dialog.rapport)

    def _oppna(self, rapport) -> None:
        """Oppnar projektet i mappen. Knappen ska leda rakt in i arbetet."""
        mapp = os.path.dirname(str(rapport.arbetsfil))
        projekt = sorted(
            os.path.join(mapp, namn)
            for namn in os.listdir(mapp)
            if namn.lower().endswith(".qgz")
        )
        if not projekt:
            self.iface.messageBar().pushWarning(
                MENY, f"Uttaget är klart, men inget projekt i {mapp}"
            )
            return

        QgsProject.instance().read(projekt[-1])
        self.iface.messageBar().pushSuccess(
            MENY,
            f"{lansmodul.benamning([rapport.lan, *rapport.grannlan])} klart —"
            f" {os.path.basename(projekt[-1])} öppnat",
        )
