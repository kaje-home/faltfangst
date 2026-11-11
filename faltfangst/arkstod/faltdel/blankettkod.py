"""Koden som QGIS kor nar blanketten oppnas.

QGIS anropar en funktion vid varje oppnat formular och skickar med dialogen
-- `editforminit`. Har gors tva saker med den: knappen till uppslagsboken
kopplas, och besoket stamplas.

**Funktionen kommer fran pluginet och inte fran projektfilen.** Forsta
forsoket skrev in kallkoden i qgz-filen -- QGIS kallar det CodeSourceDialog
-- och gav i QGIS `NameError: name ... is not defined`. Skalet ar att QGIS
sedan 3.36 har `Qgis.PythonEmbeddedMode`, och att den staar pa **Ask**:
python som ligger *i ett projekt* ar en sakerhetsfraaga, sa QGIS vagrar tills
nagon uttryckligen sagt ja. Koden kordes aldrig, men anropet gjordes anda.

Pluginet ar daremot redan installerad och godkand programvara. Det som star
i projektet ar bara *namnet* -- `editforminitcodesource = 3`, Environment --
och `registrera()` lagger funktionen dar QGIS letar.

Varfor stampeln ligger har och inte i ett defaultuttryck
--------------------------------------------------------

Granskningsdatum och TID hade defaultuttryck med `applyOnUpdate = 1`, och de
fyrade aldrig vid revidering. Uppmatt i QGIS:

    TID                beror pa falten: ['TID']
    Granskningsdatum   beror pa falten: []
    medelfel           beror pa falten: ['matmet']

QGIS raknar om ett defaultvarde nar ett falt **som uttrycket beror pa**
andras -- inte vid vilken andring som helst. `to_date(now())` namner inget
falt alls och kunde darfor aldrig raknas om; `coalesce("TID", ...)` namner
bara sig sjalvt. `medelfel` namner `matmet` och har alltid fungerat. Samma
flagga, tre olika utfall, och skillnaden var vilka falt uttrycket namnde.

Det gaar att lura -- namn ett falt man brukar andra -- men det vore en fint
som ser ut som ett misstag. Har gors i stallet det som faktiskt menas: nar
nagot i formularet andras ar det ett besok, och da stamplas dagens datum och
nasta lediga lopnummer. En gaang per oppnat formular, sa att ett datum man
skriver for hand darefter staar kvar.

Defaultuttrycken ar kvar for **nyregistrering**: dar racker de, for QGIS
raknar ut dem nar lamningen skapas och innan formularet visas.

Och varfor autotexten flyttade hit
----------------------------------

Beskrivningen arvdes fran forra lamningen genom ett defaultuttryck, alltsa
ocksa i det ogonblick lamningen skapas. Da har man annu inte sagt vad det
ar. Uttrycket kunde darfor omojligt ta hansyn till lamningstypen, och efter
sex kolbottnar fick en fangstgrop kolbottentexten.

Nar valet av typ ar det som utloser arvet loser sig bada delarna: texten
kommer fran forra lamningen **av samma typ**, och den kommer i den stund
man sagt vilken typ det ar.
"""

from __future__ import annotations

from arkstod.faltdel.status import (
    BEKRAFTAD,
    FORSTORD,
    INGEN_BEDOMNING,
    MOJLIG_FORNLAMNING,
    OBEKRAFTAD,
    UTAN_BEDOMNING,
    bedomning_for_typ,
    kraver_faltbesok,
    kraver_obekraftad,
    geometriregel,
    kraver_skadebeskrivning,
    kraver_tradition,
    medelfel_over_taket,
    saknar_hanvisning,
    utesluter_bedomning,
)

# Knappens objectName i blanketten. Bade .ui-filen och koden nedan anvander
# samma namn, sa det staar pa ett stalle.
KNAPP = "knapp_uppslagsbok"

# Filen uppslagsbok.py skriver, i arbetsmappen.
BOKEN = "uppslagsbok.html"

# Falten stampeln ror.
DATUMFALT = "Granskningsdatum"
LOPNUMMER = "TID"

# Uppslagsrutorna pa blanketten, och kolumnen i `ark_anvisning` som fyller
# dem. De var virtuella falt en gaang -- se formular.UPPSLAGSFALT -- och
# raknades da om per rad i hela lansuttaget. Nu laser vi en rad.
UPPSLAG = {
    "kontextvarning": "uteslut",
    "mattregel": "mattregel",
    "beskrivningsexempel": "exempel",
    "motiveringspaminnelse": "motivering",
}

# Autotextens falt.
TYPFALT = "lamningstyp"
BESKRIVNING = "beskrivning"
FLAGGAN = "autotext"

# Nar en lamning inte kan ha nagon antikvarisk bedomning alls.
#
# Rapporterat: "kombinationen fornlamning och helt undersokt ska aldrig
# kunna goras". Regeln fanns redan -- status.UTAN_BEDOMNING bar de sex
# tillstanden ur handledningen for Fornreg 4.0, s. 41 -- men bara som ett
# mjukt villkor i projektet. Ett mjukt villkor sager ifran vid sparandet;
# det hindrar ingen fran att gora kombinationen.
#
# Har gors det Fornreg sjalvt gor: bedomningen satts till Ingen antikvarisk
# bedomning i samma stund statusen valjs, och skalet skrivs i
# paminnelserutan. Reglerna hamtas darifran de redan staar. En andra
# uppskrivning har hade varit tva sanningar om samma sak, och den ena hade
# hunnit bli fel.
BEDOMNINGSFALT = "antikvariskbedomning"
STATUSFALT = tuple(dict.fromkeys(regel.kolumn for regel in UTAN_BEDOMNING))
# Skalet, sa att den lasta rutan inte blir en gata nar lamningen oppnas
# igen en annan dag.
LASTEXT = "\n".join(
    (
        "Bedömningen är låst av {falt}: {varde} — {skal}. Ändrar du {falt}"
        " går bedömningen att välja igen.",
        "Handledning för Fornreg 4.0, s. 41.",
    )
)
# Faltens namn som de staar pa blanketten, inte i databasen.
FALTETIKETT = {
    "undersokningsstatus": "Undersökt",
    "skadestatus": "Skador",
    "aktualitetstatus": "Registreringsstatus",
}

# Skadan ska beskrivas. Handledning for Fornreg 4.0, s. 43: bara "Ej skadad"
# slipper. Villkoret finns i projektet men ar mjukt -- det sager ifran vid
# sparandet, och da staar man kanske inte kvar vid lamningen langre.
SKADEFALT = "Skadebesk"
SKADETEXT = (
    "Skadebeskrivning krävs när skadestatus är {varde}. Beskriv skadorna "
    "i tur och ordning, från lämningens mitt och ut mot kanterna."
)

# En nypatraffad forstord lamning ar en uppgift, inte en bekraftelse.
#
# Handledningen s. 43: forstord och aldrig publicerad ska ha
# registreringsstatus Uppgift om lamning, ej bekraftad i falt. Blanketten
# satter den **en gaang**, i den stund Forstord valjs. Att haalla fast den
# hade varit att ta ifran arkeologen ett val som ar hens.
PUBLICERINGSFALT = "publiceringsdatum"
ALDRIG_PUBLICERAD = "arkstod_aldrig_publicerad"
SATT_OBEKRAFTAD = "arkstod_satt_obekraftad"
OBEKRAFTADTEXT = (
    "Registreringsstatus sattes till ”{varde}”: lämningen är förstörd och "
    "har aldrig varit publicerad, så det finns ingen bekräftelse att "
    "bevara. Handledning för Fornreg 4.0, s. 43."
)
# Falt blanketten laser men som inte ar listrutor.
TRADITIONSFALT = "tradition"
MATMETODSFALT = "matmet"
MEDELFELSFALT = "medelfel"

# De ovriga beskeden, vart och ett med sin sidhanvisning.
TRADITIONSTEXT = (
    "Traditionen ska fyllas i för lämningstypen {typ} — det är den "
    "uppgiften som bär lämningen. Fältet finns på fliken Administrativt. "
    "Fornreg 4.0, s. 59."
)
TYPBEDOMNINGSTEXT = (
    "Lämningstypen {typ} har alltid bedömningen ”{varde}”, så den sattes "
    "åt dig. Fornreg 4.0, s. 40."
)
FALTBESOKSTEXT = (
    "”{varde}” förutsätter att lämningen är bekräftad i fält. En uppgift ur "
    "en karta eller ett bra boplatsläge räcker inte. Fornreg 4.0, s. 40."
)
HANVISNINGSTEXT = (
    "Skriv i beskrivningen vart lämningen överförts, t.ex. ”Överförd till "
    "L2018:286.” Fälthandbok i arkeologisk inventering 2.0, s. 60."
)
MEDELFELSTEXT = (
    "Medelfelet {varde} m är för stort: {vem} ±{tak:g} m. Mät om medan du "
    "står kvar. Fälthandbok i arkeologisk inventering 2.0, s. 63."
)

# Geometrisorten man ritat i, och vad den heter for en manniska.
#
# Rapporterat: "gaar utmarkt att gora en yta av fardvag". Regeln fanns, men
# bara som anmarkning i leveranslistan -- och den laser man pa kontoret.
# Ritar man ytan i falt sags ingenting forran det ar for sent att gaa
# tillbaka och se efter.
GEOMETRISORT = "arkstod_geometrisort"
GEOMETRINAMN = {"point": "punkt", "linestring": "linje", "polygon": "yta"}
GEOMETRITEXT = (
    "Lämningen är ritad som {sort}, och {skal}. Rita om den i rätt lager — "
    "geometrin följer här lämningstypen och inte storleken."
)

# En blankrad mellan beskeden: de ar olika saker att atgarda, inte ett stycke.
MELLANRUM = "\n\n"

# Falten blanketten bevakar utover statusfalten. Beskeden handlar om dem, sa
# de maste provas om nar de andras -- annars staar ett besked kvar om en
# tradition man just skrivit.
BEVAKADE = (
    BEDOMNINGSFALT,
    SKADEFALT,
    TYPFALT,
    TRADITIONSFALT,
    MATMETODSFALT,
    MEDELFELSFALT,
    BESKRIVNING,
)

# Rutan skalet skrivs i, och listans egen text som ska tillbaka dit efterat.
PAMINNELSERUTA = "motiveringspaminnelse"
LISTANS_PAMINNELSE = "arkstod_paminnelse"

# Egenskaper vi hanger pa dialogen. Formulardialogen aterandvands mellan
# lamningar, sa bade kopplingen och stampeln maste ga att kanna igen.
KOPPLAD = "arkstod_kopplad"
STAMPLAT = "arkstod_stamplat"
# Texten vi sjalva satt in. Utan den gaar det inte att skilja en arvd text
# fran en nagon skrivit, och da vagar man varken byta ut den eller lata bli.
ARVD_TEXT = "arkstod_arvd_text"
# Listans anvisningar, laesta en gaang per dialog.
ANVISNINGAR = "arkstod_anvisningar"


# Vad QGIS skriver i ett tomt textfalt om ingen sagt nagot annat.
QGIS_FORVALDA_NULLTEXT = "NULL"


def dolj_nulltexten() -> None:
    """Later tomma falt vara tomma i stallet for att staa och saga NULL.

    QGIS ritar ett tomt varde med en text, och den ar "NULL" fran borjan.
    I en blankett med tjugo falt betyder det tjugo NULL att lasa forbi innan
    man hittar det som faktiskt staar nagot i -- och den som ser ordet forsta
    gangen undrar rimligen om nagot gaatt sonder.

    Installningen ar QGIS egen och galler hela programmet, inte projektet.
    Darfor rors den **bara om den staar orord**: har nagon valt en egen text
    ar det ett val, och det ska inte skrivas over av ett plugin.
    """
    from qgis.core import QgsApplication

    if QgsApplication.nullRepresentation() == QGIS_FORVALDA_NULLTEXT:
        QgsApplication.setNullRepresentation("")


# QGIS installning for identifieringsverktyget. Nyckeln ar QGIS egen och
# staar inte i projektet -- den galler hela programmet.
IDENTIFIERINGSNYCKEL = "Map/identifyAutoFeatureForm"


def oppna_formularet_vid_identifiering() -> None:
    """Later ett tryck pa en lamning oppna blanketten i stallet for en lista.

    Rapporterat fran falt: *formularet kommer inte auto nar man vill kolla pa
    en tidigare registrering.* Sa ar QGIS satt fran borjan --
    identifieringsverktyget visar en resultatlista, och blanketten naar man
    forst genom att klicka vidare i den. For att lasa en text man skrivit i
    gaar ar det ett steg for mycket, och pa en faltdator med penna ar det tva.

    Installningen ar QGIS egen och galler hela programmet. Darfor rors den
    **bara om den aldrig satts**: har nagon stangt av den ar det ett val, och
    ett val ska inte skrivas over av ett plugin. Samma regel som for
    nulltexten.
    """
    from qgis.core import QgsSettings

    installningar = QgsSettings()
    if installningar.value(IDENTIFIERINGSNYCKEL) is None:
        installningar.setValue(IDENTIFIERINGSNYCKEL, True)


def nar_formularet_oppnas(dialog, lager, sarskild):
    """QGIS anropar den har vid varje oppnat formular."""
    _koppla_uppslagsbok(dialog, lager)
    _koppla_aterstarknappen(dialog, lager)
    _koppla_stampeln(dialog, lager)
    _koppla_autotext(dialog, lager)
    _koppla_bedomningen(dialog, lager)
    _koppla_mattknappen(dialog, lager, sarskild)
    _dolj_tomma_nummer(dialog, sarskild)
    _fyll_registret(dialog, lager, sarskild)
    # Posten hangs pa dialogen: egenskapsvalen ska fyllas om nar
    # lamningstypen byts, och da finns bara dialogen till hands.
    dialog.setProperty(OPPEN_POST_NY, _saknas(sarskild, UUIDFALT))
    _fyll_egenskaper(dialog, lager, falt(sarskild, TYPFALT), sarskild)
    # Publiceringsdatumet staar inte pa blanketten men behovs av regeln om
    # nypatraffade forstorda lamningar, sa det lases ur posten vid oppningen.
    dialog.setProperty(ALDRIG_PUBLICERAD, _saknas(sarskild, PUBLICERINGSFALT))
    dialog.setProperty(SATT_OBEKRAFTAD, False)
    fyll_uppslagen(dialog, lager, falt(sarskild, TYPFALT))


# Lamningens tva nummer, och etiketterna som hor till dem.
#
# Bada kommer fran Riksantikvarieambetet och gaar inte att skriva i. Vid
# revidering ar de det som sager vilken lamning man staar i; vid
# nyregistrering ar de tomma och forblir tomma -- Fornreg delar ut numret
# forst nar lamningen publiceras.
#
# Tva tomma rutor pa den flik man arbetar mest i ar tva rader hojd for
# ingenting, och hojd ar det som tar slut nar tangentbordet ar uppe. De
# doljs darfor nar de saknar varde, och kommer tillbaka sa fort de har ett.
NUMMERFALT = {
    "lamningsnummer": "label_4",
    "raa_nummer": "label_2",
}


# Rutan pa uppslagsfliken som visar vad registret sager om just den har
# lamningen: dess egenskaper och, ar den sammansatt, vad den bestar av.
#
# Uppgifterna ligger i lansuttaget -- RAA:s egna tabeller `egenskap` och
# `ingaendelamning` -- och lastes aldrig forran nu. Se
# `lamningsuppgifter` for vad de innehaller.
REGISTERRUTA = "registret"
ETIKETT_REGISTER = "label_registret"
OPPEN_POST_NY = "arkstod_ny_lamning"
EXEMPELRUTA = "beskrivningsexempel"
UUIDFALT = "lamning_uuid"


def _fyll_registret(dialog, lager, posten) -> None:
    """Skriver registrets uppgifter om lamningen i uppslagsrutan."""
    import sqlite3

    from qgis.PyQt.QtWidgets import QLabel, QTextBrowser

    from arkstod.faltdel.lamningsuppgifter import uppgifter

    ruta = dialog.findChild(QTextBrowser, REGISTERRUTA)
    if ruta is None:
        return
    etikett = dialog.findChild(QLabel, ETIKETT_REGISTER)
    uuid = falt(posten, UUIDFALT)
    if uuid is None or not str(uuid).strip():
        # En nyregistrering finns inte i registret an, och en ruta som sager
        # det tar plats utan att bara nagot. Den doljs, och i dess stalle
        # staar egenskapsvalen -- det ar dar man sjalv fyller i det registret
        # annars hade svarat.
        _visa_registret(ruta, etikett, "")
        return

    kalla = lager.dataProvider().dataSourceUri().split("|")[0]
    try:
        anslutning = sqlite3.connect(f"file:{kalla}?mode=ro", uri=True)
    except sqlite3.Error:
        return
    try:
        anslutning.text_factory = str
        text = uppgifter(anslutning, str(uuid)).text()
    finally:
        anslutning.close()
    _visa_registret(ruta, etikett, text)


def _visa_registret(ruta, etikett, text: str) -> None:
    """Rutan syns bara nar den har nagot att saga.

    Formularets ytor ar det som ar ont om -- med tangentbordet uppe syns
    omkring 210 bildpunkter -- och en tom ruta som upplyser om att den ar tom
    ar den samst anvanda ytan av alla.
    """
    ruta.setPlainText(text)
    ruta.setVisible(bool(text))
    if etikett is not None:
        etikett.setVisible(bool(text))


# Egenskapsvalen pa fliken Lamningen. Fyra listrutor racker: av listans 157
# lamningstyper har 66 egenskaper alls, och av dem har 45 en enda, 16 tva,
# 4 tre och 1 fyra.
#
# Rapporterat fran falt: *vid nyregistrering vill man kunna valja varde for
# egenskap pa fliken lamningen.* Det ar dar typen valjs, och egenskapen ar
# nasta fraga efter typen -- en kolningsanlaggning ar en kolbotten liggmila,
# en kolbotten resmila, en kolningsgrop eller en kolugn.
#
# Valet skrivs inte till nagot falt. Arbetsfilen har ingen egenskapskolumn
# for egna lamningar, och att lagga till en hade andrat leveransen. Det
# valet gor i stallet tva saker som inte kraver det: exempelrutan visar den
# beskrivning som hor till just det vardet -- Exempelsamlingen ar nycklad pa
# egenskapsvarde -- och beskrivningen kan borja darifran.
EGENSKAPSRUTOR = tuple(f"egenskap_{n}" for n in range(1, 5))
EGENSKAPSETIKETTER = tuple(f"label_egenskap_{n}" for n in range(1, 5))
INGET_VAL = "—"

# Beskedet nar typen inte har nagra egenskaper alls.
#
# Rapporterat fran falt: *nar jag gor en yta, tex blastplats, kommer inga
# egenskapsvarden.* Riktigt -- Blastplats har inga i listan. Men tystnad ser
# ut som ett fel, och det kostade faltarbetstid att upptacka att det inte var
# ett. Nu staar det i stallet skrivet.
#
# Listan har 91 typer utan egenskaper av 157. Ett samband gaar att lasa ur
# den, men bara at ett hall: **alla 22 sammansatta lamningstyper saknar
# egenskaper, utan undantag** -- Blastplats, Fangstgropssystem, Gravfalt,
# Omrade med fossil akermark och de ovriga. De beskrivs av vad de innehaller,
# och for dem ar rutan Registret det som bar uppgiften.
#
# De ovriga 69 saknar egenskaper av andra skal. Fabod, Bytomt/gardstomt och
# Plats med tradition ar omraden och platser, inte sammansatta typer -- den
# skillnaden ar listans egen och ska inte suddas ut har.
EGENSKAPSBESKED = "egenskapsbesked"
UTAN_EGENSKAPER = "Listan har inga egenskaper för den här typen."


def _fyll_egenskaper(dialog, lager, lamningstyp, posten=None) -> None:
    """Staller listrutorna efter vald lamningstyp, eller doljer dem.

    Bara vid nyregistrering. En lamning som redan staar i registret har sina
    egenskaper skrivna dar, och de visas i registerrutan bredvid -- att
    erbjuda ett val som inte kan sparas hade sett ut som en mojlighet att
    andra dem.
    """
    import sqlite3

    from qgis.PyQt.QtWidgets import QComboBox, QLabel

    from arkstod.faltdel.lamningsuppgifter import mojliga_egenskaper

    rutor = [dialog.findChild(QComboBox, namn) for namn in EGENSKAPSRUTOR]
    etiketter = [dialog.findChild(QLabel, namn) for namn in EGENSKAPSETIKETTER]
    besked = dialog.findChild(QLabel, EGENSKAPSBESKED)
    # `any(rutor)` duger inte: en tom QComboBox har langden noll och ar
    # darfor falsk i Python. Uppmatt i verklig QGIS -- fyra riktiga
    # listrutor, och any() svarade False.
    if all(ruta is None for ruta in rutor):
        return

    uuid = falt(posten, UUIDFALT)
    ny_lamning = uuid is None or not str(uuid).strip()

    par: list[tuple[str, list[str]]] = []
    # Skild fran `not par`: en arbetsfil som inte gaar att lasa ar inte samma
    # sak som en typ utan egenskaper. Beskedet far bara ges nar listan
    # verkligen svarat.
    listan_svarade = False
    if ny_lamning and lamningstyp:
        try:
            kalla = lager.dataProvider().dataSourceUri().split("|")[0]
            anslutning = sqlite3.connect(f"file:{kalla}?mode=ro", uri=True)
        except (AttributeError, sqlite3.Error):
            anslutning = None
        if anslutning is not None:
            try:
                anslutning.text_factory = str
                par = mojliga_egenskaper(anslutning, str(lamningstyp))
                listan_svarade = True
            except sqlite3.Error:
                par = []
            finally:
                anslutning.close()

    for ruta, etikett, uppgift in zip(rutor, etiketter, list(par) + [None] * 4):
        if ruta is None:
            continue
        if uppgift is None:
            ruta.setVisible(False)
            if etikett is not None:
                etikett.setVisible(False)
            continue
        typnamn, varden = uppgift
        # Blockerat: att fylla listan raknas som en andring, och den skulle
        # annars slaa tillbaka in i exempelrutan innan nagon valt nagot.
        ruta.blockSignals(True)
        ruta.clear()
        ruta.addItem(INGET_VAL)
        ruta.addItems(varden)
        ruta.blockSignals(False)
        ruta.setVisible(True)
        if etikett is not None:
            etikett.setText(typnamn)
            etikett.setVisible(True)

    if besked is not None:
        # Beskedet bara nar en typ ar vald och den saknar egenskaper. Innan
        # typen valts ar tystnaden ratt: dar finns inget att saga an.
        tomt = bool(ny_lamning and lamningstyp and listan_svarade and not par)
        besked.setText(UTAN_EGENSKAPER if tomt else "")
        besked.setVisible(tomt)


def valda_egenskaper(dialog) -> list[str]:
    """De egenskapsvarden som staar valda just nu, i listrutornas ordning."""
    from qgis.PyQt.QtWidgets import QComboBox

    valda = []
    for namn in EGENSKAPSRUTOR:
        ruta = dialog.findChild(QComboBox, namn)
        # isHidden och inte isVisible: ett formular som annu inte visats
        # svarar False pa isVisible aven for rutor som staar framme.
        if ruta is None or ruta.isHidden():
            continue
        varde = (ruta.currentText() or "").strip()
        if varde and varde != INGET_VAL and varde not in TOMMA_VAL:
            valda.append(varde)
    return valda


def exempel_for_valen(samlad: str, valda) -> str:
    """De av typens beskrivningsexempel som hor till de valda vardena.

    Exempelsamlingen ar nycklad pa egenskapsvarde -- "Bytesdjur: Älg/ren,
    Form: Rund" -- sa har finns svaret redan. En fangstgrop har fem exempel
    och den som valt Rund och Varg behover ett av dem.

    Tar valen ut ingenting lamnas hela samlingen orord. Ett tomt uppslag ar
    ett samre svar an ett brett: nyckelorden i listan stavas inte alltid som
    egenskapsvardena, och da ar det regeln som fallerar och inte texten som
    saknas.
    """
    from arkstod.faltdel.uppslagsbok import _dela_exempel

    valda = [v for v in (valda or []) if v]
    if not samlad or not valda:
        return samlad or ""
    traffar = [
        ett
        for ett in _dela_exempel(samlad)
        if ett.nyckel and all(v.casefold() in ett.nyckel.casefold() for v in valda)
    ]
    if not traffar:
        return samlad
    return (chr(10) * 2).join(
        f"{ett.nyckel} — {ett.text}" if ett.nyckel else ett.text for ett in traffar
    )


# Hur langt in i exemplet inledningen far racka innan den slutar vara en
# inledning. Ingen av Exempelsamlingens egna ar i narheten -- den langsta i
# listan ar "Kolbotten efter liggmila, rektangulär," pa 38 tecken.
INLEDNINGSTAK = 80

# Den inledning verktyget senast skrev in, sa att en angrad tanke gaar att
# rakna om utan att arkeologens egen text rors.
SENASTE_INLEDNING = "arkstod_senaste_inledning"


def inledning_ur_exempel(samlad: str, valda) -> str:
    """Beskrivningens forsta ord, hamtade ur det exempel valen pekar ut.

    Rapporterat fran falt: *vid registrering av en fangstgrop eller en
    kolningsanlaggning valjer man kolbotten och form och far forsta delen av
    beskrivningen auto, enligt exempelsamlingen.*

    Inledningen hittas inte pa. Den **staar i exemplet**, och det loser en sak
    som annars hade kravt en egen tabell: lamningstypen ar inte alltid ordet
    beskrivningen borjar med. En Fangstgrop med Bytesdjur=Varg inleds
    "Varggrop", en Kolningsanlaggning med Typ=Kolbotten liggmila inleds
    "Kolbotten efter liggmila". Bada kommer ur egenskapsvardet, och bada
    faller ut av sig sjalva nar texten laeses ur ratt exempel.

    Klippet gaar vid forsta siffran -- dar slutar orden och matten borjar.
    Ett avslutande "ca" foljer med matten och tas darfor bort.
    """
    import re

    from arkstod.faltdel.uppslagsbok import _dela_exempel

    valda = [v for v in (valda or []) if v]
    if not samlad or not valda:
        return ""
    inledningar = []
    for ett in _dela_exempel(samlad):
        if not ett.nyckel:
            continue
        if not all(v.casefold() in ett.nyckel.casefold() for v in valda):
            continue
        traff = re.match(r"[^0-9]{0,%d}" % INLEDNINGSTAK, ett.text)
        if not traff:
            continue
        inledning = re.sub(r"\bca\s*$", "", traff.group(0)).rstrip()
        if inledning:
            inledningar.append(inledning)
    if not inledningar:
        return ""
    # Flera exempel kan dela nyckel. Ar de eniga anvands ordet; skiljer de
    # sig aat far arkeologen skriva sjalv hellre an att fa ett godtyckligt
    # av dem.
    if len(set(inledningar)) != 1:
        return ""
    return inledningar[0] + " "


# Egenskapstypen som bar formordet. Exempelsamlingens inledningar ar byggda
# likadant genomgaende -- saken forst, formen darefter, bada fore forsta
# siffran: "Kolbotten, rund,", "Varggrop, kvadratisk,", "Fangstgrop, oval,".
FORMEGENSKAP = "Form"


def synliga_egenskapstyper(dialog):
    """Namnen pa de egenskapstyper som staar framme just nu."""
    from qgis.PyQt.QtWidgets import QComboBox, QLabel

    namn = []
    for rutnamn, etikettnamn in zip(EGENSKAPSRUTOR, EGENSKAPSETIKETTER):
        ruta = dialog.findChild(QComboBox, rutnamn)
        if ruta is None or ruta.isHidden():
            continue
        etikett = dialog.findChild(QLabel, etikettnamn)
        namn.append(etikett.text() if etikett is not None else "")
    return namn


def valda_egenskapspar(dialog):
    """De valda vardena med sin egenskapstyp: [("Typ", "Kolugn"), ...].

    Bara de som faktiskt valts. Att kraeva alla var fel: en hard har tre
    egenskaper och en stensattning likasa, dar Fyllning ar
    "Rodockrafargad sand" -- nagot som nastan aldrig galler. Kravet gjorde
    att inledningen aldrig kom for dem.
    """
    from qgis.PyQt.QtWidgets import QComboBox, QLabel

    par = []
    for rutnamn, etikettnamn in zip(EGENSKAPSRUTOR, EGENSKAPSETIKETTER):
        ruta = dialog.findChild(QComboBox, rutnamn)
        if ruta is None or ruta.isHidden():
            continue
        varde = (ruta.currentText() or "").strip()
        if not varde or varde == INGET_VAL or varde in TOMMA_VAL:
            continue
        etikett = dialog.findChild(QLabel, etikettnamn)
        par.append(((etikett.text() if etikett is not None else ""), varde))
    return par


def _saken(samlad: str, kravda) -> str:
    """Ordet beskrivningen borjar med, ur typens egna exempel.

    Inte ur lamningstypens namn: raknat i Exempelsamlingen inleds 262 av 377
    beskrivningar med nagot annat ord an typen heter. En Kvarn skrivs
    "Kvarnlamning", en Kata "Katatomt", en Lagenhetsbebyggelse "Torplamning".

    Ordet tas darfor ur exemplen, och det vanligaste vinner -- men bara med
    egen majoritet. Ar de jamna ges ingenting.
    """
    from collections import Counter

    from arkstod.faltdel.uppslagsbok import _dela_exempel

    raknade = Counter()
    for ett in _dela_exempel(samlad):
        if kravda and not all(v.casefold() in (ett.nyckel or "").casefold() for v in kravda):
            continue
        sak = ett.text.split(",", 1)[0].strip()
        if sak and not any(c.isdigit() for c in sak):
            raknade[sak] += 1
    if not raknade:
        return ""
    vanligast = raknade.most_common(2)
    if len(vanligast) > 1 and vanligast[0][1] == vanligast[1][1]:
        return ""
    return vanligast[0][0]


def inledning_for_valen(samlad: str, par, synliga=()) -> str:
    """Inledningen for de val som gjorts, aven utan eget exempel.

    Formen ar det ord beskrivningen har efter saken, sa den maste vara vald
    innan nagot skrivs -- annars gissas den. Ovriga egenskaper ar
    forfiningar och far vanta: en hards Fyllning och Typ behover inte vara
    ifyllda for att "Hard, rund, " ska vara ratt.

    Forsta hand ar alltid Exempelsamlingens egna ord. Finns inget exempel for
    just den kombinationen satts inledningen ihop av tva delar som bada
    kommer ur korpus -- saken ur typens exempel, formen ur det valda vardet.

    **Saken ensam racker aldrig, och det ar med flit.** Femtiotva av de 66
    typerna med egenskaper saknar Form, och for tjugoen av dem gaar det att
    rakna fram ett entydigt ord ur exemplen. Att skriva ut det ordet vore
    frestande och fel: majoritetsordet ar ofta ett *specialfall*, inte ett
    samlingsnamn. Provat mot listan:

        Bro            varden: Valv, Sten, Tra, Stal   ordet: "Stenvalvbro"
        Brytningsyta   varden: Kvarts, Ovrig           ordet: "Kvartsbrott"
        Gjuteri        varden: Jarn, Koppar, Adel      ordet: "Klockgjutningsplats"
        Fastning/skans varden: Fastning, Skans         ordet: "Skanslamning"

    En trabro skulle da inledas "Stenvalvbro" och ett jarngjuteri
    "Klockgjutningsplats". Ett ord som ser auktoritativt ut och ar fel ar
    samre an tystnad -- det senare ratter man, det forra star kvar.
    """
    if not samlad or not par:
        return ""
    if FORMEGENSKAP in synliga and not any(t == FORMEGENSKAP for t, _ in par):
        return ""

    exakt = inledning_ur_exempel(samlad, [v for _, v in par])
    if exakt:
        return exakt

    form = next((v for t, v in par if t == FORMEGENSKAP), "")
    if not form:
        return ""
    ovriga = [v for t, v in par if t != FORMEGENSKAP]
    sak = _saken(samlad, ovriga) or _saken(samlad, ())
    if not sak:
        return ""
    return f"{sak}, {form.casefold()}, "


def _koppla_egenskapsvalen(dialog, lager, lamningstyp) -> None:
    """Later ett valt egenskapsvarde snava in exempelrutan."""
    from qgis.PyQt.QtWidgets import QComboBox

    for namn in EGENSKAPSRUTOR:
        ruta = dialog.findChild(QComboBox, namn)
        if ruta is None:
            continue
        try:
            ruta.currentIndexChanged.disconnect()
        except TypeError:
            pass
        ruta.currentIndexChanged.connect(
            lambda _index, d=dialog, la=lager, t=lamningstyp: _efter_egenskapsval(d, la, t)
        )


def _efter_egenskapsval(dialog, lager, lamningstyp) -> None:
    """Snavar in exempelrutan och satter beskrivningens forsta ord.

    Rapporterat fran falt: *om jag angrar mig och vill skriva att kolbottnen
    ar rund i stallet for kvadratisk funkar det inte.* Riktigt -- forsta
    versionen skrev bara i en tom ruta, och efter ett val var den inte tom
    langre. Regeln "skriv aldrig over" ar ratt, men den kunde inte skilja
    **arkeologens** text fran **verktygets egen inledning som blivit
    inaktuell**.

    Skillnaden gaar att gora genom att minnas vad som senast skrevs in. Staar
    den kvar **ensam** ar den var att byta ut:

        "Kolbotten, kvadratisk, "  -> byt Form till Rund ->  "Kolbotten, rund, "

    Har fortsattningen skrivits rors ingenting. Rapporterat: *det ar i ett
    forsta skede de sparar lite tid; har man sedan skrivit fortsattningen med
    beskrivning av rund men den var oval far man andra manuellt.* Riktigt --
    och att da byta bara inledningen hade gjort texten fel pa ett satt som ar
    svarare att upptacka an att den star oandrad.
    """
    from qgis.core import QgsApplication
    from qgis.PyQt.QtWidgets import QPlainTextEdit

    fyll_uppslagen(dialog, lager, lamningstyp)

    ruta = dialog.findChild(QPlainTextEdit, BESKRIVNING)
    if ruta is None:
        return
    bok = dialog.property(ANVISNINGAR) or {}
    samlad = (bok.get(lamningstyp or "", {}) or {}).get(EXEMPELRUTA) or ""
    inledning = inledning_for_valen(
        samlad, valda_egenskapspar(dialog), synliga_egenskapstyper(dialog)
    )
    nuvarande = ruta.toPlainText()
    forra = dialog.property(SENASTE_INLEDNING) or ""
    tom = nuvarande.strip() in ("", QgsApplication.nullRepresentation())
    # Bara var egen inledning, och bara sa lange den staar ensam. Har
    # fortsattningen skrivits hor den ihop med de ord som redan staar dar --
    # att byta "rund" mot "oval" i inledningen medan kroppen fortsatter
    # beskriva en rund grop vore att gora texten fel pa ett satt som ar
    # svarare att upptacka an att den ar oandrad. Formen styr dessutom
    # mattens form: runt mats i diameter, ovalt i langd x bredd med
    # langdriktning, sa ett halvt byte lamnar bade ord och matt fel.
    ensam = bool(forra and nuvarande.strip() == forra.strip())

    if not tom and not ensam:
        return
    if not inledning:
        if ensam:
            ruta.setPlainText("")
            dialog.changeAttribute(BESKRIVNING, "")
        dialog.setProperty(SENASTE_INLEDNING, "")
        return

    ruta.setPlainText(inledning)
    markor = ruta.textCursor()
    markor.movePosition(markor.End)
    ruta.setTextCursor(markor)
    dialog.setProperty(SENASTE_INLEDNING, inledning)
    dialog.changeAttribute(BESKRIVNING, inledning)


def _dolj_tomma_nummer(dialog, posten) -> None:
    """Later tomma nummerrutor slippa ta plats vid nyregistrering."""
    from qgis.PyQt.QtWidgets import QLabel, QTextBrowser

    for faltnamn, etikettnamn in NUMMERFALT.items():
        ruta = dialog.findChild(QTextBrowser, faltnamn)
        etikett = dialog.findChild(QLabel, etikettnamn)
        if ruta is None or etikett is None:
            continue
        # Posten och inte rutan: rutan kan ha ritats innan varden hangts pa,
        # och da hade en reviderad lamning tappat sitt nummer ur blanketten.
        syns = not _saknas(posten, faltnamn)
        ruta.setVisible(syns)
        etikett.setVisible(syns)


def falt(posten, namn):
    """Ett faltvarde ur en post, eller None om faltet inte finns.

    QgsFeature kastar KeyError pa ett okant faltnamn, och en post utan
    faltlista -- den som QGIS skickar med nar ett formular oppnas innan
    faltena hangts pa -- har inga namn alls. Ett formular som inte gaar att
    oppna ar varre an en tom ruta, sa fragan far vara tillaten att sakna
    svar.

    Rapporterat fran falt: KeyError: 'lamningstyp' nar en yta ritades.
    """
    if posten is None:
        return None
    try:
        return posten[namn]
    except (KeyError, IndexError, TypeError):
        return None


def _anvisningar(lager) -> dict:
    """Hela `ark_anvisning` som en uppslagsbok i minnet.

    En fraaga per arbetsfil i stallet for en per rad. Tabellen ar 157 rader
    och far plats var som helst; det som kostade var att gora uppslaget till
    ett virtuellt falt, for da gjordes det om for varje rad i lagret.
    """
    import sqlite3

    try:
        kalla = lager.dataProvider().dataSourceUri().split("|")[0]
        anslutning = sqlite3.connect(f"file:{kalla}?mode=ro", uri=True)
    except (AttributeError, sqlite3.Error):
        # Ett lager utan filkalla -- minneslager, eller ett prov. Rutorna far
        # staa tomma; formularet ska oppnas anda.
        return {}
    try:
        kolumner = ", ".join(f'"{kolumn}"' for kolumn in UPPSLAG.values())
        return {
            rad[0]: dict(zip(UPPSLAG, rad[1:]))
            for rad in anslutning.execute(
                f'SELECT "lamningstyp", {kolumner} FROM ark_anvisning'
            )
        }
    except sqlite3.OperationalError:
        # En aldre arbetsfil utan uppslagstabell. Rutorna far staa tomma
        # hellre an att formularet inte oppnas.
        return {}
    finally:
        anslutning.close()


def fyll_uppslagen(dialog, lager, lamningstyp) -> None:
    """Skriver listans text i blankettens fyra uppslagsrutor."""
    from qgis.PyQt.QtWidgets import QTextBrowser

    bok = dialog.property(ANVISNINGAR)
    if bok is None:
        bok = _anvisningar(lager)
        dialog.setProperty(ANVISNINGAR, bok)

    rader = bok.get(lamningstyp or "", {})
    valda = valda_egenskaper(dialog)
    for widgetnamn in UPPSLAG:
        ruta = dialog.findChild(QTextBrowser, widgetnamn)
        if ruta is None:
            continue
        text = rader.get(widgetnamn) or ""
        if widgetnamn == EXEMPELRUTA:
            text = exempel_for_valen(text, valda)
        ruta.setPlainText(text)

    # Paminnelserutan delas med bedomningslaset. Listans text sparas undan
    # sa att den kan komma tillbaka nar laset slapper, och laset far sista
    # ordet -- det galler den lamning som ligger pa bordet, inte typen.
    dialog.setProperty(LISTANS_PAMINNELSE, rader.get(PAMINNELSERUTA) or "")
    _foljden_av_statusen(dialog)


# Vad en listruta visar for ett tomt varde. QGIS ritar det tomma valet med
# sin nullstrang, och vardelistan lagger dessutom till parenteser: uppmatt i
# verklig QGIS stod det "(NULL)" i en orord skaderuta.
#
# Utan det provet blev tomheten ett varde: en farsk blankett bad genast om
# en skadebeskrivning till skadestatus "(NULL)".
TOMMA_VAL = ("", "NULL", "(NULL)")


def _geometrisort(lager) -> str:
    """Vilken sorts geometri lagret bar: point, linestring eller polygon."""
    if lager is None:
        return ""
    try:
        from qgis.core import QgsWkbTypes

        return {
            QgsWkbTypes.PointGeometry: "point",
            QgsWkbTypes.LineGeometry: "linestring",
            QgsWkbTypes.PolygonGeometry: "polygon",
        }.get(lager.geometryType(), "")
    except (AttributeError, ImportError):
        return ""


def _valet(dialog, faltnamn: str) -> str:
    """Det som staar i en av blankettens listrutor just nu, tomt som tomt."""
    from qgis.core import QgsApplication
    from qgis.PyQt.QtWidgets import QComboBox

    ruta = dialog.findChild(QComboBox, faltnamn)
    if ruta is None:
        return ""
    text = (ruta.currentText() or "").strip()
    null = QgsApplication.nullRepresentation()
    if text in TOMMA_VAL or text in (null, f"({null})"):
        return ""
    return text


def _koppla_bedomningen(dialog, lager=None) -> None:
    """Later statusfalten styra bedomningen, och paminna om skadetexten.

    Tre regler ur handledningen for Fornreg 4.0, alla med samma karaktar:
    de foljer av varandra och behover inte valjas. Reglerna sjalva bor i
    status.py; har kopplas de till blanketten.
    """
    # Geometrisorten star inte i nagot falt utan i vilket lager man ritat i,
    # sa den lases vid varje oppning och hangs pa dialogen. Skrivs bara nar
    # den gaar att lasa: en dialog som redan bar en sort ska inte tappa den
    # for att nagon anropade utan lager.
    sorten = _geometrisort(lager)
    if sorten:
        dialog.setProperty(GEOMETRISORT, sorten)

    if dialog.property(KOPPLAD + "_bedomning"):
        return

    def vid_andring(falt, varde=None, andrat=None):
        # Aven bedomningen sjalv och de falt beskeden handlar om: ett varde
        # som anda tar sig in ska motas av samma regel. Slingan tar slut av
        # sig sjalv -- andra varvet staar det ratta redan dar, och da skrivs
        # inget mer.
        if falt in STATUSFALT or falt in BEVAKADE:
            _foljden_av_statusen(dialog)

    dialog.widgetValueChanged.connect(vid_andring)
    dialog.setProperty(KOPPLAD + "_bedomning", True)


def _foljden_av_statusen(dialog) -> None:
    """Satter det som foljer av valen, och skriver skalen i paminnelserutan.

    Reglerna sjalva bor i status.py och motivering.py. Har avgors bara nar
    de provas och i vilken ordning beskeden staar: det som blanketten redan
    har gjort forst, det som hindrar darefter, och det som aterstar att
    fylla i sist.
    """
    from qgis.PyQt.QtWidgets import QComboBox, QTextBrowser

    ruta = dialog.findChild(QComboBox, BEDOMNINGSFALT)
    if ruta is None:
        return

    typ = _valet(dialog, TYPFALT)
    varden = {namn: _valet(dialog, namn) for namn in STATUSFALT}
    varden[PUBLICERINGSFALT] = (
        "" if dialog.property(ALDRIG_PUBLICERAD) else "publicerad"
    )
    varden["beskrivning"] = _beskrivningen(dialog)
    skalen = []

    # Forst den nypatraffade forstorda lamningen: den satter ett statusvarde
    # som i sin tur kan utlosa laset, sa den maste ga fore.
    if kraver_obekraftad(varden) and not dialog.property(SATT_OBEKRAFTAD):
        dialog.setProperty(SATT_OBEKRAFTAD, True)
        if varden["aktualitetstatus"] != OBEKRAFTAD:
            dialog.changeAttribute("aktualitetstatus", OBEKRAFTAD)
            varden["aktualitetstatus"] = OBEKRAFTAD
            skalen.append(OBEKRAFTADTEXT.format(varde=OBEKRAFTAD))
    elif varden["skadestatus"] != FORSTORD:
        # Angrar man sig ska regeln kunna slaa till en gaang till.
        dialog.setProperty(SATT_OBEKRAFTAD, False)

    # Bedomningar som typen sjalv bestammer. Fornreg satter den at en, och
    # da ska blanketten gora det ocksa -- annars sitter man med ett varde
    # som andras nar man publicerar.
    typens = bedomning_for_typ(typ)
    if typens is not None:
        if ruta.currentText() != typens:
            dialog.changeAttribute(BEDOMNINGSFALT, typens)
        skalen.append(TYPBEDOMNINGSTEXT.format(typ=typ, varde=typens))

    regel = utesluter_bedomning(varden)

    # Vardet satts tillbaka, rutan stangs inte av.
    #
    # Forsta forsoket var setEnabled(False) pa listrutan, som Fornreg tycks
    # gora. Det haaller inte har: QGIS satter pa rutan igen vid varje
    # uppdatering av formularet, och uppmatt i provbanken var den valbar
    # direkt efteraat i alla atta provade fall. Att stanga av en ruta som
    # nagon annan satter pa ar att lova mer an man haaller.
    #
    # Vardevakten haaller daremot: valjer man Fornlamning studsar den
    # tillbaka i samma andetag, och matningen visar Ingen antikvarisk
    # bedomning bade i rutan och i posten for alla sex utlosande varden --
    # och Fornlamning kvar for Delundersokt och Grov skada.
    if regel is not None:
        if ruta.currentText() != INGEN_BEDOMNING:
            # Via dialogen och inte rutan: det ar changeAttribute som far
            # andringen att raknas som en andring, och det ar den som
            # utloser stampeln.
            dialog.changeAttribute(BEDOMNINGSFALT, INGEN_BEDOMNING)
        skalen.append(
            LASTEXT.format(
                falt=FALTETIKETT[regel.kolumn],
                varde=regel.varde,
                skal=regel.skal,
            )
        )
    elif kraver_faltbesok(_valet(dialog, BEDOMNINGSFALT)) and (
        varden["aktualitetstatus"] != BEKRAFTAD
    ):
        # Aven det tomma faltet, och framfor allt det.
        #
        # De tre andra registreringsstatusarna laser bedomningen helt och
        # fangas av regeln ovan, sa det enda lage dar Mojlig fornlamning kan
        # staa utan att vara bekraftad i falt ar nar statusen inte ar vald
        # an. Utan tomheten hade regeln aldrig kunnat slaa till.
        #
        # Ingen tvangsandring: vilket av de tva vardena som ar fel vet bara
        # den som stod dar.
        skalen.append(FALTBESOKSTEXT.format(varde=MOJLIG_FORNLAMNING))

    # Skadetexten sist och inte i stallet for laset: en forstord lamning
    # utloser bada, och da behovs bada. Den som bara far se det ena skulle
    # tro att det andra var avklarat.
    if kraver_skadebeskrivning(varden["skadestatus"]) and not _texten(
        dialog, SKADEFALT
    ):
        skalen.append(SKADETEXT.format(varde=varden["skadestatus"]))

    sorten = dialog.property(GEOMETRISORT)
    geometri = geometriregel(typ)
    if sorten and geometri is not None:
        from arkstod.faltdel.kontroller import storsta_matt

        matt = storsta_matt(varden["beskrivning"]) or 0
        tillatna = geometri.stor if matt > 20 else geometri.liten
        if sorten not in tillatna:
            skalen.append(
                GEOMETRITEXT.format(
                    sort=GEOMETRINAMN[sorten], skal=geometri.skal
                )
            )

    if kraver_tradition(typ) and not _faltvarde(dialog, TRADITIONSFALT):
        skalen.append(TRADITIONSTEXT.format(typ=typ))

    if saknar_hanvisning(varden):
        skalen.append(HANVISNINGSTEXT)

    medelfel = _faltvarde(dialog, MEDELFELSFALT)
    over = medelfel_over_taket(_faltvarde(dialog, MATMETODSFALT), medelfel)
    if over is not None:
        tak, vem = over
        skalen.append(MEDELFELSTEXT.format(varde=medelfel, vem=vem, tak=tak))

    paminnelse = dialog.findChild(QTextBrowser, PAMINNELSERUTA)
    if paminnelse is None:
        return
    listans = dialog.property(LISTANS_PAMINNELSE) or ""
    paminnelse.setPlainText(MELLANRUM.join(skalen) if skalen else listans)


def _faltvarde(dialog, faltnamn: str) -> str:
    """Ett faltvarde, ur rutan om den finns och annars ur posten.

    Medelfelet staar inte pa blanketten -- matmetoden sager vad det blir,
    och en ruta till hade gjort fliken trang. Faltet finns anda i lagret och
    kan ha ett varde, sa en kontroll som bara laste rutorna hade sagt att
    det var tomt och tjatat om nagot som redan var gjort.
    """
    text = _texten(dialog, faltnamn) or _valet(dialog, faltnamn)
    if text:
        return text
    try:
        posten = dialog.currentFormFeature()
    except (AttributeError, RuntimeError):
        return ""
    varde = falt(posten, faltnamn)
    if varde is None:
        return ""
    text = str(varde).strip()
    return "" if text in TOMMA_VAL else text


def _texten(dialog, faltnamn: str) -> str:
    """Det som staar i en av blankettens textrutor just nu."""
    from qgis.core import QgsApplication
    from qgis.PyQt.QtWidgets import QPlainTextEdit

    ruta = dialog.findChild(QPlainTextEdit, faltnamn)
    if ruta is None:
        return ""
    text = ruta.toPlainText().strip()
    return "" if text == QgsApplication.nullRepresentation() else text


# Knappen som raknar matten ur den ritade geometrin.
#
# Rapporterat: *ritar man en yta, tex en fabodvall eller gardstomt, brukar
# inte matten matas i falt utan inne pa kontoret nar man putsar
# beskrivningarna.* Da staar geometrin redan dar, och den bar svaret.
#
# Provat mot Blekingeuttagets egna ytor, raknat mot vad arkeologer skrivit i
# samma lamnings beskrivning: 100x60 (NNV-SSÖ) mot raknade 102x68
# (NNV-SSÖ), 90x20 (ÖNÖ-VSV) mot 92x19 (ÖNÖ-VSV), 210x80 mot 212x81. I tva
# fall var det raknade riktigare an det skrivna -- "V-Ö" bryter mot regeln
# att nordlig eller ostlig riktning staar forst, och en post skrev
# "80x300 m" om en yta som ar 76x31.
#
# **Den skriver aldrig over.** Texten satts in vid markoren. De fall dar
# raakningen inte stammer ar just de dar beskrivningens matt galler nagot
# annat -- en husgrund inne i gardstomten, inte tomten -- och det kan
# verktyget inte veta.
MATTKNAPP = "knapp_matt"


def mattformen(lager, lamningstyp) -> tuple[bool, bool]:
    """Om typen skrivs med bara langd, och om ordet "huvudriktning" ska med.

    Bada laeses ur arbetsfilens egna korpustabeller. Det ar samma kalla som
    uppslagsfliken visar, sa det knappen skriver kan inte saga emot det
    formularet har oppet bredvid.
    """
    import sqlite3

    from arkstod.faltdel.mattregel import bara_langd, skriver_huvudriktning

    if not lamningstyp:
        return False, False
    try:
        kalla = lager.dataProvider().dataSourceUri().split("|")[0]
        anslutning = sqlite3.connect(f"file:{kalla}?mode=ro", uri=True)
    except (AttributeError, sqlite3.Error):
        return False, False
    try:
        anslutning.text_factory = str
        rad = anslutning.execute(
            'SELECT text FROM "ark_beskrivningsprincip" WHERE lamningstyp = ?',
            (str(lamningstyp),),
        ).fetchone()
        princip = rad[0] if rad else ""
        exempel = [
            text
            for (text,) in anslutning.execute(
                'SELECT text FROM "ark_beskrivningsexempel" WHERE lamningstyp = ?',
                (str(lamningstyp),),
            )
        ]
    except sqlite3.OperationalError:
        # En aldre arbetsfil utan korpustabellerna. Da faar knappen skriva
        # ytmattet som forr hellre an att inte skriva nagot.
        return False, False
    finally:
        anslutning.close()
    return bara_langd(princip), skriver_huvudriktning(exempel)


def matt_ur_geometrin(
    geometri,
    sorten: str,
    bara_langd: bool = False,
    huvudriktning: bool = False,
) -> str:
    """Mattet som text, eller tom strang om geometrin inte bar nagot.

    `orientedMinimumBoundingBox` ger langd, bredd och langdaxelns baring.
    Uppmatt mot kanda rektanglar: vinkeln **ar** baringen, raknad medurs
    fran norr, och hojden ar den langa sidan. Forsta forsoket la pa 90 grader
    och gav genomgaende fel vaderstreck.
    """
    from arkstod.faltdel.mattregel import langdmatt, linjematt, ytmatt

    if geometri is None or geometri.isEmpty():
        return ""
    ruta, _area, vinkel, bredd, hojd = geometri.orientedMinimumBoundingBox()
    if ruta is None or ruta.isEmpty():
        return ""
    langd, kort = max(bredd, hojd), min(bredd, hojd)
    barning = (vinkel if hojd >= bredd else vinkel + 90) % 360
    if bara_langd:
        # Rapporterat fran falt: ett fangstgropssystem skrivs inte
        # "590x100 m (NÖ–SV)" utan med en enda langd. Geometrin sager inte
        # vilket matt som ska skrivas -- systemet ritas som en yta men
        # beskrivs som en strackning -- sa typens princip far avgora.
        strackan = geometri.length() if sorten == "linestring" else langd
        return langdmatt(strackan, barning, huvudriktning)
    if sorten == "linestring":
        # Linjens langd ar dess egen och inte rektangelns: en krokig halvag
        # ar langre an sin utstrackning.
        return linjematt(geometri.length(), barning)
    return ytmatt(langd, kort, barning)


def _koppla_mattknappen(dialog, lager, posten) -> None:
    """Later knappen skriva in matten vid markoren i beskrivningen."""
    from qgis.PyQt.QtWidgets import QPlainTextEdit, QPushButton

    knapp = dialog.findChild(QPushButton, MATTKNAPP)
    if knapp is None:
        return

    sorten = _geometrisort(lager)
    try:
        knapp.clicked.disconnect()
    except TypeError:
        pass

    if sorten == "point":
        # En punkt har ingen utstrackning att mata. Knappen doljs och slacks
        # inte: en slackt knapp tar lika mycket plats som en tand, och
        # formularets ytor ar det som ar ont om. Slackningen holl inte heller
        # -- QGIS tander om widgetar vid varje uppdatering av formularet.
        knapp.setVisible(False)
        return

    knapp.setVisible(True)
    knapp.setEnabled(True)
    knapp.setToolTip("Räknar längd, bredd och längdriktning ur geometrin")

    def skriv_in():
        try:
            geometri = dialog.currentFormFeature().geometry()
        except (AttributeError, RuntimeError):
            geometri = falt(posten, "geometri")
        # Listrutan forst: den bar det val man just gjort, aven innan
        # posten skrivits om.
        typen = _valet(dialog, "lamningstyp") or falt(posten, "lamningstyp")
        langdform, huvudriktning = mattformen(lager, typen)
        text = matt_ur_geometrin(geometri, sorten, langdform, huvudriktning)
        ruta = dialog.findChild(QPlainTextEdit, BESKRIVNING)
        if not text or ruta is None:
            return
        # Vid markoren, och inget skrivs over: vad mattet hor till i
        # meningen vet bara den som skriver den.
        ruta.insertPlainText(text)
        dialog.changeAttribute(BESKRIVNING, ruta.toPlainText())

    knapp.clicked.connect(skriv_in)


ATERSTARKNAPP = "knapp_aterstar"


def _koppla_aterstarknappen(dialog, lager) -> None:
    """Later knappen pa administrativa fliken lista det som fattas.

    Rapporterat fran falt: *"Vad aterstar" bor vara i sjalva verktyget, en
    knapp pa administrativa fliken verkar logiskt.* Riktigt -- det ar med
    blanketten framfor sig man undrar, och menyn ligger en flik och ett
    musdrag bort.

    Menyvalet staar kvar. Det granskar hela jobbet och behovs nar man staar
    vid bilen och ska besluta om att aka; knappen svarar pa samma fraga men
    dar fragan stalls.
    """
    from qgis.PyQt.QtWidgets import QMessageBox, QPushButton

    knapp = dialog.findChild(QPushButton, ATERSTARKNAPP)
    if knapp is None or dialog.property(KOPPLAD + "_aterstar"):
        return

    def visa():
        import sqlite3

        from arkstod.faltdel.kontroller import granska_egna, sammanfatta_aterstaende

        try:
            kalla = lager.dataProvider().dataSourceUri().split("|")[0]
            anslutning = sqlite3.connect(f"file:{kalla}?mode=ro", uri=True)
        except (AttributeError, sqlite3.Error):
            return
        try:
            anslutning.text_factory = str
            rader = granska_egna(anslutning)
        except sqlite3.Error:
            return
        finally:
            anslutning.close()
        text, nagot = sammanfatta_aterstaende(rader)
        visning = QMessageBox.warning if nagot else QMessageBox.information
        visning(dialog, "Vad återstår?", text)

    knapp.clicked.connect(visa)
    dialog.setProperty(KOPPLAD + "_aterstar", True)


def _koppla_uppslagsbok(dialog, lager) -> None:
    """Ger knappen pa uppslagsfliken sin uppgift.

    Sokvagen raknas ut vid varje oppning och inte vid uttaget: arbetsmappen
    skapas pa kontorsdatorn och kopieras darefter till faltdatorn, ofta till
    en annan sokvag. Lagrets egen datakalla vet var filen ligger just nu.
    """
    import os

    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtGui import QDesktopServices
    from qgis.PyQt.QtWidgets import QPushButton

    knapp = dialog.findChild(QPushButton, "knapp_uppslagsbok")
    if knapp is None:
        return

    # Datakallan ar "<sokvag>.gpkg|layername=point". Boken ligger bredvid.
    kalla = lager.dataProvider().dataSourceUri().split("|")[0]
    boken = os.path.join(os.path.dirname(kalla), "uppslagsbok.html")

    # Utan detta far knappen en koppling per lamning man haft oppen, och
    # boken oppnas lika manga ganger pa ett tryck.
    try:
        knapp.clicked.disconnect()
    except TypeError:
        pass

    if not os.path.exists(boken):
        # Hellre en slackt knapp an en som ser ut att fungera.
        knapp.setEnabled(False)
        knapp.setToolTip("uppslagsbok.html saknas i arbetsmappen")
        return

    knapp.setEnabled(True)
    knapp.clicked.connect(
        lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(boken))
    )


def _koppla_stampeln(dialog, lager) -> None:
    """Stamplar besoket sa fort nagot i formularet andras."""
    if dialog.property(KOPPLAD):
        # Samma dialog igen. Signalen ar redan kopplad; det som maste
        # nollstallas ar stampeln, for det ar en ny lamning.
        dialog.setProperty(STAMPLAT, False)
        return

    def vid_andring(*_):
        if dialog.property(STAMPLAT):
            return
        dialog.setProperty(STAMPLAT, True)
        _stampla(dialog, lager)

    dialog.widgetValueChanged.connect(vid_andring)
    dialog.setProperty(KOPPLAD, True)
    dialog.setProperty(STAMPLAT, False)


def _koppla_autotext(dialog, lager) -> None:
    """Later beskrivningen arvas nar lamningstypen valts -- inte forr.

    Texten hamtades forst som ett defaultvarde, alltsa i det ogonblick
    lamningen skapas. Da har man annu inte sagt vad det ar, sa den kunde
    omojligt ta hansyn till lamningstypen: efter sex kolbottnar fick en
    fangstgrop kolbottentexten.

    Nar valet av typ ar det som utloser arvet loser sig bada delarna. Texten
    kommer fran forra lamningen **av samma typ**, och den kommer i samma
    stund som man sagt vilken typ det ar.
    """
    if dialog.property(KOPPLAD + "_autotext"):
        return

    def vid_andring(falt, varde=None, andrat=None):
        if falt != TYPFALT:
            return
        # Uppslagen forst: de galler den typ man just valt, och ska staa
        # dar innan man borjar skriva beskrivningen.
        fyll_uppslagen(dialog, lager, varde)
        if dialog.property(OPPEN_POST_NY):
            _fyll_egenskaper(dialog, lager, varde, None)
            _koppla_egenskapsvalen(dialog, lager, varde)
        _arv_beskrivning(dialog, lager, varde)

    dialog.widgetValueChanged.connect(vid_andring)
    dialog.setProperty(KOPPLAD + "_autotext", True)


def _arv_beskrivning(dialog, lager, typ) -> None:
    """Fyller i forra lamningens text, om den bad om det och typen stammer."""
    nuvarande = _beskrivningen(dialog)
    arvd = dialog.property(ARVD_TEXT)

    # Det nagon skrivit sjalv ror vi aldrig. Bara tomt, eller det vi sjalva
    # satt in: byter man typ efter att ha arvt en text ska den bytas ut, och
    # finns ingen ny ska den bort -- det var hela fragan.
    if nuvarande and nuvarande != arvd:
        return

    text = _forra_texten(lager, typ) or ""
    if text == nuvarande:
        # Ingenting att gora. Skriva anda vore inte harmlost: en skrivning
        # gor lamningen andrad, och en andring ar det som utloser stampeln.
        return

    dialog.changeAttribute(BESKRIVNING, text)
    dialog.setProperty(ARVD_TEXT, text)
    if text:
        # Kryssrutan foljer med, annars maste man kryssa i den pa var och en
        # av de tjugo kolbottnarna.
        dialog.changeAttribute(FLAGGAN, 1)


def _beskrivningen(dialog) -> str:
    """Det som staar i beskrivningsrutan just nu.

    Rutan och inte posten: posten bar det formularet oppnades med, och
    fragan galler vad som staar dar i detta ogonblick.

    Ett tomt falt ar inte alltid tomt i rutan. QGIS ritar NULL med en text,
    och den ar "NULL" om ingen andrat installningen -- provet i verklig
    QGIS gav just den strangen, och tomhetskontrollen sa da att nagon skrivit
    nagot. Vad tecknet ar staar i QgsApplication, sa det fragas dar.
    """
    from qgis.core import QgsApplication
    from qgis.PyQt.QtWidgets import QPlainTextEdit

    ruta = dialog.findChild(QPlainTextEdit, BESKRIVNING)
    if ruta is None:
        return ""
    text = ruta.toPlainText().strip()
    return "" if text == QgsApplication.nullRepresentation() else text


def _forra_texten(lager, typ):
    """Beskrivningen fran senaste lamningen av samma typ som bad om arv.

    Tre villkor, och vart och ett bar sitt skal:

    * **samma lamningstyp** -- annars far fangstgropen kolbottentexten
    * **kryssrutan ibockad** -- det ar den som sager "fortsatt pa samma
      text", och den staar aldrig pa av sig sjalv
    * **hogsta TID** -- lopnumret och inte fid, for en lamning som annu
      ligger i redigeringsbufferten har inget fid: QGIS skriver det forst
      vid sparning
    """
    if not typ:
        return None

    from qgis.core import QgsExpression, QgsFeatureRequest

    begaran = QgsFeatureRequest()
    begaran.setFlags(QgsFeatureRequest.NoGeometry)
    begaran.setFilterExpression(
        f'"{TYPFALT}" = {QgsExpression.quotedValue(typ)}'
        f' and "{FLAGGAN}" = 1'
    )

    basta, texten = None, None
    for post in lager.getFeatures(begaran):
        text = falt(post, BESKRIVNING)
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            nummer = int(falt(post, LOPNUMMER))
        except (TypeError, ValueError):
            continue
        if basta is None or nummer > basta:
            basta, texten = nummer, text
    return texten


def _stampla(dialog, lager) -> None:
    """Dagens datum, och ett lopnummer om lamningen saknar ett.

    Bada laser ur den post formularet oppnades med. Det ar med flit: en
    revidering som redan bar ett lopnummer ska behalla det -- numret ska ga
    att skriva om for att lagga en lamning mellan tva andra i ordningen --
    medan datumet ar ett pastaende om i dag och alltid satts.
    """
    from qgis.PyQt.QtCore import QDate

    posten = dialog.feature()

    if _tomt(posten, LOPNUMMER):
        dialog.changeAttribute(LOPNUMMER, nasta_lopnummer(lager))

    dialog.changeAttribute(DATUMFALT, QDate.currentDate())


def _saknas(posten, faltnamn: str) -> bool:
    """Sant om ett textfalt saknar varde.

    QGIS NULL ar varken None eller tom strang, men det skriver ut sig som
    "NULL" -- och `_tomt` bredvid duger inte, den provar att lasa ett tal.
    """
    varde = falt(posten, faltnamn)
    return varde is None or str(varde).strip() in ("", QGIS_FORVALDA_NULLTEXT)


def _tomt(posten, faltnamn: str) -> bool:
    """Sant om faltet saknar varde.

    QGIS NULL ar varken None eller falskt i alla lagen, sa provet gors pa
    det som faktiskt ska ga: att lasa talet.
    """
    try:
        int(falt(posten, faltnamn))
    except (TypeError, ValueError, KeyError):
        return True
    return False


def nasta_lopnummer(lager) -> int:
    """Hogsta TID i lagret plus ett -- ocksa bland osparade lamningar.

    `maximum()` som aggregat gaar inte att lita pa har: en lamning som annu
    ligger i redigeringsbufferten kan saknas. Radgenomgangen ser dem, och
    utan geometri och med ett enda falt kostar den lite aven i ett lansuttag.
    """
    from qgis.core import QgsFeatureRequest

    begaran = QgsFeatureRequest()
    begaran.setFlags(QgsFeatureRequest.NoGeometry)
    begaran.setSubsetOfAttributes([LOPNUMMER], lager.fields())

    hogsta = 0
    for post in lager.getFeatures(begaran):
        try:
            tal = int(falt(post, LOPNUMMER))
        except (TypeError, ValueError):
            continue
        hogsta = max(hogsta, tal)
    return hogsta + 1


def initfunktion() -> str:
    """Funktionens namn, som QGIS ska anropa."""
    return nar_formularet_oppnas.__name__


def registrera() -> None:
    """Lagger funktionen dar QGIS letar efter den.

    QGIS kor bade sin kontroll och sitt anrop i `__main__` -- samma namnrymd
    som pythonkonsolen och som projektmakron. Anropet ser ut som
    `nar_formularet_oppnas(dialog, lager, sarskild)`, ett bart namn, sa det
    racker inte att modulen gaar att importera.
    """
    import __main__

    setattr(__main__, nar_formularet_oppnas.__name__, nar_formularet_oppnas)


def avregistrera() -> None:
    """Tar bort den igen. Kors nar pluginet lasses av."""
    import __main__

    if getattr(__main__, initfunktion(), None) is nar_formularet_oppnas:
        delattr(__main__, initfunktion())
