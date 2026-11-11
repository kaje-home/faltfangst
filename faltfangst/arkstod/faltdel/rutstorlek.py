"""Textrutornas hojd, raknad ur lanets egen data.

Formularet ritade alla textrutor lika stora, och det ar fel pa ett satt som
kostar plats dar den behovs mest. Orienteringsrutan blev nastan lika stor som
beskrivningsrutan trots att beskrivningar ar det langsta man skriver.

Det gaar att rakna ut i stallet for att gissa. Uttaget bar 25 000 lamningars
befintliga text, och den sager precis hur lang en beskrivning brukar bli i det
har lanet.

**Bredden mats en gaang, hojden raknas per uttag.** Hur manga tecken som far
plats pa en rad beror pa layouten och inte pa datan; det andras bara nar
formularet gors om, och star darfor som konstant i RUTOR. Hur manga rader som
behovs beror pa datan, och raknas nar arbetsmappen skapas -- da ar det ren
sqlite, utan Qt.

Talen i `tecken_per_rad` ar uppmatta i QGIS eget Qt pa ett formular satt till
940x560, med QFontMetrics mot ett stycke svensk lopande text. Ett snitt over
"abcdef" hade gett fel svar: gemener och mellanslag ar smalare an versaler.

De mats om nar blanketten byter typsnitt. Tahoma 11 tog blanketten fran
56,7 tecken per rad i beskrivningen till 52,8 -- gar talen isar blir
hojderna raknade pa fel bredd, och da ar hela ovningen fel.

**Korta falt far bade min och max, langa bara min.** Det ar sa utrymmet
flyttas. En ruta med tak slutar vaxa, och QGridLayout ger det den avstar till
grannarna -- det ar taket pa orienteringen som gor beskrivningen storre, inte
nagot man kan satta pa beskrivningen sjalv.

Darav ocksa varfor `hogst` ar sa laga tal. Ett minimum tvingar fonstret att
vaxa: forsta forsoket satte beskrivningen till 12 rader ur datan, och
formularet gick fran 560 till 795 pixlar hogt -- ratt hojd for texten och fel
hojd for skarmen den ska rymmas pa. Minimum ar darfor en golvniva, inte ett
onskemal, och resten far beskrivningen anda genom att grannarna slutat ta.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

# Andelen texter som ska fa plats utan att man behover rulla. Median vore for
# snalt -- halften av alla beskrivningar hade hamnat utanfor -- och max styrs
# av en enda ovanligt lang text.
ANDEL = 0.9

# Rullytan far inte mala nagon egen botten.
#
# Rapporterat: "formularet tappade sina farger, dvs fargen mellan rutorna
# och etiketterna". Blankettens rodbruna botten kommer inte fran fliksidan
# -- den malar ingenting alls -- utan fran QTabWidgets panel bakom den,
# och tabWidgets palett har Window = 170,0,0.
#
# En rullyta har en viewport, och den har autoFillBackground pa. Uppmatt:
# viewporten fyller=True med #f0f0f0. Den lade sig alltsa som ett grat ark
# over det roda, och kvar blev bara en rand langs kanten.
#
# Genomskinligt pa bada: rullytan sjalv (en stilmall pa en QAbstractScrollArea
# galler aven dess viewport) och innehallswidgeten, som ar viewportens barn.
# Barnbarnen -- etiketter och falt -- traffas inte av > > och behaller sitt.
GENOMSKINLIG = "\n".join(
    (
        "QScrollArea { background: transparent; }",
        "QScrollArea > QWidget > QWidget { background: transparent; }",
    )
)

# Kant, marginal och inre luft: skillnaden mellan radhojd*rader och den hojd
# rutan faktiskt behover for att slippa rullist.
#
# Uppmatt, inte gissad -- rutan vaxtes tills rullisten slocknade, och svaret
# var detsamma for 1 till 5 rader. Den gissade tolvan gjorde varje ruta tre
# pixlar for laag, sa en enradig ruta visade rullist for sin egen enda rad.
KANT = 15


@dataclass(frozen=True)
class Ruta:
    """En textruta i formularet, och kolumnen den skriver i."""

    namn: str
    kolumn: str
    tecken_per_rad: float
    radhojd: int
    minst: int
    hogst: int
    # Sant for den ruta som ska ta det utrymme de andra avstar fran.
    vaxer: bool = False
    # Vara egna kolumner ar tomma i ett farskt uttag och gaar inte att mata.
    forval: int = 2

    def hojd(self, rader: int) -> int:
        return rader * self.radhojd + KANT


# Uppmatt i QGIS Qt, formularet satt till 940x560. Se modulens docstring.
#
# `minst` och `hogst` ar inte data utan omdome: en ruta ska aldrig bli sa lag
# att man inte ser vad man skriver, och aldrig sa hog att fliken spricker pa
# en tiotumsskarm.
RUTOR: tuple[Ruta, ...] = (
    Ruta("beskrivning", "beskrivning", 74.7, 31, minst=3, hogst=4, vaxer=True),
    # Terrang och vegetation ar tva falt, och Fornreg 4.0 skiljer dem:
    #
    #   Terrang kring lamning (s. 60): lamningens topografiska och geologiska
    #   belagenhet samt markanvandning, skriven i tva led -- lage i terrangen
    #   och jordart, sedan markslag. "Kron av flack moranrygg (NÖ-SV).
    #   Skogsmark, tallskog."
    #
    #   Vegetation pa lamning (s. 61): vaxtlighet direkt pa lamningen, framst
    #   trad och buskar. "3 tallar och ett 10-tal sma granar pa vallen."
    #
    # Terrangen stod pa en rad for att jag last faltet som kort. Uppmatt i
    # Jamtlandsuttagets 11128 ifyllda terrangbeskrivningar: median 53 tecken,
    # 90:e percentilen 86 -- och kallans egna exempel ar 40-90 tecken.
    #
    # **Talet 82,9 ar mott om.** De har tre falten laag i en smal hogerspalt
    # och rymde 20,5 tecken per rad; pa fliken Platsen staar de i full bredd,
    # och da ryms 82,9 -- uppmatt med QFontMetrics mot ett stycke svensk
    # loepande text, som modulens docstring beskriver. Samma text tar alltsa
    # en fjardedel sa manga rader, och taket kan sankas utan att nagot
    # forsvinner: 90:e percentilen ar nu tva rader i stallet for fyra.
    Ruta("terrang", "terrang", 82.9, 31, minst=1, hogst=2),
    # Orienteringen ar ingen riktning utan en vaganvisning: "15 m V om back",
    # "20 m Ö om kraftledningsgata (NNÖ-SSV)". Den ar inte obligatorisk, men
    # den som fyllt i den har gjort det for att lamningen ska ga att hitta
    # igen -- och da ska texten synas.
    #
    # Uppmatt i Jamtlandsuttagets 1412 ifyllda orienteringar: median 30
    # tecken, 90:e percentilen 67, langsta 380. I full bredd ar 90:e
    # percentilen en enda rad.
    Ruta("orientering", "orientering", 82.9, 31, minst=1, hogst=2),
    Ruta(
        "antikvariskbedomning_motivering",
        "antikvariskbedomning_motivering",
        35.6,
        31,
        minst=2,
        hogst=2,
        # Tva rader, med tak. Rutan vaxte forut in i all slack pa fliken,
        # och da gick det inte att ge paminnelsen ovanfor mer plats -- den
        # tog bara tillbaka det man frigjorde.
        #
        # Beskedet ovanfor ar det man laser innan man skriver; rutan ar den
        # man skriver i, och den rullar utan att nagot gaar forlorat. Av de
        # tva ar det beskedet som maste synas helt.
    ),
    # Vara egna kolumner. Tomma vid uttaget, sa forvalet galler -- men de mats
    # anda, for den som skriver om formularet mitt i ett jobb ska fa nytta av
    # den text som hunnit skrivas.
    # Vegetationen ar var egen kolumn och alltsa tom i varje uttag -- det
    # finns aldrig nagot att mata, sa forvalet ar det som galler. I full
    # bredd racker tva rader for kallans langsta exempel, tre meningar om
    # syrener och parontrad.
    Ruta("veg", "veg", 82.9, 31, minst=1, hogst=2, forval=2),
    # Traditionen ar det langsta faltet pa blanketten och det enda dar en
    # enda lamning kan bara flera stycken. Uppmatt i Blekingeuttagets 319
    # ifyllda traditioner: median 83 tecken, 90:e percentilen 621, langsta
    # 3759. Nio av tio ryms alltsa inte -- 621 tecken ar atta rader -- men
    # fem rader tar 415 tecken, och resten far rullas. Ett falt som tar atta
    # rader av en flik som har fem ar inget falt utan en vagg.
    Ruta("tradition", "tradition", 82.9, 31, minst=1, hogst=5, forval=2),
    Ruta("Kommentar", "Kommentar", 35.6, 31, minst=1, hogst=3, forval=2),
    Ruta("Skadebesk", "Skadebesk", 35.6, 31, minst=1, hogst=3, forval=2),
    Ruta("ovrigt", "ovrigt", 49.6, 31, minst=1, hogst=3, forval=2),
)

# Typsnittet talen ovan ar uppmatta med. Byter blanketten typsnitt maste de
# matas om -- annars raknas hojderna pa en bredd som inte galler langre.
# Tahoma 11 tog beskrivningen fran 56,7 tecken per rad till 52,8.
MATT_MED = ("Tahoma", "11")

# Ett falt gaar med flit emot. TID ar registreringsordningen -- det tal man
# bladdrar upp och laser av vid varje lamning, med penna, i solljus. Det stod
# i 24 punkter i den gamla blanketten och det var ingen slump; jag jamnade ut
# det till 11 och fick det tillbaka. Sexton ar avvagningen: klart storre an
# resten, men inte sa stort att rutan tar en egen rad.
AVVIKANDE_GRAD = {"TID": "16"}

# Vad blanketten har att bygga pa i hojd, pa den skarm den anvands.
#
# Toughpad FZ-G1: 10,1 tum, 1920x1200. Talet stod pa 560 och utgick fran 200
# procents skalning, alltsa 960x600 logiska pixlar. Den utgangspunkten haller
# inte langre: blanketten kraver 1192 logiska pixlar i bredd -- uppmatt i ett
# riktigt QgsAttributeForm -- och 960 racker inte. Skarmen kors alltsa i 150
# procent, vilket ger 1280x800, och da finns omkring 720 pixlar kvar i hojd
# nar fonstrets egen ram raknats bort.
#
# Overskrids det har rullar fliken. Det ar inget haveri, men det ar en
# forsamring, och den ska synas som ett rott prov och inte upptackas i falt.
#
# Talet ar vad blanketten *vill* vara, inte vad den kraver. Rutornas golv ar
# en rad var, sa dialogen gaar att krympa till 562 px pa en skrivbordsskarm
# -- forut laste minimihojderna den vid 867, vilket tog nastan hela skarmen.
FORMULARHOJD = 720

# Qt:s eget "ingen grans".
OBEGRANSAT = 16777215


@dataclass
class Matning:
    """Vad lanets egen text sager om en kolumn."""

    kolumn: str
    antal: int = 0
    langd: int = 0
    rader: int = 0
    hojd: int = 0
    matt: bool = False


@dataclass
class Storleksrapport:
    matningar: list[Matning] = field(default_factory=list)
    satta: list[str] = field(default_factory=list)


def _geometritabeller(anslutning: sqlite3.Connection) -> list[str]:
    from arkstod.faltdel import utgangslage

    return utgangslage.geometritabeller(anslutning)


def _langder(anslutning: sqlite3.Connection, kolumn: str) -> list[int]:
    """Teckenlangden pa varje ifylld text i kolumnen, over alla geometrilager."""
    langder: list[int] = []
    for tabell in _geometritabeller(anslutning):
        finns = {
            rad[1]
            for rad in anslutning.execute(f'PRAGMA table_info("{tabell}")')
        }
        if kolumn not in finns:
            continue
        langder.extend(
            rad[0]
            for rad in anslutning.execute(
                f'SELECT length("{kolumn}") FROM "{tabell}"'
                f' WHERE "{kolumn}" IS NOT NULL AND trim("{kolumn}") <> \'\''
            )
        )
    return langder


def _percentil(varden: list[int], andel: float) -> int:
    ordnade = sorted(varden)
    plats = min(int(len(ordnade) * andel), len(ordnade) - 1)
    return ordnade[plats]


def mat(gpkg: Path | str) -> list[Matning]:
    """Raknar ut vilken hojd varje ruta behover i det har uttaget."""
    anslutning = sqlite3.connect(f"file:{Path(gpkg)}?mode=ro", uri=True)
    try:
        resultat = []
        for ruta in RUTOR:
            langder = _langder(anslutning, ruta.kolumn)
            matning = Matning(kolumn=ruta.kolumn, antal=len(langder))
            if langder:
                matning.matt = True
                matning.langd = _percentil(langder, ANDEL)
                rader = -(-matning.langd // int(ruta.tecken_per_rad))
            else:
                rader = ruta.forval
            matning.rader = max(ruta.minst, min(ruta.hogst, rader))
            matning.hojd = ruta.hojd(matning.rader)
            resultat.append(matning)
        return resultat
    finally:
        anslutning.close()


# Uppslagsspalten pa flik 1 far inte klamas ihop.
#
# Bredden ar fri i layouten, och vid 940 logiska pixlar -- vad en faltdator
# med 150 procents skalning ger -- tog beskrivningsraden sa mycket att
# mattrutan blev 129 px. Texten bloa da till "Fältha ndbok en: Undan", ett ord
# per rad. Uppmatt i ett riktigt QgsAttributeForm; vid 1280 px blir samma ruta
# 348 px och laser sig som en mening.
#
# Tvahundrasextio ar det matt dar handbokens satser laser sig som meningar i
# stallet for som ett ord per rad.
#
# Priset ar blankettens minsta bredd: 1061 px utan golvet, 1192 med. En
# Toughpad FZ-G1 har 1920 fysiska pixlar, vilket ger 1280 logiska vid 150
# procents skalning -- det ryms, med marginal. Vid 200 procent ger samma skarm
# 960, och da rymdes formularet inte forut heller.
UPPSLAGSBREDD = 260

# Rutorna i den spalten. De delar kolumn och maste darfor ha samma golv;
# satter man det bara pa den ena bestammer den andra anda.
SPALTRUTOR = ("mattregel", "kontextvarning")


def _satt_bredd(widget: ElementTree.Element, bredd: int) -> None:
    """Skriver minsta bredd utan att rora hojden."""
    for egenskap in widget.findall("property"):
        if egenskap.get("name") == "minimumSize":
            egenskap.find("size").find("width").text = str(bredd)
            return
    egenskap = ElementTree.SubElement(widget, "property", {"name": "minimumSize"})
    size = ElementTree.SubElement(egenskap, "size")
    ElementTree.SubElement(size, "width").text = str(bredd)
    ElementTree.SubElement(size, "height").text = "0"


def _satt_hojd(widget: ElementTree.Element, taggnamn: str, hojd: int) -> None:
    """Skriver minimumSize eller maximumSize pa en widget."""
    for egenskap in widget.findall("property"):
        if egenskap.get("name") == taggnamn:
            size = egenskap.find("size")
            if size is not None:
                size.find("height").text = str(hojd)
                bredd = size.find("width")
                if taggnamn == "maximumSize" and bredd.text in (None, ""):
                    bredd.text = "16777215"
                return
    egenskap = ElementTree.SubElement(widget, "property", {"name": taggnamn})
    size = ElementTree.SubElement(egenskap, "size")
    ElementTree.SubElement(size, "width").text = (
        "16777215" if taggnamn == "maximumSize" else "0"
    )
    ElementTree.SubElement(size, "height").text = str(hojd)


def satt_storlekar(ui: Path | str, matningar: list[Matning]) -> list[str]:
    """Skriver rutornas hojder i formularfilen. Idempotent."""
    ui = Path(ui)
    per_kolumn = {matning.kolumn: matning for matning in matningar}
    trad = ElementTree.parse(ui)
    rot = trad.getroot()

    efter_namn = {ruta.namn: ruta for ruta in RUTOR}
    satta = []
    for widget in rot.iter("widget"):
        if widget.get("name") in SPALTRUTOR:
            _satt_bredd(widget, UPPSLAGSBREDD)
        ruta = efter_namn.get(widget.get("name") or "")
        if ruta is None:
            continue
        matning = per_kolumn.get(ruta.kolumn)
        if matning is None:
            continue
        # Golvet ar en rad, inte den uppmatta hojden.
        #
        # Rutornas minimihojder summeras till formularets, och det gjorde
        # dialogen omojlig att krympa: 864x867 som minsta storlek, vilket pa
        # en skrivbordsskarm tar nastan hela hojden. Rapporterat: "nar jag
        # oppnar formularet pa min desktop tacker det hela skarmen".
        #
        # Med ett lagt golv och det uppmatta taket far rutan sin hojd nar det
        # finns plats -- faltdatorn har det -- och krymper nar det inte gor
        # det. Textrutor rullar; det ar vad de ar till for.
        _satt_hojd(widget, "minimumSize", ruta.hojd(1))
        if ruta.vaxer:
            # Ett tak som star kvar sedan tidigare hindrar rutan fran att ta
            # det grannarna avstar. Motiveringsfaltet hade 110 px i mallen,
            # och det taket hade gjort hela omfordelningen verkningslos.
            _satt_hojd(widget, "maximumSize", OBEGRANSAT)
        else:
            # Taket ar sjalva poangen: utan det vaxer en enradig ruta med
            # layouten och ater upp plats som beskrivningen behover.
            _satt_hojd(widget, "maximumSize", matning.hojd)
        satta.append(f"{ruta.namn} {matning.rader} rader ({matning.hojd} px)")

    trad.write(ui, encoding="utf-8", xml_declaration=True)
    return satta


def satt_rullning(ui: Path | str) -> list[str]:
    """Lagger varje fliks innehall i en rullyta. Idempotent.

    Faltdatorns tangentbord tar ungefar halva skarmen, och i det gamla
    verktyget krympte formularet till den andra halvan. Har gick det inte:
    blanketten kravde 864x612 logiska pixlar, och QGIS attributdialog lindar
    inte in formularet i nagon rullyta -- uppmatt: noll stycken. Under det
    maattet gaar fonstret inte att dra, hur lite plats som an finns.

    Med en rullyta per flik blir kravet innehallets bredd och nastan ingen
    hojd alls. Finns det plats syns allt som forut; finns det inte det rullar
    man till faltet man skriver i.

    `widgetResizable` ar det som far innehallet att folja bredden i stallet
    for att fa en vaagrat rullist -- utan den rullar man i sidled, och det
    ar det ingen som vill gora med penna.

    Vaagrat rullning staar dock kvar som mojlighet, for blanketten har en
    bredd den inte kan gaa under: uppmatt behover flikarna 1144, 978, 816
    och 770 pixlar. Provat att stanga av den helt -- da klipps
    hogerkolumnen i stallet, och "Antikvarisk kommentar" gaar inte att naa
    alls i ett smalt fonster. Hellre en rullist man ser an ett falt som
    inte finns. I landscape pa faltdatorn racker bredden anda; det ar
    hojden tangentbordet tar.
    """
    ui = Path(ui)
    trad = ElementTree.parse(ui)
    rot = trad.getroot()
    gjorda: list[str] = []

    for flik in rot.iter("widget"):
        if flik.get("class") != "QWidget":
            continue
        titel = flik.find('attribute[@name="title"]/string')
        if titel is None:
            continue
        namn = flik.get("name") or "flik"
        if flik.find(f'.//widget[@name="rulla_{namn}"]') is not None:
            continue
        innehall = flik.find("layout")
        if innehall is None:
            continue

        flik.remove(innehall)

        yttre = ElementTree.SubElement(
            flik, "layout", {"class": "QVBoxLayout", "name": f"rullning_{namn}"}
        )
        for kant in ("leftMargin", "topMargin", "rightMargin", "bottomMargin"):
            egenskap = ElementTree.SubElement(yttre, "property", {"name": kant})
            ElementTree.SubElement(egenskap, "number").text = "0"

        post = ElementTree.SubElement(yttre, "item")
        rulla = ElementTree.SubElement(
            post, "widget", {"class": "QScrollArea", "name": f"rulla_{namn}"}
        )
        for egenskapsnamn, tagg, varde in (
            ("widgetResizable", "bool", "true"),
            ("frameShape", "enum", "QFrame::NoFrame"),
            ("styleSheet", "string", GENOMSKINLIG),
        ):
            egenskap = ElementTree.SubElement(
                rulla, "property", {"name": egenskapsnamn}
            )
            ElementTree.SubElement(egenskap, tagg).text = varde

        inre = ElementTree.SubElement(
            rulla, "widget", {"class": "QWidget", "name": f"innehall_{namn}"}
        )

        geometri = ElementTree.SubElement(inre, "property", {"name": "geometry"})
        rect = ElementTree.SubElement(geometri, "rect")
        for tagg, varde in (("x", "0"), ("y", "0"), ("width", "900"),
                            ("height", "700")):
            ElementTree.SubElement(rect, tagg).text = varde
        inre.append(innehall)
        gjorda.append(titel.text or namn)

    if gjorda:
        trad.write(ui, encoding="utf-8", xml_declaration=True)
    return gjorda


def anpassa(ui: Path | str, gpkg: Path | str) -> Storleksrapport:
    """Mater lanets text och skriver in hojderna i formularet."""
    satt_rullning(ui)
    matningar = mat(gpkg)
    return Storleksrapport(matningar=matningar, satta=satt_storlekar(ui, matningar))
