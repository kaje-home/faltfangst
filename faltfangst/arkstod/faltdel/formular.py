"""Skriver in formularets villkor och defaultvarden i projektfilen.

Det har ar en transformation och inte en handpalaggning i QGIS gransnitt, av
tre skal. Den gaar att prova. Den gaar att koera om nar mallen byggs. Och den
gaar att koera utan att projektets data finns bredvid -- mallprojektet pekar
pa en GPKG som inte ligger i mallmappen, och att oppna det i QGIS ger en modal
dialog om saknade lager som last hela granssnittet.

Villkoren ar mjuka. Ett hart villkor hindrar att lamningen sparas i falt, och
det ar fel plats att losa problemet pa: kvallsvyn listar det som saknas.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

from arkstod.faltdel.status import (
    FORVAL_VID_NYREGISTRERING,
    MEDELFEL,
    uttryck_medelfel,
    villkor_bedomning,
    villkor_skadebeskrivning,
)
from arkstod.faltdel.uppslagsvy import satt_uppslagsvyer

# QGIS-flaggor. 4 = uttrycksvillkor; 1 = hard styrka, 2 = mjuk.
_UTTRYCKSVILLKOR = 4
_HARD = 1
_MJUK = 2



# De harledda falten i formularet. Definierade har och inte klickade fram i
# QGIS: da gaar de att prova, och mallen gaar att bygga om.
#
# Alla fyra ar nu samma sorts uttryck. Vad som staar i texten -- listans ord
# fore skiktets, falthandbokens undantag fore Exempelsamlingens princip --
# avgors vid exporten, dar det gaar att lasa och prova utan QGIS.
# Uppslagen ar inte langre virtuella falt. De rakndes om per rad, och i
# attributtabellen betyder det per rad i hela lansuttaget: uppmatt pa
# Jamtlands 25 848 punkter tog ett falt omkring 13 sekunder och fyra falt
# omkring femtio. Rapporterat fran falt: "nu gaar det valdigt segt att oppna
# attributtabellen".
#
# Kostnaden bar ingenting. Texterna behovs for **en** rad -- den lamning man
# har oppen -- och blankettkoden laser dem ur `ark_anvisning` nar formularet
# oppnas och nar lamningstypen byts. Se blankettkod.fyll_uppslagen.
#
# Namnen staar kvar for att faltens gamla rader ska ga att ta bort ur en
# mall som redan bar dem.
UPPSLAGSFALT: tuple[str, ...] = (
    "kontextvarning",
    "mattregel",
    "beskrivningsexempel",
    "motiveringspaminnelse",
)

# Det virtuella faltet `indikatorer` blev over nar indikatorlistan gjordes om
# till statisk text i formularet. Det ligger kvar i varje lager med ratt index
# och widgetkonfiguration, och aterianvands darfor som exempelfalt i stallet
# for att ett nytt falt ska plockas in for hand i sex lager.
GAMLA_FALTNAMN: dict[str, str] = {"indikatorer": "beskrivningsexempel"}

# Lagren som anvisningsuttrycken slaar upp i. `aggregate(layer:=...)` loser
# namnet mot projektets lager, inte mot GPKG:n -- en tabell som finns i filen
# men saknas i projektet ger ett tomt falt, inte ett fel. Precis det tysta
# felet som rullistan hade.
# QGIS egen symbol for "inget varde" i en ValueMap. En tom strang ar inte
# samma sak som NULL, och en ny lamning har NULL.
QGIS_NULL = "{2839923C-8B7D-419E-B84B-CA2FE9B80EC7}"

# RAA:s egna lager i uttaget. Det ar bara i dem lamningstypen valjs; att
# uppslagslagren ocksa har en kolumn med samma namn ar en tillfallighet.
GEOMETRILAGER: tuple[str, ...] = ("point", "linestring", "polygon")

UPPSLAGSLAGER: dict[str, str] = {
    "ark_anvisning": (
        "Färdig anvisningstext per lämningstyp — det formulärets fält slår upp"
    ),
    "ark_formregel": "Fälthandbokens allmänna formregler för mått",
    "ark_beskrivningsprincip": (
        "Hur lämningstypen ska beskrivas, ordagrant ur Exempelsamlingen"
    ),
    "ark_beskrivningsexempel": (
        "Färdiga beskrivningar ur Exempelsamlingen, nycklade på egenskapsvärde"
    ),
    "ark_beskrivningstillagg": (
        "Fälthandbokens förtydliganden till beskrivningsprincipen"
    ),
    "ark_avgransning": "Listans egna ”Avser inte”-satser",
}

# Lager som inte langre har nagon tabell i GPKG:n.
#
# Tre uppslag har tagits bort ur formularet, och alla tre av samma skal: de
# hangde inte pa lamningen framfor en. Indikatorlistan sags innan man oppnat
# formularet, kvallsvyns kontroller sags nar man redan last texten, och
# storningskallorna galler landskapet och inte typen man valt. Matregeln
# ersattes av Exempelsamlingens egen text.
#
# Lagret maste bort ur projektet nar tabellen forsvinner. Annars moter QGIS
# inventeraren med "Handle Unavailable Layers" -- en modal dialog som last
# granssnittet innan kartan ens ritats.
UTGANGNA_LAGER: tuple[str, ...] = (
    "ark_mattregel",
    "ark_indikator",
    "ark_storningskalla",
)

# Faltspecifik konfiguration foljer inte med en klon: den beskriver
# ursprungslagrets kolumner, och de nya lagren har andra. QGIS bygger upp
# standardkonfigurationen ur datakallan nar blocken saknas.
_KLONBORT = (
    "fieldConfiguration",
    "aliases",
    "defaults",
    "constraints",
    "constraintExpressions",
    "expressionfields",
    "attributetableconfig",
    "splitPolicies",
    "duplicatePolicies",
)

# Falthandbokens allmanna formregler for matt ar INTE ett falt per lamning.
# Texten ar identisk for varje rad, och QGIS raknar bara om ett uttrycksfalt
# nar ett falt det beror pa andras -- ett falt utan beroenden utloses aldrig,
# sa fliken stod tom vid nyregistrering och fylldes forst nar lamningen
# sparats. Reglerna ar uppslagsmaterial och skrivs in i formularet en gaang,
# nar mallen laggs ut.
FORMREGELMARKOR = "{{FORMREGLER}}"



# Value relation-faltets konfiguration. Key ar vad som lagras, Value ar vad
# som visas -- utan Value far rullistan 157 tomma rader, vilket ar precis vad
# den fick tills nagon oppnade formularet och tittade.
#
# AllowNull ar sant med flit. Med falskt forvaljer QGIS forsta posten i listan,
# och den forsta posten ar Avrattningsplats. En tyst forvald lamningstyp ar
# just det typbestamningsfel som ar allvarligare an ett bedomningsfel; nu star
# faltet tomt tills nagon valjer, och notnull-villkoret kraver ett val.
VALUE_RELATION: dict[str, dict[str, str]] = {
    "lamningstyp": {
        "Key": "benamning",
        "Value": "benamning",
        "AllowNull": "true",
        # false: QGIS sorterar da inte om listan alfabetiskt utan laser
        # lagrets egen radordning, och den ar skriven med det vanligaste
        # i lanet forst. Se _skriv_lamningstyper i lamningstyper/gpkg.py.
        "OrderByValue": "false",
        "UseCompleter": "true",
    }
}


# Matmetoder som inte har nagot medelfel, och inte ska ha nagot.
#
# Blanketten erbjuder GPS och Manuell. Det ar ett medvetet val: det ar de tva
# som anvands, och en kortare lista ar latare att arbeta i. Jag utokade den
# forst till att omfatta MEDELFEL:s alla nycklar -- DGPS och RTK -- vilket var
# att skriva over en avvagning nagon annan redan gjort.
#
# Kravet gaar at andra hallet: varje varde man kan valja ska antingen ha ett
# kant medelfel eller sta har. Manuell matning har inget, och da skrivs det
# for hand.
UTAN_MEDELFEL: tuple[str, ...] = ("Manuell",)

# Falt dar ett tomt varde maste ga att spara som tomt.
#
# Granskningsdatum hade allow_null = false. Ett tomt datum visas da som
# widgetens minsta datum, 2019-10-14, vilket ser ut som en uppgift men inte
# ar det.
#
# Nagot falskt datum skrivs daremot inte: QGIS sparar bara de attribut
# anvandaren faktiskt andrat, och ett prov -- oppna formularet, ror
# ingenting, spara -- lamnar faltet NULL med tom andringsbuffert. Det var
# min forsta slutsats och den holl inte.
#
# Det allow_null loser ar det omvanda: utan den gaar ett datum som satts av
# misstag inte att ta bort igen.
TILLAT_TOMT: tuple[str, ...] = ("Granskningsdatum",)

# Rullistornas ordning. Vanligast overst, inte alfabetiskt.
#
# QGIS lagrar en ValueMap som en ordnad lista och visar den i den ordning
# listan star i -- `placering` i det har projektet ar redan satt for hand:
# synlig, ej synlig, i byggnad. Men de listor som skapades ur ett uttag kom
# ut alfabetiskt, och alfabetisk ordning sager ingenting om hur ofta ett
# varde valjs.
#
# Foljden for bedomningen blev bakvand: "Ej kulturhistorisk lamning" stod
# overst och "Fornlamning" tredje. Det vanligaste svaret laag mitt i listan
# och det ovanligaste forst.
#
# Ordningen nedan ar inventerarens, inte min. Varden som inte namns behaller
# sin inbordes ordning och hamnar sist -- ett nytt varde i listan forsvinner
# alltsa inte, det syns bara langst ned tills nagon placerat det.
VARDEORDNING: dict[str, tuple[str, ...]] = {
    "antikvariskbedomning": (
        "Fornlämning",
        "Övrig kulturhistorisk lämning",
        "Möjlig fornlämning",
        "Ingen antikvarisk bedömning",
        "Ej kulturhistorisk lämning",
    ),
    # Graden av undersokning forst -- ingen, del, hel -- och darefter det som
    # inte ar en grad: borttagen, okand.
    #
    # "Helt undersokt" och "Borttagen utan villkor" ar de tva varden som
    # utesluter antikvarisk bedomning, se STATUSREGLER i status.py. De star
    # nu bredvid varandra, vilket de inte gjorde nar listan var alfabetisk.
    "undersokningsstatus": (
        "Ej undersökt",
        "Delundersökt",
        "Helt undersökt",
        "Borttagen utan villkor",
        "Okänd",
    ),
    # Skadan ar en skala, inte en frekvens: ingen skada, ringa, averkan, grov,
    # forstord. Okand star sist for att den inte ligger pa skalan alls.
    #
    # Regeln i status.py foljer samma grans: bara det forsta vardet, "Ej
    # skadad", slipper en skadebeskrivning. Allt darefter kraver en
    # forklaring -- ocksa "Okand", som ar en observation och ingen frisedel.
    "skadestatus": (
        "Ej skadad",
        "Ringa åverkan",
        "Åverkan",
        "Grov skada",
        "Förstörd",
        "Okänd",
    ),
}


# Falt som en gaang hade defaultuttryck och inte har det langre. De satts av
# blankettkoden i stallet -- se `_defaultvarden` for skalet -- och deras gamla
# rader maste bort ur mallen, inte bara sluta skrivas.
FLYTTADE_TILL_BLANKETTKODEN: tuple[str, ...] = ("Granskningsdatum", "TID")


def _defaultvarden() -> dict[str, tuple[str, bool]]:
    """Falt som fylls i av sig sjalva, och nar.

    Andra vardet ar `vid_andring` -- se `_satt_default` for skillnaden
    mellan ett harlett falt och ett utgangsvarde.
    """
    varden: dict[str, tuple[str, bool]] = {
        # Harlett: foljer matmetoden och raknas om varje gaang den byts.
        "medelfel": (uttryck_medelfel(), True),
        # Granskningsdatum och TID staar inte har, och det ar med flit.
        #
        # De hade defaultuttryck som saadde dem vid skapandet, medan
        # blankettkoden stamplade dem vid revidering. Tva implementationer av
        # samma regel, i tva sprak, som kunde ge olika svar -- och TID ar
        # numera verktygets primarnyckel: autotexten soker pa den, zippen
        # grupperar pa den, leveranslistan sorterar pa den, och systemet
        # binder sina delar med den. Tva satt att dela ut den ar ett for
        # manga.
        #
        # Nu finns ett satt: `blankettkod` satter bada nar nagot i
        # formularet andras, bade vid nyregistrering och vid revidering.
        # Genomgangen dar ser ocksa lamningar som annu ligger i
        # redigeringsbufferten, vilket ett aggregat i ett uttryck inte
        # sakert gor.
        #
        # Priset ar att pluginet maste vara igang. Det maste det anda --
        # utan det finns ingen arbetsmapp -- och saknas det sager QGIS ifran
        # hogt i stallet for att tyst lamna faltet tomt.
    }
    # Utgangsvarden: sas en gaang vid nyregistrering och ags darefter av den
    # som skriver. Se status.FORVAL_VID_NYREGISTRERING for kallan till vart
    # och ett -- de ar Fornregs egna, inte vaara.
    for falt, varde in FORVAL_VID_NYREGISTRERING.items():
        varden[falt] = (f"'{varde}'", False)
    return varden


@dataclass
class Villkor:
    """Ett uttrycksvillkor pa ett falt."""

    falt: str
    uttryck: str
    beskrivning: str
    # Hart villkor hindrar sparandet. Se `villkoren` for vem som far det.
    hart: bool = False


@dataclass
class Formularrapport:
    villkor: list[str] = field(default_factory=list)
    defaultvarden: list[str] = field(default_factory=list)
    virtuella_falt: list[str] = field(default_factory=list)
    value_relation: list[str] = field(default_factory=list)
    vardeordning: list[str] = field(default_factory=list)
    tillatet_tomt: list[str] = field(default_factory=list)
    omdopta_falt: list[str] = field(default_factory=list)
    tillagda_lager: list[str] = field(default_factory=list)
    uppslagsvyer: list[str] = field(default_factory=list)
    formularkod: list[str] = field(default_factory=list)


def villkoren() -> list[Villkor]:
    """Projektets villkorade obligatoriefalt, ur falthandboken."""
    return [
        Villkor(
            "antikvariskbedomning",
            villkor_bedomning(),
            "Statusvärdet utesluter antikvarisk bedömning — sätt "
            "”Ingen antikvarisk bedömning”.",
        ),
        # Hard, till skillnad fran de andra tva.
        #
        # Rapporterat: *gav en skada pa en lamning men skrev ingen
        # skadebeskrivning, gick att spara anda.* Blanketten sa ifran i
        # paminnelserutan och villkoret sa ifran vid sparandet, men bada var
        # mjuka och lat lamningen passera.
        #
        # Skalet att villkoren en gaang gjordes mjuka staar kvar for de
        # ovriga: ett hart villkor hindrar att lamningen sparas i falt, och
        # en blankett som vagrar spara ar en blankett man kringgar. Men det
        # skalet holl for falt dar svaret kan drojas till kontoret.
        # Skadebeskrivningen kan det inte: den beskriver vad man ser pa
        # platsen, och den som lamnat platsen kan inte skriva den i
        # efterhand. Handledningen for Fornreg 4.0 s. 43 sager *maste*.
        Villkor(
            "Skadebesk",
            villkor_skadebeskrivning(),
            "Skadebeskrivning krävs när skadestatus anger åverkan eller skada.",
            hart=True,
        ),
    ]


def _satt_villkor(xml: str, villkor: Villkor) -> tuple[str, int]:
    """Satter uttryck och styrka pa ett falts constraint-element."""
    antal = 0
    vald = _HARD if villkor.hart else _MJUK

    def styrka(traff: re.Match) -> str:
        nonlocal antal
        antal += 1
        rad = traff.group(0)
        rad = re.sub(r'constraints="\d+"', f'constraints="{_UTTRYCKSVILLKOR}"', rad)
        rad = re.sub(r'exp_strength="\d+"', f'exp_strength="{vald}"', rad)
        return rad

    xml = re.sub(
        rf'<constraint [^>]*field="{re.escape(villkor.falt)}"[^>]*exp_strength="\d+"[^>]*/>',
        styrka,
        xml,
    )

    def uttryck(traff: re.Match) -> str:
        return (
            f'<constraint desc="{escape(villkor.beskrivning, {chr(34): "&quot;"})}"'
            f' field="{villkor.falt}"'
            f' exp="{escape(villkor.uttryck, {chr(34): "&quot;"})}"/>'
        )

    xml = re.sub(
        rf'<constraint desc="[^"]*" field="{re.escape(villkor.falt)}" exp="[^"]*"/>',
        uttryck,
        xml,
    )
    return xml, antal


def _satt_default(
    xml: str, falt: str, uttryck: str, vid_andring: bool = False
) -> tuple[str, int]:
    """Satter defaultuttryck, och lagger till raden om den saknas.

    `vid_andring` styr QGIS applyOnUpdate och skiljer tva slags falt at.

    Ett *harlett* falt foljer ett annat och maste raknas om varje gaang:
    medelfelet foljer matmetoden, och med applyOnUpdate = 0 raknades det en
    enda gaang -- vid skapandet, nar matmetoden annu var tom. Faltet blev
    None och forblev None hur man an valde sedan.

    Ett *utgangsvarde* saas en gaang och ags darefter av den som skriver:
    autotextens beskrivning kopieras fran foregaende lamning nar punkten satts,
    och maste sluta dar -- med applyOnUpdate = 1 hade den skrivit over texten
    man just skrivit, varje gaang man rorde ett annat falt.

    Skyddet mot att skriva over nagot man matat in hor hemma i uttrycket och
    inte i flaggan. Se `_defaultvarden`: TID bar ett coalesce och behaller
    darfor ett satt nummer, medan granskningsdatumet med flit inte gor det.
    """
    kodat = escape(uttryck, {chr(34): "&quot;"})
    flagga = "1" if vid_andring else "0"
    ny = f'<default expression="{kodat}" applyOnUpdate="{flagga}" field="{falt}"/>'

    if re.search(rf'<default [^>]*field="{re.escape(falt)}"[^>]*/>', xml):
        xml, antal = re.subn(
            rf'<default [^>]*field="{re.escape(falt)}"[^>]*/>', ny, xml
        )
        return xml, antal

    # Saknas raden laggs den till, men bara i lamningslagren. Utan den
    # begransningen far uppslagstabellerna ett defaultvarde for en kolumn de
    # inte har.
    #
    # Villkoret sag forr efter matmet, oavsett vilket falt som sattes -- det
    # fungerade sa lange medelfelet var det enda defaultvardet. Att i stallet
    # leta efter faltets eget namn duger inte heller: `medelfel` laggs till
    # med ALTER TABLE och star darfor inte i projektets faltlista, aven om
    # lagret har kolumnen. QGIS laser falten ur datakallan vid oppning.
    #
    # Geometrin ar den palitliga skiljelinjen. Uppslagstabellerna registreras
    # som attributlager och bar `geometry="No geometry"`; lamningslagren gor
    # det inte.
    antal = 0

    def i_lagret(traff: re.Match) -> str:
        nonlocal antal
        block = traff.group(0)
        if 'geometry="No geometry"' in block:
            return block
        antal += 1
        return block.replace("</defaults>", ny + "</defaults>", 1)

    xml = re.sub(r"<maplayer\b.*?</maplayer>", i_lagret, xml, flags=re.DOTALL)
    return xml, antal


def _satt_formularkod(xml: str) -> tuple[str, int]:
    """Pekar ut blankettens initfunktion i lamningslagren. Idempotent.

    QGIS anropar funktionen varje gaang ett formular oppnas och skickar med
    dialogen. Det ar den enda vagen att fa en knapp i en .ui-fil att gora
    nagot -- Qt Designer har ingen slot som oppnar en fil.

    **Projektet bar namnet, inte koden.** Kallan satts till 3, som ar
    QgsEditFormConfig.CodeSourceEnvironment: funktionen finns redan i tolken,
    lagd dit av pluginet. Forsta forsoket skrev in kallkoden i projektet
    (CodeSourceDialog, 2) och det fungerade inte -- se blankettkod.py, QGIS
    kor inte python som ligger i en projektfil utan att fraaga forst.

    Kodrutan toms med flit. Later man en gammal kopia sta kvar ar den dels
    dod kod, dels nagot som far QGIS att fraaga om projektets python i onodan.
    """
    from arkstod.faltdel import blankettkod

    namn = blankettkod.initfunktion()
    antal = 0

    def i_lagret(traff: re.Match) -> str:
        nonlocal antal
        block = traff.group(0)
        if 'geometry="No geometry"' in block:
            return block
        fore = block
        block = re.sub(
            r"<editforminit\s*/>|<editforminit>.*?</editforminit>",
            f"<editforminit>{namn}</editforminit>",
            block,
            flags=re.DOTALL,
        )
        block = re.sub(
            r"<editforminitcodesource>\d*</editforminitcodesource>",
            "<editforminitcodesource>3</editforminitcodesource>",
            block,
        )
        block = re.sub(
            r"<editforminitcode>.*?</editforminitcode>",
            "<editforminitcode></editforminitcode>",
            block,
            flags=re.DOTALL,
        )
        if block != fore:
            antal += 1
        return block

    xml = re.sub(r"<maplayer\b.*?</maplayer>", i_lagret, xml, flags=re.DOTALL)
    return xml, antal


def satt_formularregler(qgz: Path | str) -> Formularrapport:
    """Skriver in villkor och defaultvarden i projektet. Idempotent."""
    qgz = Path(qgz)
    with zipfile.ZipFile(qgz) as arkiv:
        poster = {post.filename: arkiv.read(post.filename) for post in arkiv.infolist()}

    rapport = Formularrapport()
    for namn, innehall in list(poster.items()):
        if not namn.lower().endswith(".qgs"):
            continue
        xml = innehall.decode("utf-8")
        # Lagren forst: uttrycken nedan slaar upp i dem.
        xml, lagda = _sakerstall_uppslagslager(xml)
        rapport.tillagda_lager.extend(lagda)
        # Sedan hur de visas. Maste ligga efter lagren -- de sex som klonas
        # har varken alias eller kolumnval fran borjan.
        xml, stallda = satt_uppslagsvyer(xml)
        rapport.uppslagsvyer.extend(stallda)
        # Sedan namnbytet: uttrycket ska skrivas till det nya namnet.
        for fran, till in GAMLA_FALTNAMN.items():
            xml, antal = _byt_faltnamn(xml, fran, till)
            if antal:
                rapport.omdopta_falt.append(f"{fran} → {till} ({antal} ställen)")
        for villkor in villkoren():
            xml, antal = _satt_villkor(xml, villkor)
            if antal:
                rapport.villkor.append(f"{villkor.falt} ({antal} lager)")
        for faltnamn, (uttryck, vid_andring) in _defaultvarden().items():
            xml, antal = _satt_default(xml, faltnamn, uttryck, vid_andring)
            if antal:
                rapport.defaultvarden.append(f"{faltnamn} ({antal} lager)")
        for faltnamn, installningar in VALUE_RELATION.items():
            xml, antal = _satt_value_relation(xml, faltnamn, installningar)
            if antal:
                rapport.value_relation.append(f"{faltnamn} ({antal} lager)")
        for faltnamn, ordning in VARDEORDNING.items():
            xml, antal, saknade = _satt_vardeordning(xml, faltnamn, ordning)
            if antal:
                besked = f"{faltnamn} ({antal} lager)"
                if saknade:
                    besked += " — saknade värden: " + ", ".join(saknade)
                rapport.vardeordning.append(besked)
        xml, kodade = _satt_formularkod(xml)
        if kodade:
            rapport.formularkod.append(f"uppslagsboken ({kodade} lager)")
        for faltnamn in FLYTTADE_TILL_BLANKETTKODEN:
            xml, borttagna = _rensa_default(xml, faltnamn)
            if borttagna:
                rapport.defaultvarden.append(f"{faltnamn} (togs bort)")
        xml, tak = _satt_lopnummertak(xml)
        if tak:
            rapport.tillatet_tomt.append(f"TID upp till {LOPNUMMERTAK}")
        for faltnamn in TILLAT_TOMT:
            xml, antal = _satt_tillat_tomt(xml, faltnamn)
            if antal:
                rapport.tillatet_tomt.append(f"{faltnamn} ({antal} lager)")
        for faltnamn in UPPSLAGSFALT:
            xml, antal = _rensa_virtuellt_falt(xml, faltnamn)
            if antal:
                rapport.virtuella_falt.append(f"{faltnamn} (togs bort)")
        poster[namn] = xml.encode("utf-8")

    with zipfile.ZipFile(qgz, "w", zipfile.ZIP_DEFLATED) as arkiv:
        for namn, innehall in poster.items():
            arkiv.writestr(namn, innehall)
    return rapport


def _lagerid(namn: str) -> str:
    """Ett stabilt lager-id ur namnet.

    QGIS satter en UUID. Har behovs bara att det ar unikt och att det blir
    detsamma varje gaang mallen byggs om -- annars far projektet ett nytt id
    for samma lager vid varje korning, och diffen blir omojlig att lasa.
    """
    summa = hashlib.md5(namn.encode("utf-8")).hexdigest()
    delar = (summa[:8], summa[8:12], summa[12:16], summa[16:20], summa[20:32])
    return namn + "_" + "_".join(delar)


def _lagerblock(xml: str, namn: str) -> tuple[str | None, str | None]:
    """Lagrets tva block: definitionen och raden i lagerlistan."""
    definition = re.search(
        rf"<maplayer\b(?:(?!</maplayer>).)*?<layername>{re.escape(namn)}</layername>"
        r".*?</maplayer>",
        xml,
        re.S,
    )
    trad = re.search(
        rf'<layer-tree-layer[^>]*name="{re.escape(namn)}".*?</layer-tree-layer>',
        xml,
        re.S,
    )
    return (
        definition.group(0) if definition else None,
        trad.group(0) if trad else None,
    )


def _klona_lager(mall: str, tradmall: str, namn: str, beskrivning: str) -> tuple[str, str]:
    """Gor om en lagerklon till ett nytt uppslagslager."""
    gammalt = re.search(r"<layername>(.*?)</layername>", mall).group(1)
    gammalt_id = re.search(r"<id>(.*?)</id>", mall).group(1)
    nytt_id = _lagerid(namn)

    definition = mall
    for block in _KLONBORT:
        definition = re.sub(
            rf"<{block}\b.*?</{block}>|<{block}\b[^>]*/>", "", definition, flags=re.S
        )
    definition = definition.replace(gammalt_id, nytt_id)
    definition = definition.replace(f"layername={gammalt}", f"layername={namn}")
    definition = definition.replace(
        f"<layername>{gammalt}</layername>", f"<layername>{namn}</layername>"
    )
    definition = re.sub(
        r"<abstract>.*?</abstract>",
        f"<abstract>{escape(beskrivning)}</abstract>",
        definition,
        count=1,
        flags=re.S,
    )

    trad = tradmall.replace(gammalt_id, nytt_id)
    trad = trad.replace(f'name="{gammalt}"', f'name="{namn}"')
    trad = trad.replace(f"layername={gammalt}", f"layername={namn}")
    return definition, trad


def _sakerstall_uppslagslager(xml: str) -> tuple[str, list[str]]:
    """Ser till att anvisningarnas uppslagslager finns i projektet.

    Lagren laggs till som kloner av ett befintligt attributlager i stallet
    for att skrivas fran grunden: ett maplayer-block ar 15 kB, och det mesta
    ar stil och metadata som ska vara likadan.
    """
    lagda: list[str] = []

    # Mallen tas ur ett lager som faktiskt finns och som blir kvar.
    # ark_motivering har samma form som de nya -- attributlager utan geometri.
    # De utgangna provas sist: de duger som mall, men bara om inget annat
    # finns, eftersom de tas bort langre ned.
    mall = tradmall = None
    for kandidat in ("ark_motivering", "ark_uteslutning", *UTGANGNA_LAGER):
        mall, tradmall = _lagerblock(xml, kandidat)
        if mall and tradmall:
            break
    if not mall or not tradmall:
        return xml, lagda

    for namn, beskrivning in UPPSLAGSLAGER.items():
        if f"<layername>{namn}</layername>" in xml:
            continue
        definition, trad = _klona_lager(mall, tradmall, namn, beskrivning)
        xml = xml.replace("</projectlayers>", definition + "\n  </projectlayers>", 1)
        xml = xml.replace(tradmall, tradmall + "\n      " + trad, 1)
        lagda.append(namn)

    # Det utgangna lagret tas bort sist -- det kan ha varit mall ovan.
    for namn in UTGANGNA_LAGER:
        xml = _ta_bort_lager(xml, namn)
    return xml, lagda


def _ta_bort_lager(xml: str, namn: str) -> str:
    """Tar bort ett lager ur projektets alla forteckningar.

    QGIS for lagret i fem register, inte ett: sjalva definitionen, raden i
    lagerlistan, den aldre legend-sektionen, ritordningen och de listor som
    kartteman bygger pa. Lamnas nagon av dem kvar namner projektet ett lager
    som inte finns -- QGIS klagar inte, men filen pastar nagot osant.
    """
    definition, trad = _lagerblock(xml, namn)
    lagerid = None
    if definition:
        traff = re.search(r"<id>(.*?)</id>", definition)
        lagerid = traff.group(1) if traff else None
    if not lagerid:
        # Lagret kan sakna definition men finnas kvar i forteckningarna.
        traff = re.search(rf'id="({re.escape(namn)}_[^"]*)"', xml)
        lagerid = traff.group(1) if traff else None

    for block in (definition, trad):
        if block:
            xml = xml.replace(block, "", 1)

    xml = re.sub(
        rf'<legendlayer\b[^>]*name="{re.escape(namn)}".*?</legendlayer>',
        "",
        xml,
        flags=re.S,
    )
    if lagerid:
        kodat = re.escape(lagerid)
        xml = re.sub(rf'\s*<layer id="{kodat}"\s*/>', "", xml)
        xml = re.sub(rf"\s*<item>{kodat}</item>", "", xml)
    return xml


def _byt_faltnamn(xml: str, fran: str, till: str) -> tuple[str, int]:
    """Byter ett faltnamn overallt dar projektet namner det som falt.

    QGIS namner ett falt pa flera stallen -- <field name=>, <alias field=>,
    <editable>, <labelOnTop>, <constraint field=>, fieldConfiguration. Bytet
    maste traffa alla, annars blir konfigurationen foraldralos och QGIS
    tappar widgeten.

    Monstret kraver att namnet star som helt attributvarde. Ett rakt
    stangbyte skulle traffa lagernamnet `ark_indikator` och tabellrader
    dar ordet ingaar i lopande text.
    """
    antal = 0
    for attribut in ("name", "field"):
        xml, traffar = re.subn(
            rf'(?<= {attribut}=")({re.escape(fran)})(?=")', till, xml
        )
        antal += traffar
    return xml, antal


def _rensa_virtuellt_falt(xml: str, namn: str) -> tuple[str, int]:
    """Tar bort ett virtuellt falt ur alla lager.

    Att sluta skriva uttrycket tar inte bort faltet ur en mall som redan bar
    det, och sa lange raden staar kvar raknas den om per rad. Widgeten i
    blanketten heter likadant och fylls av blankettkoden i stallet.

    Borttagningen sker inne i `<expressionfields>` och inte i hela filen:
    `<field name="...">` staar ocksa i faltkonfigurationen, och den ska inte
    rors. Attributens ordning varierar mellan QGIS versioner, sa raden
    kanns igen pa sitt namn och inget annat.
    """
    antal = 0

    def i_blocket(traff: re.Match) -> str:
        nonlocal antal
        block, byten = re.subn(
            rf'\s*<field\b[^>]*\bname="{re.escape(namn)}"[^>]*/>',
            "",
            traff.group(0),
        )
        antal += byten
        return block

    xml = re.sub(
        r"<expressionfields>.*?</expressionfields>",
        i_blocket,
        xml,
        flags=re.DOTALL,
    )
    return xml, antal

def _satt_tillat_tomt(xml: str, falt: str) -> tuple[str, int]:
    """Later ett tomt varde sparas som tomt.

    Med allow_null = false visar en tom datumruta widgetens minsta datum och
    skriver in det vid sparning -- en uppgift som ser riktig ut och inte ar
    det.
    """
    antal = 0

    def i_faltet(traff: re.Match) -> str:
        nonlocal antal
        block = traff.group(0)
        ny, byten = re.subn(
            r'<Option type="bool" value="false" name="allow_null"/>',
            '<Option type="bool" value="true" name="allow_null"/>',
            block,
        )
        antal += byten
        return ny

    xml = re.sub(
        rf'<field name="{re.escape(falt)}"[^>]*>.*?</field>',
        i_faltet,
        xml,
        flags=re.DOTALL,
    )
    return xml, antal


# Lopnumrets tak i projektets faltinstallning. Rutan stod pa 1000, och det
# ar ett tal nagon satt en gaang utan att mena nagot med det -- en storre
# inventering slaar i det, och da gaar lamningen inte att numrera alls.
LOPNUMMERTAK = 99999


def _rensa_default(xml: str, falt: str) -> tuple[str, int]:
    """Tar bort ett defaultvarde som inte ska finnas kvar.

    Att sluta skriva en rad tar inte bort den ur en mall som redan bar den.
    Granskningsdatum och TID satts numera av blankettkoden; laag deras gamla
    uttryck kvar hade bada mekanismerna varit igang samtidigt.
    """
    return re.subn(rf'<default [^>]*field="{re.escape(falt)}"[^>]*/>', "", xml)


def _satt_lopnummertak(xml: str) -> tuple[str, int]:
    """Hojer TID:s ovre grans i faltets Range-installning."""
    antal = 0

    def i_faltet(traff: re.Match) -> str:
        nonlocal antal
        block = traff.group(0)
        ny, byten = re.subn(
            r'<Option type="int" value="\d+" name="Max"/>',
            f'<Option type="int" value="{LOPNUMMERTAK}" name="Max"/>',
            block,
        )
        antal += byten
        return ny

    return re.sub(
        r'<field name="TID"[^>]*>.*?</field>', i_faltet, xml, flags=re.DOTALL
    ), antal


def _satt_value_relation(
    xml: str, falt: str, installningar: dict[str, str]
) -> tuple[int, int]:
    """Satter noycklarna i ett value relation-falts konfiguration."""
    antal = 0

    def i_faltet(traff: re.Match) -> str:
        nonlocal antal
        block = traff.group(0)
        if 'type="ValueRelation"' not in block:
            return block
        antal += 1
        for nyckel, varde in installningar.items():
            typ = "bool" if varde in ("true", "false") else "QString"
            rad = f'<Option value="{varde}" name="{nyckel}" type="{typ}"/>'
            monster = rf'<Option [^>]*name="{nyckel}"[^>]*/>'
            if re.search(monster, block):
                block = re.sub(monster, rad, block)
            else:
                block = block.replace(
                    '<Option type="Map">', '<Option type="Map">' + rad, 1
                )
        return block

    # Faltet bar attribut -- `<field name="lamningstyp" configurationFlags=...>`
    # -- sa monstret far inte forutsatta att taggen slutar direkt efter namnet.
    xml = re.sub(
        rf'<field name="{re.escape(falt)}"[^>]*>.*?</field>',
        i_faltet,
        xml,
        flags=re.DOTALL,
    )
    return xml, antal


# En post i en ValueMap: en Map med ett enda self-closing Option i sig.
# Listans egen omslutande Map foljs av <Option type="List">, inte av ett
# self-closing element, sa monstret traffar bara posterna.
_VARDEPOST = re.compile(r'<Option type="Map">\s*<Option [^>]*/>\s*</Option>')
_VARDET = re.compile(r'value="([^"]*)"')


def _satt_vardeordning(
    xml: str, falt: str, ordning: tuple[str, ...]
) -> tuple[str, int, list[str]]:
    """Ordnar ett ValueMap-falts varden efter `ordning`.

    Idempotent: att ordna en redan ordnad lista ar ingen andring.

    Varden som inte namns i `ordning` behaller sin inbordes ordning sist.
    Namn i `ordning` som inte finns i projektet lamnas tillbaka som saknade
    -- ett stavfel har vore annars osynligt, och just den sortens tysta
    verkningsloshet har bitit har forut.
    """
    antal = 0
    sedda: set[str] = set()

    def i_faltet(traff: re.Match) -> str:
        nonlocal antal
        block = traff.group(0)
        if 'type="ValueMap"' not in block:
            return block
        poster = list(_VARDEPOST.finditer(block))
        if len(poster) < 2:
            return block

        def varde(post: re.Match) -> str:
            traffad = _VARDET.search(post.group(0))
            return traffad.group(1) if traffad else ""

        sedda.update(varde(post) for post in poster)

        def plats(post: re.Match) -> int:
            namn = varde(post)
            return ordning.index(namn) if namn in ordning else len(ordning)

        # sorted ar stabil, sa onamnda varden behaller sin ordning.
        omsorterade = sorted(poster, key=plats)
        antal += 1
        # Mellanrummet mellan tva poster ar radbrytning och indrag; det ar
        # samma mellan alla, sa det duger som skarv.
        skarv = block[poster[0].end() : poster[1].start()]
        return (
            block[: poster[0].start()]
            + skarv.join(post.group(0) for post in omsorterade)
            + block[poster[-1].end() :]
        )

    xml = re.sub(
        rf'<field name="{re.escape(falt)}"[^>]*>.*?</field>',
        i_faltet,
        xml,
        flags=re.DOTALL,
    )
    saknade = [namn for namn in ordning if namn not in sedda] if sedda else []
    return xml, antal, saknade


def valjbara_varden(qgz: Path | str) -> dict[str, list[str]]:
    """Vilka varden varje rullistefalt tillater, last ur projektet.

    Kallan ar formularets egna ValueMap-listor. Att skriva av dem pa nagot
    annat stalle vore att skapa en andra sanning som tyst kan ga isar med
    den forsta -- och ett statusvarde som inte finns i listan slar sonder
    statusreglerna utan att nagot sager ifran.

    Ordningen bevaras: den ar satt i VARDEORDNING och ska se likadan ut var
    an varden valjs.
    """
    from arkstod.faltdel.projekt import las_projektfil

    xml = las_projektfil(Path(qgz))
    listor: dict[str, list[str]] = {}
    for traff in re.finditer(
        r'<field name="([^"]+)"[^>]*>(.*?)</field>', xml, re.DOTALL
    ):
        falt, block = traff.group(1), traff.group(2)
        if 'type="ValueMap"' not in block or falt in listor:
            continue
        varden = [
            match.group(1)
            for post in _VARDEPOST.finditer(block)
            if (match := _VARDET.search(post.group(0)))
        ]
        if varden:
            listor[falt] = varden
    return listor


# Vilken raknad kolumn som galler for vilket lager. `ark_lamningstyp` bar
# antalet per geometrisort ur lansuttaget, och det ar den rakningen som ska
# styra rullistan: ritar man en yta ar fangstgropen inte trolig.
RAKNAT_PER_LAGER: dict[str, str] = {
    "point": "antal_punkt",
    "linestring": "antal_linje",
    "polygon": "antal_yta",
}


def _typer_i_vanlighetsordning(
    gpkg: Path, kolumn: str, sammansatta_sist: bool
) -> list[str]:
    """Lamningstyperna, vanligast forst for den har geometrisorten.

    Tre grupper, i den har ordningen:

    1. typer som forekommer i lanet med den geometrin, vanligast forst
    2. sammansatta typer som forekommer, vanligast forst -- om
       `sammansatta_sist`
    3. resten i bokstavsordning

    De tjugotva sammansatta typerna ar behallare: Fangstgropssystem,
    Gravfalt, Hagnadssystem, Omrade med fossil akermark. Man ritar dem runt
    delar man redan registrerat, och det gors pa kontoret -- i falt prickar
    man in de enskilda fangstgroparna.

    Fangstgropssystem laag darfor trea i punktlistan, vilket ar sant om
    registret och fel om arbetet. Rapporterat fran falt. I ytlistan star de
    kvar i vanlig ordning: nar man vaeljer att rita en yta ar en behallare
    just vad man ritar.

    Grupp tre gaar fortfarande att valja -- ett lan far sin forsta yta av en
    typ nan gaang, och det ska inte vara omojligt att registrera.
    """
    anslutning = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    try:
        efter = "sammansatt ASC, " if sammansatta_sist else ""
        return [
            rad[0]
            for rad in anslutning.execute(
                'SELECT benamning FROM "ark_lamningstyp"'
                f' ORDER BY ("{kolumn}" > 0) DESC, {efter}'
                f' "{kolumn}" DESC, benamning COLLATE NOCASE'
            )
        ]
    finally:
        anslutning.close()


def satt_typlista(qgz: Path | str, gpkg: Path | str) -> int:
    """Skriver lamningstypernas rullista, en egen ordning per geometrisort.

    Rullistan var en ValueRelation mot `ark_lamningstyp`, och den gaar inte
    att ordna fritt: QGIS sorterar alltid, pa vardet om OrderByValue ar sant
    och annars pa nyckeln. Provat i QGIS eget Qt med fyra uppsattningar --
    nyckeln `fid` gav radordningen, `benamning` gav bokstavsordning oavsett
    OrderByValue. Och nyckeln maste vara benamningen, for det ar den som
    lagras i lamningen.

    En ValueMap bevarar daremot listans ordning. Den bakar in vardena i
    projektfilen, och det var en gaang skalet till att lamningstypen flyttades
    *ur* en ValueMap: den var skriven ur ett lansuttag och saknade 41 av
    listans typer. Det skalet galler inte har -- listan skrivs vid uttaget ur
    samma tabell som annars slagits upp, sa alla 157 foljer med.

    **Ordningen ar olika per lager.** Fangstgropen ar lanets vanligaste punkt
    och nastan aldrig en yta; att lagga den overst i ytlagret vore att lagga
    det osannolika forst. Och de sammansatta typerna staar sist bland dem som
    forekommer i punkt- och linjelistan -- se _typer_i_vanlighetsordning.

    **Forsta posten ar tom, och maste bara QGIS egen NULL-symbol.** En tom
    strang duger inte: en ny lamning har NULL, inte tomt, och matchar da
    ingen post alls -- listan oppnades langst ned och man fick rulla hela
    vagen tillbaka. Rapporterat fran falt tva ganger, forsta gangen "botten"
    och andra gangen "mitten".

    Symbolen ar QgsValueMapFieldFormatter.NULL_VALUE, en GUID. Att den ar
    ratt ar inte laest ur dokumentationen utan sett: QGIS fick skriva en
    ValueMap med en tom post, och sa har ser den ut.
    """
    qgz, gpkg = Path(qgz), Path(gpkg)

    def poster_for(lager: str) -> str:
        typer = _typer_i_vanlighetsordning(
            gpkg, RAKNAT_PER_LAGER[lager], sammansatta_sist=lager != "polygon"
        )
        rader = [
            '<Option type="Map">'
            f'<Option type="QString" value="{QGIS_NULL}" name=""/>'
            "</Option>"
        ]
        rader += [
            '<Option type="Map">'
            f'<Option type="QString" value="{escape(typ, {chr(34): "&quot;"})}"'
            f' name="{escape(typ, {chr(34): "&quot;"})}"/>'
            "</Option>"
            for typ in typer
        ]
        return (
            '<editWidget type="ValueMap"><config><Option type="Map">'
            f'<Option type="List" name="map">{"".join(rader)}</Option>'
            "</Option></config></editWidget>"
        )

    with zipfile.ZipFile(qgz) as arkiv:
        innehall = {p.filename: arkiv.read(p.filename) for p in arkiv.infolist()}

    antal = 0
    for namn, data in list(innehall.items()):
        if not namn.lower().endswith(".qgs"):
            continue
        xml = data.decode("utf-8")

        # Bara geometrilagren. Uppslagslagren -- ark_anvisning, ark_motivering
        # och de andra -- har ocksa en kolumn som heter lamningstyp, och en
        # oavgransad sokning stamplade en lista pa 157 varden i vart och ett.
        for lager in GEOMETRILAGER:
            ny_widget = poster_for(lager)

            def i_faltet(traff: re.Match) -> str:
                nonlocal antal
                block, byten = re.subn(
                    r'<editWidget type="[^"]*">.*?</editWidget>',
                    lambda _: ny_widget,
                    traff.group(0),
                    count=1,
                    flags=re.DOTALL,
                )
                antal += byten
                return block

            def i_lagret(lagertraff: re.Match) -> str:
                return re.sub(
                    r'<field name="lamningstyp"[^>]*>.*?</field>',
                    i_faltet,
                    lagertraff.group(0),
                    flags=re.DOTALL,
                )

            xml = re.sub(
                rf"<maplayer[^>]*>(?:(?!</maplayer>).)*?"
                rf"<layername>{lager}</layername>(?:(?!</maplayer>).)*?</maplayer>",
                i_lagret,
                xml,
                flags=re.DOTALL,
            )
        innehall[namn] = xml.encode("utf-8")

    with zipfile.ZipFile(qgz, "w", zipfile.ZIP_DEFLATED) as arkiv:
        for namn, data in innehall.items():
            arkiv.writestr(namn, data)
    return antal


def _satt_kryssruta(block: str, falt: str) -> str:
    """Ger faltet en kryssruta som lagrar 1 och 0.

    `autotext` laggs till med ALTER TABLE och staar darfor inte i projektets
    faltlista. Utan en egen widget gissar QGIS -- och en heltalskolumn utan
    besked blir en skrivruta, inte en kryssruta. Talen maste ocksa sagas ut:
    utan CheckedState skriver QGIS sant och falskt som text.
    """
    widget = (
        f'<field name="{falt}" configurationFlags="NoFlag">'
        '<editWidget type="CheckBox"><config><Option type="Map">'
        '<Option name="CheckedState" value="1" type="QString"/>'
        '<Option name="UncheckedState" value="0" type="QString"/>'
        "</Option></config></editWidget></field>"
    )
    monster = rf'<field name="{falt}"[^>]*>.*?</field>'
    if re.search(monster, block, re.DOTALL):
        return re.sub(monster, lambda _: widget, block, count=1, flags=re.DOTALL)
    return block.replace("</fieldConfiguration>", widget + "</fieldConfiguration>", 1)


def satt_autotext(qgz: Path | str) -> list[str]:
    """Ger `autotext` sin kryssruta och sitt utgangslage.

    **Sjalva arvet gors inte har.** Det satt forr som ett defaultuttryck pa
    `beskrivning` -- alltsa i det ogonblick lamningen skapas -- och da har
    man annu inte sagt vad det ar. Uttrycket kunde darfor omojligt ta hansyn
    till lamningstypen, och efter sex kolbottnar fick en fangstgrop
    kolbottentexten. Arvet ligger nu i blankettkod.py och utloses av att man
    valjer typ. Ett kvarlamnat defaultvarde pa beskrivningen skulle bara
    hinna fore, sa det tas bort om det staar kvar.

    Kvar har ar tva saker som hor till projektet och inte till stunden:
    kryssrutan, och att den borjar urbockad. `autotext` laggs till med ALTER
    TABLE och staar darfor inte i projektets faltlista -- utan besked gissar
    QGIS en skrivruta, och utan utgangsvarde blir faltet NULL, vilket i en
    kryssruta inte ar urbockat utan obestamt. Det visades ibockat.
    """
    qgz = Path(qgz)
    with zipfile.ZipFile(qgz) as arkiv:
        innehall = {p.filename: arkiv.read(p.filename) for p in arkiv.infolist()}

    satta: list[str] = []
    for namn, data in list(innehall.items()):
        if not namn.lower().endswith(".qgs"):
            continue
        xml = data.decode("utf-8")
        for lager in GEOMETRILAGER:
            borjan = xml.find(f"<layername>{lager}</layername>")
            if borjan < 0:
                continue
            borjan = xml.rfind("<maplayer", 0, borjan)
            # Slut-taggen maste med. _satt_default lagger till en saknad rad
            # genom att soka <maplayer>...</maplayer>, och ett block utan sin
            # slut-tagg matchar inte -- da blev `autotext` tyst utan default.
            slutet = xml.find("</maplayer>", borjan) + len("</maplayer>")
            block = xml[borjan:slutet]
            block = re.sub(
                r'<default [^>]*field="beskrivning"[^>]*/>', "", block
            )
            block, _ = _satt_default(block, "autotext", "0")
            block = _satt_kryssruta(block, "autotext")
            xml = xml[:borjan] + block + xml[slutet:]
            satta.append(lager)
        innehall[namn] = xml.encode("utf-8")

    with zipfile.ZipFile(qgz, "w", zipfile.ZIP_DEFLATED) as arkiv:
        for namn, data in innehall.items():
            arkiv.writestr(namn, data)
    return satta
