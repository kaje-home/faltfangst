"""Statusmaskinen och de villkorade obligatoriefalten.

Falthandboken har regler som inte ar rad utan foljd: vissa statusvarden gor
att lamningen inte kan ha en antikvarisk bedomning alls, och da ska faltet
sattas automatiskt i stallet for att valjas fritt. Andra galler at andra
hallet -- ar skadestatus atverkan maste skadan beskrivas.

Reglerna ligger har som data i stallet for i formularets XML, av samma skal
som resten: ett uttryck i en projektfil gaar inte att prova, och ett schema
som andras efter ett par anvandningar ska vara latt att andra.

Vardena ar RAA:s egna, avlasta ur lansuttaget. Att skriva av dem ur minnet
hade gett "Uppgift om lamning" i stallet for "Uppgift om lamning, ej bekraftad
i falt", och regeln hade da aldrig slagit till.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

INGEN_BEDOMNING = "Ingen antikvarisk bedömning"
FORSTORD = "Förstörd"


@dataclass(frozen=True)
class Statusregel:
    """Ett statusvarde som utesluter antikvarisk bedomning."""

    kolumn: str
    varde: str
    skal: str


# De sex tillstanden ur falthandboken. Lamningen finns inte kvar att bedoma,
# eller ar inte en lamning att bedoma.
UTAN_BEDOMNING: tuple[Statusregel, ...] = (
    Statusregel(
        "aktualitetstatus",
        "Uppgift om lämning, ej bekräftad i fält",
        "det finns ingen bekräftad fysisk lämning att pröva",
    ),
    Statusregel(
        "aktualitetstatus",
        "Utgår på grund av felregistrering",
        "posten skulle aldrig ha funnits",
    ),
    Statusregel(
        "aktualitetstatus",
        "Överförd till annan lämning",
        "lämningen bedöms under sitt nya nummer",
    ),
    Statusregel(
        "undersokningsstatus",
        "Helt undersökt",
        "lämningen är borta efter undersökning",
    ),
    Statusregel(
        "undersokningsstatus",
        "Borttagen utan villkor",
        "lämningen är borttagen",
    ),
    Statusregel("skadestatus", FORSTORD, "lämningen är förstörd"),
)

# Regeln ar formulerad som ett undantag och inte som en lista, for det ar sa
# den lyder: **bara "Ej skadad" slipper en skadebeskrivning.**
#
# Forst stod fyra varden uppraknade -- Averkan, Ringa averkan, Grov skada,
# Forstord -- och "Okand" raknades som undantagen tillsammans med "Ej
# skadad". Det ar fel. Okand ar ingen frisedel utan en observation som ocksa
# behover forklaras: varfor gick skadan inte att bedoma? Overtorvad,
# snotackt, otillganglig.
#
# Skillnaden mellan de tva formerna ar inte bara stilistisk. En uppraknad
# lista maste fyllas pa nar RAA lagger till ett statusvarde, och glommer man
# det blir det nya vardet tyst undantaget. Ett undantag maste daremot
# utokas med flit.
SKADA_UTAN_BESKRIVNING: tuple[str, ...] = ("Ej skadad",)

# Matmetodens medelfel. Varden ur falthandboken; de sitter i mataren, inte i
# lamningen, och ska darfor foljas med som default i stallet for att skrivas
# in for hand vid varje registrering.
MEDELFEL: dict[str, float] = {
    "GPS": 7.0,
    "DGPS": 2.0,
    "RTK": 0.05,
}

# Absolut tak for medelfelet, oavsett matmetod. Registreringsmanualen s. 9:
# *Felmarginalen vid inmatning far inte overstiga +/-10 m.*
MEDELFEL_TAK = 10.0

# Lamningstyper dar faltet Tradition maste fyllas i.
#
# Handledningen for Fornreg 4.0, s. 59-60: *Faltet Tradition ska du fylla i
# for lamningstyperna Kalla med tradition, Naturforemal/-bildning med
# tradition, Offerkast och Plats med tradition men ar inte obligatoriskt for
# andra lamningstyper.*
#
# Namnen ar **listans** och inte handledningens: naturforemalet heter
# "Naturforemal/-bildning med bruk, tradition eller namn" i lamningstypslista
# 5.0. Skriver man av handledningens namn slar regeln aldrig till.
TRADITIONSTYPER: tuple[str, ...] = (
    "Källa med tradition",
    "Naturföremål/-bildning med bruk, tradition eller namn",
    "Offerkast",
    "Plats med tradition",
)

# Bedomningar som lamningstypen sjalv bestammer.
#
# Handledningen s. 40: *Bedomningen Ej kulturhistorisk lamning kan endast
# anges for lamningstypen Fornlamningsliknande bildning. [...] Valjer du
# lamningstypen Fornlamningsliknande bildning satter systemet automatiskt Ej
# kulturhistorisk lamning.* Regeln gaar aat bada hallen, och blanketten
# foljer bada.
EJ_KULTURHISTORISK = "Ej kulturhistorisk lämning"
BEDOMNING_PER_TYP: dict[str, str] = {
    "Fornlämningsliknande bildning": EJ_KULTURHISTORISK,
}

# En bedomning som forutsatter ett faltbesok.
#
# Handledningen s. 40: *For att ange Mojlig fornlamning maste lamningen vara
# bekraftad i falt. Det far inte vara en uppgift om en lamning hamtad
# exempelvis fran en historisk karta.*
MOJLIG_FORNLAMNING = "Möjlig fornlämning"
BEKRAFTAD = "Bekräftad i fält"
OVERFORD = "Överförd till annan lämning"

# Lamningar som aldrig bekraftats i falt. Det narmaste "obesokt" som RAA:s
# oppna data medger -- registreringsdatum finns inte i uttaget, sa "aldre
# registrering" gaar inte att avgora.
OBEKRAFTAD = "Uppgift om lämning, ej bekräftad i fält"

# Statusvarden dar geometrin inte pastar lamningens egen utbredning.
#
# En obekraftad uppgift ritas som en yta over det omrade dar lamningen kan
# tankas ligga -- ytan sager "nagonstans har inne", inte "sa har stor ar den".
# En felregistrering ar ingen lamning alls, och en overford post har flyttat.
# Att lasa nagon av dem som ett uttalande om storlek ar att lasa fel.
#
# De ovriga i UTAN_BEDOMNING star kvar: Fornreg sager att geometrin for en
# helt undersokt eller borttagen lamning ska omfatta dess sista kanda
# utbredning, sa den pastar fortfarande en storlek.
EJ_EGEN_UTBREDNING: tuple[str, ...] = (
    OBEKRAFTAD,
    "Utgår på grund av felregistrering",
    OVERFORD,
)

# "Överförd till L2018:286." Bade orden och numret; RAA-numret duger ocksa,
# for en lamning som aldrig publicerats har inget L-nummer att peka pa.
_HANVISNING = re.compile(
    r"överförd\s+till\s+\S*(?:L\s?\d{4}:\d+|\d)", re.IGNORECASE
)


@dataclass(frozen=True)
class Geometriregel:
    """Vilken geometrisort en lamningstyp ska ha, oavsett storlek."""

    typ: str
    # Vad som galler under respektive over tjugometersgransen.
    liten: tuple[str, ...]
    stor: tuple[str, ...]
    kalla: str
    skal: str


# Typer dar geometrisorten inte foljer den allmanna tjugometersregeln.
#
# Grundregeln -- under 20 m punkt, over 20 m yta -- staar i kontroller och
# galler allt annat. Har staar undantagen, och de kommer inte ur
# lamningstypslistan utan ur handledningen och exempelsamlingen. Listan ar
# darfor en upprakning: den vet inget den inte blivit tillsagd.
GEOMETRI_PER_TYP: dict[str, Geometriregel] = {
    "Färdvägssystem": Geometriregel(
        "Färdvägssystem",
        ("linestring",),
        ("linestring",),
        "Arbeta med lämningsinformation, Fornreg 4.0, s. 50",
        "ett färdvägssystem registreras med linjer och utan yttre"
        " begränsningsyta",
    ),
    "Färdväg": Geometriregel(
        "Färdväg",
        ("linestring",),
        ("linestring",),
        "Handledning för inventering och dokumentation — Exempelsamling,"
        " s. 87",
        "vägar ritas alltid som linjer i hela sin sträckning, aldrig som"
        " områden",
    ),
    "Gruvhål": Geometriregel(
        "Gruvhål",
        ("point",),
        ("linestring",),
        "Arbeta med lämningsinformation, Fornreg 4.0, s. 51",
        "ett gruvhål över 20 m registreras med en linje som motsvarar"
        " gruvhålets kant, ett mindre med en punkt",
    ),
}


def geometriregel(lamningstyp: str | None) -> Geometriregel | None:
    """Undantaget for typen, eller None nar grundregeln galler."""
    return GEOMETRI_PER_TYP.get((lamningstyp or "").strip())


# Vad Fornreg sjalvt fyller i nar en ny lamning registreras.
#
# Handledningen sager det om vart och ett, och lansuttaget bekraftar det:
#
#   Registreringsstatus  Bekraftad i falt      s. 37   94 % av Blekinge
#   Undersokningsstatus  Ej undersokt          s. 45   81 %
#   Grad av skada        Ej skadad             s. 43   67 %
#   Placering            Synlig ovan mark      s. 58   98 %
#
# *Ej skadad ar ett forvalt varde och ar ifyllt nar du registrerar en ny
# lamning* (s. 43), och likadant for de tre andra. Blanketten lamnade dem
# tomma, sa fyra listrutor oppnades per lamning for varden systemet sjalvt
# anser vara utgangslaget -- attio tryck med penna pa tjugo kolbottnar.
#
# **Bara vid nyregistrering.** QGIS raknar ut ett defaultvarde nar lamningen
# skapas, och rors darfor aldrig vid revidering: lansets egna varden staar
# kvar.
#
# Skadestatusens 67 % ar det svagaste av de fyra, och invandningen ar
# verklig -- ett forval som ar fel var tredje gaang kan accepteras av
# troghet. Det staar har anda, for Fornreg gor precis detta: valet flyttas
# tidigare i kedjan, det uppstar inte.
FORVAL_VID_NYREGISTRERING: dict[str, str] = {
    "aktualitetstatus": BEKRAFTAD,
    "undersokningsstatus": "Ej undersökt",
    "skadestatus": SKADA_UTAN_BESKRIVNING[0],
    "placering": "Synlig ovan mark",
}


def utesluter_bedomning(rad: dict) -> Statusregel | None:
    """Den forsta statusregel som slar till, eller None."""
    for regel in UTAN_BEDOMNING:
        if (rad.get(regel.kolumn) or "") == regel.varde:
            return regel
    return None


def kraver_obekraftad(rad: dict) -> bool:
    """Om lamningen ar forstord och aldrig har varit publicerad.

    Handledningen for Fornreg 4.0, s. 43: *For en nypatraffad lamning (dvs.
    som inte tidigare har varit publicerad) som ar forstord, anger du
    registreringsstatus Uppgift om lamning, ej bekraftad i falt och grad av
    skada Forstord.*

    Skalet staar pa s. 37: en forstord lamning som aldrig publicerats har
    aldrig kunnat bekraftas av nagon, och det finns inget kvar att bekrafta.
    En redan publicerad lamning behaller daremot sin registreringsstatus --
    dar finns en tidigare iakttagelse som fortfarande gallde nar den gjordes.

    Publiceringsdatum och inte lamningsnummer ar provet: det ar ordagrant
    det handledningen fragar efter.
    """
    return (rad.get("skadestatus") or "").strip() == FORSTORD and not str(
        rad.get("publiceringsdatum") or ""
    ).strip()


def kraver_skadebeskrivning(skadestatus: str | None) -> bool:
    """Om det valda statusvardet kraver att skadan beskrivs.

    Tomt varde kraver ingenting: en lamning dar skadestatus inte ar satt har
    ingen skada att beskriva an.
    """
    varde = (skadestatus or "").strip()
    return bool(varde) and varde not in SKADA_UTAN_BESKRIVNING


def medelfel_for(matmetod: str | None) -> float | None:
    return MEDELFEL.get((matmetod or "").strip().upper())


def medelfel_over_taket(matmetod: str | None, medelfel) -> tuple[float, str] | None:
    """Taket for metoden, om det angivna medelfelet overskrider det.

    MEDELFEL ar inte bara ett forval. Falthandboken s. 63 skriver talen som
    granser: *Den hogsta tillatna felmarginalen vid GPS-inmatning ar +/-7 m.
    Anvands DGPS minskar det till +/-2 m, och med RTK blir det sa precist
    som +/-0,05 m.* Registreringsmanualen s. 9 satter dessutom ett tak
    oavsett metod: *Felmarginalen vid inmatning far inte overstiga +/-10 m.*

    Ett for stort medelfel ar inte ett skrivfel utan en lagesuppgift som
    inte haaller for registret. Den som staar kvar pa platsen kan mata om.
    """
    try:
        varde = float(str(medelfel).replace(",", "."))
    except (TypeError, ValueError):
        return None

    tak = medelfel_for(matmetod)
    if tak is not None and varde > tak:
        return tak, f"{(matmetod or '').strip().upper()} tillåter högst"
    if varde > MEDELFEL_TAK:
        return MEDELFEL_TAK, "inmätning tillåter högst"
    return None


def samsta_kvaliteten(matningar) -> tuple[str, float] | None:
    """Helhetens matmetod och medelfel: den samsta av delarnas.

    Handledningen for Fornreg 4.0, s. 56: *Det ar den sammantagna kvaliteten
    for hela lamningen som ska redovisas. Om lamningen bestar av flera
    geometrier som har matts in vid flera olika tillfallen och med olika
    metoder och registreringsunderlag ar det den samsta kvaliteten som ska
    anges for helheten.*

    Samst ar storst medelfel. Saknar en del sitt eget varde anvands metodens
    forval, och saknas aven metoden raknas delen inte alls -- en okand
    kvalitet ar inte samma sak som en dalig, och att gissa aat det haallet
    vore att forsamra helheten pa ingen grund.
    """
    basta = None
    for matmetod, medelfel in matningar:
        try:
            varde = float(str(medelfel).replace(",", "."))
        except (TypeError, ValueError):
            varde = medelfel_for(matmetod)
        if varde is None:
            continue
        if basta is None or varde > basta[1]:
            basta = ((matmetod or "").strip(), varde)
    return basta


def kraver_tradition(lamningstyp: str | None) -> bool:
    """Om traditionen maste skrivas for den har lamningstypen."""
    return (lamningstyp or "").strip() in TRADITIONSTYPER


def bedomning_for_typ(lamningstyp: str | None) -> str | None:
    """Den bedomning typen sjalv bestammer, om den gor det."""
    return BEDOMNING_PER_TYP.get((lamningstyp or "").strip())


def saknar_hanvisning(rad: dict) -> bool:
    """Om en overford lamning inte sager vart den overforts.

    Falthandboken s. 60: *En hanvisning som talar om till vilken lamning den
    overforts ska alltid goras i beskrivningen, exempelvis: "Overford till
    L2018:286."*

    Utan hanvisningen ar posten en atervandsgrand: den sager att lamningen
    finns nagon annanstans men inte var. Bade orden och numret kravs -- ett
    lamningsnummer nagonstans i texten kan vara vad som helst.
    """
    if (rad.get("aktualitetstatus") or "").strip() != OVERFORD:
        return False
    return not _HANVISNING.search(str(rad.get("beskrivning") or ""))


def kraver_faltbesok(bedomning: str | None) -> bool:
    """Om bedomningen forutsatter att lamningen ar bekraftad i falt."""
    return (bedomning or "").strip() == MOJLIG_FORNLAMNING


def villkor_bedomning() -> str:
    """QGIS-uttryck: sant nar bedomningen ar forenlig med statusvardena."""
    delar = [
        f"\"{regel.kolumn}\" = '{regel.varde}'" for regel in UTAN_BEDOMNING
    ]
    return (
        f"NOT ({' OR '.join(delar)})"
        f" OR \"antikvariskbedomning\" = '{INGEN_BEDOMNING}'"
    )


def villkor_skadebeskrivning() -> str:
    """QGIS-uttryck: sant nar skadan ar beskriven om den behover vara det."""
    undantagna = ", ".join(f"'{varde}'" for varde in SKADA_UTAN_BESKRIVNING)
    tom = "coalesce(trim(\"skadestatus\"), '') = ''"
    beskriven = "coalesce(trim(\"Skadebesk\"), '') <> ''"
    return f"{tom} OR \"skadestatus\" IN ({undantagna}) OR {beskriven}"


def uttryck_medelfel() -> str:
    """QGIS-uttryck for medelfelets default utifran vald matmetod."""
    fall = " ".join(
        f"WHEN \"matmet\" = '{metod}' THEN {fel}" for metod, fel in MEDELFEL.items()
    )
    return f"CASE {fall} END"
