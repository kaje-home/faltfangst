"""Kontrollerna: vad handboken och Fornreg sager om form och geometri.

Det har var kvallsvyn -- en egen korning efter faltdagen som listade allt som
avvek. Den togs bort, och kontrollerna flyttade in i leveranslistan, dar de
star vid det falt de galler i det ogonblick det ska fyllas i.

Skalet var inte att kontrollerna var fel utan att platsen var det. En separat
korning maste man komma ihaag, och den sa saker man redan sett: man laser varje
beskrivning nar man klistrar in den i Fornreg. Dartill saag den bara rader dar
nagot av verktygets egna falt var ifyllt, vilket missade en reviderad
beskrivning -- RAA:s kolumn -- och rapporterade i stallet femtroskeln for
andras registreringar decennier tillbaka. Femton anmarkningar man inte kunde
gora nagot at, och noll om det egna arbetet.

Kvar ar kontrollerna sjalva. De pastar aldrig att nagot ar fel i sak: de sager
att en text avviker fran handbokens form, eller att en geometri ar ovanlig for
sin lamningstyp i det har uttaget. Vad som ar riktigt avgor den som var pa
platsen.

Reglerna ar reguljara uttryck och uppslag, ingen spraakmodell. Det ar en poang:
en linter som gissar ar samre an ingen linter, eftersom man slutar lyssna pa
den.
"""

from __future__ import annotations

import re
import math
import sqlite3
import struct
from dataclasses import dataclass

from arkstod.faltdel.geometri import omslutande
from arkstod.faltdel.mattregel import GODTAGNA_STRECK, STRECK, motsatt
from arkstod.faltdel.status import (
    BEKRAFTAD,
    EJ_KULTURHISTORISK,
    EJ_EGEN_UTBREDNING,
    INGEN_BEDOMNING,
    MOJLIG_FORNLAMNING,
    OBEKRAFTAD,
    OVERFORD,
    bedomning_for_typ,
    geometriregel,
    kraver_faltbesok,
    kraver_obekraftad,
    kraver_skadebeskrivning,
    kraver_tradition,
    medelfel_over_taket,
    saknar_hanvisning,
    utesluter_bedomning,
)

KALLA = "Fälthandbok i arkeologisk inventering 2.0 (2023-11-28), Jamtli. CC BY."
KALLA_FORNREG = "Arbeta med lämningsinformation, Fornreg 4.0, Riksantikvarieämbetet"
KALLA_REGISTRET = "Länsuttagets egen praxis, räknad ur ark_lamningstyp"

# Handbokens gransvarden.
GEOMETRITROSKEL_METER = 20


# Nar en geometrityp ska raknas som avvikande for lamningstypen.
#
# Fornreg binder geometrin till lamningens storlek, inte till dess typ, och
# tillater dessutom yta oavsett storlek nara en fastighetsgrans. Nagon regel
# "den har typen far aldrig vara en yta" finns alltsa inte att hamta, och
# anmarkningen formuleras darfor som en observation om registret -- inte som
# ett brott mot en foreskrift.
#
# Talen ar satta sa att en avvikelse ska vara tydlig: minst 50 lamningar av
# typen i uttaget, och den har geometrisorten under 5 procent av dem. I
# Jamtland ger det fangstgropen (46 ytor av 7 255, 0,6 %) och
# kolningsanlaggningen (4 av 3 574, 0,1 %).
PRAXIS_MINSTA_UNDERLAG = 50
PRAXIS_ANDEL = 0.05


@dataclass(frozen=True)
class Anmarkning:
    """En avvikelse fran handbokens form. Inte ett pastaende om sakfragan."""

    regel: str
    text: str
    tabell: str = ""
    fid: int = 0
    lamningstyp: str = ""
    kalla: str = KALLA

    def __str__(self) -> str:
        var = f"{self.tabell}:{self.fid} " if self.tabell else ""
        return f"{var}[{self.regel}] {self.text}"


# ── Beskrivningsgrammatik ────────────────────────────────────────────────────

# "15 m i diameter" ska vara "15 m diam". Regeln star uttryckligen i handboken
# och traffar verkliga beskrivningar i uttaget.
_I_DIAM = re.compile(r"\bm\s+i\s+diam(?:eter)?\b", re.IGNORECASE)

# Handbokens ord: "Antal under 10 bor inte uppskattas. Anvand inte uttryck som
# 'ca 4' eller 'ett 5-tal'." Regeln galler ANTAL, inte matt -- "ca 0,8 m" ar en
# helt normal mattangivelse. Darfor heltal, och inte foljt av en enhet.
_CIRKA = re.compile(
    r"\bca\.?\s*(\d+)(?![,.\d])(?!\s*(?:m\b|cm\b|meter\b|km\b|%))", re.IGNORECASE
)
_ANTALSTAL = re.compile(r"\bett\s+(\d+)-tal\b", re.IGNORECASE)

# "Avstand och storleksmatt anges i meter, med en eller hogst tva decimaler."
# Undantagna ar skalgropar, ristningar och inskriptioner -- de mats i
# centimeter, och da galler inte meterregeln.
_METER = re.compile(r"(\d+[,.](\d+))\s*m\b")
_CENTIMETERTYPER = re.compile(r"skålgrop|ristning|inskript", re.IGNORECASE)

# Langdriktning inleds med nordlig riktning, i andra hand ostlig.
# Tre bokstaver ocksa: NNV-SSO och ONO-VSV ar lika vanliga som N-S, och med
# tva slog kontrollen till pa en brakdel av materialet.
#
# O tas med i klassen for att kunna anmarkas, inte for att godtas. Se
# _OSTLIGT_O nedan.
# Hela parentesen fangas, med skiljetecken och mellanslag, sa att formen
# gaar att prova och inte bara innehallet.
_RIKTNING = re.compile(
    r"\((\s*)([NSÖOVnsöov]{1,3})(\s*)([-–—])(\s*)([NSÖOVnsöov]{1,3})(\s*)\)"
)

# Falthandboken: "meter med en eller hogst tva decimaler: 1 m, 1,2 m eller
# 1,45 m". Decimaltecknet ar komma; en punkt ar en engelsk vana som smyger
# sig in nar man skrivit i annat.
# Ostlig riktning skrivs med O-med-prickar. Se mattregel.VADERSTRECK for
# raknandet: det ar gjort i manualerna -- Exempelsamlingen och
# lamningstypslistan -- och inte bland registrerade lamningar. Ett "NNO" ar
# alltsa inte en variant utan en avvikelse.
_OSTLIGT_O = re.compile(r"\b(?=[NSV]*O)[NSOV]{1,3}\b")

_DECIMALPUNKT = re.compile(r"\b\d+\.\d+\s*(?:m|cm)\b")

# Matt i beskrivningen, for jamforelse med geometrin.
_DIAMETER = re.compile(r"(\d+(?:[,.]\d+)?)\s*m\s+(?:i\s+)?diam", re.IGNORECASE)
# Formen styr mattets form: runt mats i diameter, ovalt och kantigt i
# langd x bredd med langdriktning.
#
# Rapporterat: *nagot ovalt har ingen diam utan langdriktning.* Raknat i
# Exempelsamlingen staar det klart: oval far langd x bredd i 15 fall av 15,
# rektangular i 35 av 35, kvadratisk i 9 av 9 -- aldrig diameter.
#
# Rund provas inte. Den far diam i 31 fall men langd x bredd i 15: en
# narmast rund grop kan mycket val matas i tva led. Inte heller
# Oregelbunden, Domarring eller Ovrig -- en domarring ar en ring och har
# diameter, och for de ovriga saknas underlag. Kontrollen galler bara de
# former dar kallan ar entydig.
FORMER_UTAN_DIAMETER = (
    "oval", "rektangulär", "kvadratisk", "långhög", "långröse", "skeppsformig",
)

# Bara nar diametern ar formens eget matt -- alltsa direkt efter formordet.
# "Oval, 4x3 m, med runt bottenplan 1 m diam" ar ratt: diametern hor da
# till bottenplanet och inte till gropen.
_FORM_MED_DIAMETER = re.compile(
    r"\b(" + "|".join(FORMER_UTAN_DIAMETER) + r")\b\s*,?\s*"
    r"(?:ca\s*)?\d+(?:[,.]\d+)?\s*m\s+(?:i\s+)?diam",
    re.IGNORECASE,
)

_UTBREDNING = re.compile(r"(\d+(?:[,.]\d+)?)\s*[x×]\s*(\d+(?:[,.]\d+)?)\s*m\b")


def _tal(text: str) -> float:
    return float(text.replace(",", "."))


def _inleder_ratt(forsta: str) -> bool:
    """Nordlig riktning forst, i andra hand ostlig."""
    forsta = forsta.upper()
    if forsta.startswith("N") or forsta.startswith("S"):
        return forsta.startswith("N")
    # O anmarks for sig; ordningen provas anda, sa att "V-NNO" inte far
    # tva anmarkningar dar den ena rader ut den andra.
    return forsta.startswith(("Ö", "O"))


def granska_beskrivning(text: str) -> list[Anmarkning]:
    """Formreglerna, som reguljara uttryck. Ren funktion -- latt att prova."""
    if not text:
        return []
    anmarkningar: list[Anmarkning] = []

    for traff in _I_DIAM.finditer(text):
        anmarkningar.append(
            Anmarkning(
                "diam",
                f"”{traff.group(0).strip()}” — handboken skriver ”m diam”, utan ”i”",
            )
        )

    for traff in _FORM_MED_DIAMETER.finditer(text):
        form = traff.group(1).casefold()
        anmarkningar.append(
            Anmarkning(
                "form",
                f"”{traff.group(0)}” — {form} mäts i längd×bredd med "
                "längdriktning, inte i diameter",
            )
        )

    for traff in _CIRKA.finditer(text):
        if _tal(traff.group(1)) < 10:
            anmarkningar.append(
                Anmarkning(
                    "uppskattning",
                    f"”{traff.group(0)}” — inga uppskattningar under tio",
                )
            )

    for traff in _ANTALSTAL.finditer(text):
        if int(traff.group(1)) < 10:
            anmarkningar.append(
                Anmarkning(
                    "uppskattning",
                    f"”{traff.group(0)}” — inga uppskattningar under tio",
                )
            )

    i_centimeter = bool(_CENTIMETERTYPER.search(text))
    for traff in _METER.finditer(text):
        if len(traff.group(2)) > 2 and not i_centimeter:
            anmarkningar.append(
                Anmarkning(
                    "decimaler",
                    f"”{traff.group(0)}” — meter anges med 1–2 decimaler",
                )
            )

    for traff in _DECIMALPUNKT.finditer(text):
        anmarkningar.append(
            Anmarkning(
                "decimaltecken",
                f"”{traff.group(0)}” — decimaltecknet är komma: "
                f"”{traff.group(0).replace('.', ',')}”",
            )
        )

    # Ostlig riktning skrivs med O-med-prickar, och regeln galler var i
    # texten strecket an staar -- inte bara i langdriktningens parentes.
    # "20 m NO om vagen" ar lika fel som "(NNO-SSV)".
    for streck in sorted({traff.group(0) for traff in _OSTLIGT_O.finditer(text)}):
        anmarkningar.append(
            Anmarkning(
                "väderstreck",
                f"”{streck}” — östlig riktning förkortas Ö: "
                f"”{streck.replace('O', 'Ö')}”",
            )
        )

    for traff in _RIKTNING.finditer(text):
        hela = traff.group(0)
        forsta, skiljetecken, andra = traff.group(2), traff.group(4), traff.group(6)
        ratt = f"({forsta.upper()}{STRECK}{andra.upper()})"

        # En langdriktning ar en axel. Bada andarna ska vara samma linje sedd
        # at var sitt hall -- "NÖ–SSV" ar inte en riktning utan tva.
        motstycke = motsatt(forsta)
        if motstycke and andra.upper() != motstycke:
            anmarkningar.append(
                Anmarkning(
                    "riktning",
                    f"”{hela}” — längdriktningen är en axel: mot {forsta.upper()}"
                    f" står {motstycke}",
                )
            )
        elif skiljetecken not in GODTAGNA_STRECK or any(
            traff.group(luft) for luft in (1, 3, 5, 7)
        ):
            # Falthandboken skriver formen rakt ut: "80×30 m (NNV–SSÖ)".
            # Bade tankstreck och bindestreck godtas -- verktyget skriver det
            # senare, och RAA:s egna texter bar det forra. Kvar att anmarka
            # pa ar tankstreck med luft omkring och andra streck an de tva.
            anmarkningar.append(
                Anmarkning(
                    "riktning",
                    f"”{hela}” — längdriktningen skrivs {ratt}",
                )
            )

        if not _inleder_ratt(forsta):
            anmarkningar.append(
                Anmarkning(
                    "riktning",
                    f"”{hela}” — längdriktning inleds med nordlig "
                    "riktning, i andra hand östlig",
                )
            )

    return anmarkningar


def storsta_matt(text: str) -> float | None:
    """Lamningens storsta matt enligt beskrivningen, i meter."""
    matt: list[float] = []
    for traff in _DIAMETER.finditer(text or ""):
        matt.append(_tal(traff.group(1)))
    for traff in _UTBREDNING.finditer(text or ""):
        matt.extend((_tal(traff.group(1)), _tal(traff.group(2))))
    return max(matt) if matt else None


# ── Kontroller mot en enskild lamning ────────────────────────────────────────


# Statusreglerna, en rad var.
#
# De var nio if-block med samma innanmate: prova regeln, formulera beskedet,
# lagg till i listan. Sju blev nio under sommaren och nasta blir tio, sa
# monstret staar nu pa ett stalle och regeln ar det enda som skiljer dem at.
#
# Varje prova-funktion far posten och lamningstypen och svarar med beskedet
# eller None. Ordningen i tabellen ar ordningen anmarkningarna staar i.


def _bedomning_trots_uteslutning(post: dict, typ: str) -> str | None:
    regel = utesluter_bedomning(post)
    bedomning = post.get("antikvariskbedomning") or ""
    if regel is None or not bedomning or bedomning == INGEN_BEDOMNING:
        return None
    return (
        f"”{regel.varde}” men bedömd som ”{bedomning}” — {regel.skal}, "
        f"så bedömningen ska vara ”{INGEN_BEDOMNING}”"
    )


def _skada_utan_beskrivning(post: dict, typ: str) -> str | None:
    if not kraver_skadebeskrivning(post.get("skadestatus")):
        return None
    if (post.get("Skadebesk") or "").strip():
        return None
    return f"skadestatus ”{post.get('skadestatus')}” men ingen skadebeskrivning"


def _forstord_utan_obekraftad(post: dict, typ: str) -> str | None:
    if not kraver_obekraftad(post):
        return None
    if (post.get("aktualitetstatus") or "") == OBEKRAFTAD:
        return None
    return (
        "förstörd och aldrig publicerad — registreringsstatus ska "
        f"vara ”{OBEKRAFTAD}”"
    )


def _mot_typens_bedomning(post: dict, typ: str) -> str | None:
    typens = bedomning_for_typ(typ)
    bedomning = post.get("antikvariskbedomning") or ""
    if typens is None or not bedomning or bedomning == typens:
        return None
    return (
        f"lämningstypen {typ} har alltid bedömningen ”{typens}”,"
        f" men här står ”{bedomning}”"
    )


def _bildning_pa_fel_typ(post: dict, typ: str) -> str | None:
    bedomning = post.get("antikvariskbedomning") or ""
    if bedomning != EJ_KULTURHISTORISK or bedomning_for_typ(typ) is not None:
        return None
    return (
        f"”{bedomning}” kan endast anges för lämningstypen"
        " Fornlämningsliknande bildning"
    )


def _mojlig_utan_faltbesok(post: dict, typ: str) -> str | None:
    if not kraver_faltbesok(post.get("antikvariskbedomning") or ""):
        return None
    if (post.get("aktualitetstatus") or "") == BEKRAFTAD:
        return None
    return (
        f"”{MOJLIG_FORNLAMNING}” förutsätter att lämningen är"
        " bekräftad i fält — en uppgift ur en karta eller ett"
        " boplatsläge räknas inte"
    )


def _tradition_saknas(post: dict, typ: str) -> str | None:
    if not kraver_tradition(typ) or (post.get("tradition") or "").strip():
        return None
    return f"traditionen ska fyllas i för lämningstypen {typ}"


def _overford_utan_hanvisning(post: dict, typ: str) -> str | None:
    if not saknar_hanvisning(post):
        return None
    return (
        f"”{OVERFORD}” men beskrivningen säger inte vart —"
        " skriv t.ex. ”Överförd till L2018:286.”"
    )


def _obekraftad(post: dict, typ: str) -> str | None:
    if (post.get("aktualitetstatus") or "") != OBEKRAFTAD:
        return None
    return (
        "uppgift om lämning, ej bekräftad i fält — närmaste "
        "motsvarighet till obesökt som öppna data medger"
    )


# Regelnamn, provning, kalla. Namnet ar det som staar inom hakparentes i
# leveranslistan, och kallan den handbok anmarkningen gaar att slaa upp i.
STATUSREGLER: tuple[tuple[str, object, str], ...] = (
    ("status", _bedomning_trots_uteslutning, KALLA),
    ("skadebeskrivning", _skada_utan_beskrivning, KALLA),
    ("registreringsstatus", _forstord_utan_obekraftad, KALLA),
    ("typens bedömning", _mot_typens_bedomning, KALLA_FORNREG),
    ("typens bedömning", _bildning_pa_fel_typ, KALLA_FORNREG),
    ("status", _mojlig_utan_faltbesok, KALLA_FORNREG),
    ("tradition", _tradition_saknas, KALLA_FORNREG),
    ("överförd", _overford_utan_hanvisning, KALLA),
    ("obekräftad", _obekraftad, KALLA),
)


def granska_status(tabell: str, post: dict, typ: str) -> list[Anmarkning]:
    """Statusmaskinen och de villkorade obligatoriefalten."""
    anmarkningar: list[Anmarkning] = []
    for regel, prova, kalla in STATUSREGLER:
        besked = prova(post, typ)
        if besked:
            anmarkningar.append(
                Anmarkning(regel, besked, tabell, post["fid"], typ, kalla=kalla)
            )
    return anmarkningar
def granska_matning(tabell: str, post: dict, typ: str) -> list[Anmarkning]:
    """Matmetoden och dess medelfel.

    FMIS-handledningen s. 34: *Metod for inmatning av geometrin ska alltid
    redovisas* och *Medelfel eller exakt varde for inmatningen i falt ska
    alltid anges.* Talen har ett tak -- se `status.medelfel_over_taket`.

    Bada gaar att atgarda pa platsen och nastan ingen annanstans: den som
    staar kvar vid lamningen kan mata om, den som sitter pa kontoret kan
    bara gissa.
    """
    anmarkningar: list[Anmarkning] = []
    metod = (post.get("matmet") or "").strip()
    if not metod:
        anmarkningar.append(
            Anmarkning(
                "mätmetod",
                "mätmetoden är inte angiven — den ska alltid redovisas",
                tabell,
                post["fid"],
                typ,
                kalla=KALLA,
            )
        )

    over = medelfel_over_taket(metod, post.get("medelfel"))
    if over is not None:
        tak, vem = over
        anmarkningar.append(
            Anmarkning(
                "medelfel",
                f"medelfel {post.get('medelfel')} m — {vem} ±{tak:g} m",
                tabell,
                post["fid"],
                typ,
                kalla=KALLA,
            )
        )
    return anmarkningar


def granska_geometri(tabell: str, post: dict, beskrivning: str) -> Anmarkning | None:
    """Tjugometersregeln: under 20 m punkt, over 20 m yta.

    Beskrivningens matt vager tyngre an geometrins utstrackning: en yta kan
    vara grovt digitaliserad, men mattet ar uppmatt pa platsen.

    Saknar beskrivningen matt sags ingenting har. Regeln foll forr tillbaka
    pa geometrins egen utstrackning, och prövade da geometrin mot sig sjalv:
    ytan ar stor, alltsa ar det ratt att den ar en yta. Av 46 fangstgropsytor
    i det jamtlandska uttaget saknar 42 matt i beskrivningen, och alla 42 gick
    igenom -- den storsta 1 622 meter bred. De fangas nu av regeln om yta utan
    matt och av geometripraxis.
    """
    typ = post.get("lamningstyp") or ""
    matt = storsta_matt(beskrivning)

    # Undantagen forst. For nagra typer bestams sorten av typen och inte av
    # storleken, och da ar grundregelns besked direkt felaktigt: ett gruvhal
    # pa 30 m fick forr texten "over 20 m ska vara yta" nar handledningen
    # sager linje.
    regel = geometriregel(typ)
    if regel is not None:
        tillatna = regel.stor if (matt or 0) > GEOMETRITROSKEL_METER else regel.liten
        if tabell in tillatna:
            return None
        return Anmarkning(
            "geometri",
            f"registrerad som {_GEOMETRISORT[tabell][1]} — {regel.skal}",
            tabell,
            post["fid"],
            typ,
            kalla=regel.kalla,
        )

    if matt is None:
        return yta_utan_matt(tabell, post)

    if tabell == "point" and matt > GEOMETRITROSKEL_METER:
        return Anmarkning(
            "geometri",
            f"{matt:.0f} m enligt beskrivningen men registrerad som punkt — "
            f"över {GEOMETRITROSKEL_METER} m ska vara yta",
            tabell,
            post["fid"],
            post.get("lamningstyp") or "",
        )
    if tabell == "polygon" and matt < GEOMETRITROSKEL_METER:
        return Anmarkning(
            "geometri",
            f"{matt:.0f} m enligt beskrivningen men registrerad som yta — "
            f"under {GEOMETRITROSKEL_METER} m ska vara punkt",
            tabell,
            post["fid"],
            post.get("lamningstyp") or "",
        )
    return None


# Vad sorten heter i tabellen, och vad den heter for en manniska.
_GEOMETRISORT = {
    "point": ("antal_punkt", "punkt"),
    "linestring": ("antal_linje", "linje"),
    "polygon": ("antal_yta", "yta"),
}


def geometripraxis(anslutning: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """Hur varje lamningstyp ar geometrisatt i det har uttaget.

    Talen skrivs vid exporten, raknade ur uttagets egen data. Saknas tabellen
    -- en aldre arbetsfil -- lamnas kontrollen darhan i stallet for att spricka.
    """
    try:
        rader = anslutning.execute(
            "SELECT benamning, antal_punkt, antal_linje, antal_yta"
            " FROM ark_lamningstyp"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {
        rad[0]: {"antal_punkt": rad[1], "antal_linje": rad[2], "antal_yta": rad[3]}
        for rad in rader
    }


def granska_geometripraxis(
    tabell: str, post: dict, typ: str, praxis: dict[str, dict[str, int]]
) -> Anmarkning | None:
    """Nar geometrisorten ar ovanlig for lamningstypen i det har uttaget.

    Det har ar ingen foreskrift. Fornreg binder geometrin till lamningens
    storlek och inte till dess typ, och tillater uttryckligen yta oavsett
    storlek nara en fastighetsgrans. Anmarkningen sager darfor vad registret
    gor, inte vad regeln kraver -- och lamnar avgorandet till den som laser.

    Tre skal till att en avvikelse kan vara helt riktig, och alla forekommer:

    * Lamningen ar mindre an vanligt. En fabodvall har normalt en yta, men
      finns bara stugugrunden kvar ar punkten det sanna svaret.
    * Ytan ar en osakerhet och inte en utbredning. De posterna raknas inte
      alls -- se `EJ_EGEN_UTBREDNING` -- och anmarks darfor inte heller.
    * Lamningen ligger vid en fastighetsgrans, dar Fornreg vill ha yta
      oavsett storlek.

    Och underlaget ar inte facit: aldre registreringar bar egna fel, sa
    praxis innehaller en del av det som ska hittas. Kontrollen ar darfor en
    fraga, inte ett pastaende.
    """
    sort = _GEOMETRISORT.get(tabell)
    tal = praxis.get(typ)
    if sort is None or not tal:
        return None
    # En obekraftad uppgift ritas over det omrade dar lamningen kan tankas
    # ligga. Ytan sager "nagonstans har inne", inte "sa har stor ar den".
    if (post.get("aktualitetstatus") or "") in EJ_EGEN_UTBREDNING:
        return None
    totalt = sum(tal.values())
    if totalt < PRAXIS_MINSTA_UNDERLAG:
        return None
    antal = tal[sort[0]]
    if antal == 0 or antal / totalt >= PRAXIS_ANDEL:
        return None

    vanligast = max(_GEOMETRISORT.values(), key=lambda par: tal[par[0]])
    return Anmarkning(
        "geometripraxis",
        f"registrerad som {sort[1]} — ovanligt för typen: {antal} av "
        f"{totalt} bekräftade {typ.lower()} är {sort[1]}, "
        f"{tal[vanligast[0]]} är {vanligast[1]}. "
        "Kan vara riktigt om lämningen är mindre än vanligt eller ligger "
        "vid en fastighetsgräns",
        tabell,
        post["fid"],
        typ,
        kalla=KALLA_REGISTRET,
    )


# Hur nara en ny lamning far ligga en redan registrerad av samma typ innan
# det ar vart en fraaga.
#
# Talet ar ett arbetsmatt och kommer inte ur nagon kalla. Skalet att det ar
# sa stort som tjugo meter: uttaget bar inte RAA:s lagesosakerhet, och aldre
# registreringar ar ofta inmatta med samre metoder -- den publicerade
# L1946:3142 anger 30 m och inmatningskvalitet "dalig". Tva registreringar
# inom det avstandet kan mycket val vara samma lamning.
NARHET = 20


def _mittpunkt(blob: bytes | None) -> tuple[float, float] | None:
    from arkstod.faltdel.geometri import omslutande

    try:
        ruta = omslutande(blob)
    except (ValueError, struct.error):
        return None
    if ruta is None:
        return None
    minx, maxx, miny, maxy = ruta
    return (minx + maxx) / 2, (miny + maxy) / 2


def granska_narhet(
    anslutning: sqlite3.Connection,
    tabell: str,
    fid: int,
    lamningstyp: str,
    geometri: bytes | None,
    egna: set[int],
    narhet: float = NARHET,
) -> Anmarkning | None:
    """Ligger den nya lamningen ovanpa en som redan ar registrerad?

    Uttaget bar lanets alla registrerade lamningar, och de har legat oanvanda.
    Star man i skogen och prickar en kolbotten som redan finns i registret ar
    det inget verktyget kan avgora -- men det kan saga att den ar dar.

    Bara mot lamningar av **samma typ**, och bara for lamningar jobbet sjalvt
    skapat. Utan de tva villkoren blir det brus: i ett tatt omrade ligger det
    alltid nagot inom tjugo meter.

    Rtree-indexet gor sokningen billig -- det ar GeoPackagens eget, och det
    finns i varje uttag.
    """
    mitt = _mittpunkt(geometri)
    if mitt is None or not lamningstyp:
        return None
    x, y = mitt

    # Rtree-indexet forst nar det finns -- det ar GeoPackagens eget och
    # sparar en genomgang av lagret. Saknas det (en handbyggd arbetsfil,
    # eller ett prov) gaar fragan i stallet pa lamningstypen, och den ar
    # smal nog: en enda typ av lanets alla lamningar.
    villkor = '"lamningstyp" = ?'
    parametrar: list = [lamningstyp]
    try:
        kandidater = [
            rad[0]
            for rad in anslutning.execute(
                f'SELECT id FROM "rtree_{tabell}_geometri"'
                " WHERE maxx >= ? AND minx <= ? AND maxy >= ? AND miny <= ?",
                (x - narhet, x + narhet, y - narhet, y + narhet),
            )
        ]
        grannar = [rad for rad in kandidater if rad != fid and rad not in egna]
        if not grannar:
            return None
        villkor += " AND fid IN (" + ", ".join("?" for _ in grannar) + ")"
        parametrar += grannar
    except sqlite3.OperationalError:
        pass

    traffar = []
    for granne, nummer, blob in anslutning.execute(
        f'SELECT fid, lamningsnummer, geometri FROM "{tabell}" WHERE {villkor}',
        parametrar,
    ):
        if granne == fid or granne in egna:
            continue
        annan = _mittpunkt(blob)
        if annan is None:
            continue
        avstand = math.hypot(annan[0] - x, annan[1] - y)
        if avstand <= narhet:
            traffar.append((round(avstand), nummer or f"fid {granne}"))

    if not traffar:
        return None
    traffar.sort()
    beskeden = ", ".join(f"{nummer} ({avstand} m)" for avstand, nummer in traffar[:3])
    return Anmarkning(
        regel="närhet",
        text=(
            f"Det finns redan {len(traffar)} registrerad"
            f"{'e' if len(traffar) > 1 else ''} {lamningstyp.lower()} inom"
            f" {int(narhet)} m: {beskeden}. Är det samma lämning?"
        ),
        tabell=tabell,
        fid=fid,
        lamningstyp=lamningstyp,
        kalla="uttagets egna registreringar",
    )


def yta_utan_matt(tabell: str, post: dict) -> Anmarkning | None:
    """En yta vars storlek inte gaar att prova mot nagot.

    Fornreg: *Geometrierna ska sa langt som mojligt stamma med den storlek
    som finns redovisad i beskrivningen till lamningen.* Star ingen storlek i
    beskrivningen finns ingenting att stamma mot, och for en yta ar det en
    verklig lucka -- ytan pastar en utbredning som ingen har skrivit ned.

    For en punkt sags ingenting. Punkten ar grundfallet och pastar ingen
    utbredning alls.
    """
    if tabell != "polygon":
        return None
    rektangel = omslutande(post.get("geometri"))
    if rektangel is None:
        return None
    bredd = max(rektangel[1] - rektangel[0], rektangel[3] - rektangel[2])
    return Anmarkning(
        "geometri",
        f"registrerad som yta, {bredd:.0f} m bred, men beskrivningen anger "
        "ingen storlek att stämma av mot",
        tabell,
        post["fid"],
        post.get("lamningstyp") or "",
        kalla=KALLA_FORNREG,
    )




# Falt som gaar att fylla i medan man staar kvar, och som ingen kan fylla i
# efterat. Skadebeskrivningen staar inte har: den ar sedan i dag ett hart
# villkor och slipper igenom overhuvudtaget inte.
def sammanfatta_aterstaende(rader) -> tuple[str, bool]:
    """Raderna som en text att visa, och om nagot alls aterstar.

    Bor har sa att knappen pa blanketten och menyvalet inte kan saga olika
    saker om samma sak.
    """
    if not rader:
        return "Ingenting återstår på dina egna lämningar.", False
    rad, tom = chr(10), chr(10) * 2
    stycken = []
    for _tabell, tid, typ, besked in rader:
        rubrik = f"TID {tid} — {typ}" if typ else f"TID {tid}"
        stycken.append(rubrik + rad + "  " + (rad + "  ").join(besked))
    antal = len(rader)
    return (
        f"{antal} lämning{'ar' if antal > 1 else ''} har något kvar:"
        + tom + tom.join(stycken)
    ), True


def granska_egna(
    anslutning: sqlite3.Connection,
) -> list[tuple[str, int | None, str, list[str]]]:
    """Vad som aterstar pa jobbets egna lamningar, tabell for tabell.

    Leveranslistan hittar samma saker, men den laser man pa kontoret. Det
    ar for sent for allt som bara gaar att se pa platsen: mattmetoden man
    anvande, traditionen nagon berattade, geometrisorten man ritade i.

    Urvalet ar de lamningar som bar ett lasbart lopnummer -- det ar
    stampeln, och den satts sa fort man rort blanketten. Lansets ovriga
    lamningar ar inte vaara att svara for.
    """
    ut: list[tuple[str, int | None, str, list[str]]] = []
    for tabell in ("point", "linestring", "polygon"):
        try:
            kolumner = {
                rad[1] for rad in anslutning.execute(
                    f'PRAGMA table_info("{tabell}")')
            }
        except sqlite3.Error:
            continue
        if not kolumner or "TID" not in kolumner:
            continue
        anslutning.row_factory = sqlite3.Row
        for rad in anslutning.execute(
            f'SELECT * FROM "{tabell}" WHERE "TID" IS NOT NULL'
            ' AND trim(CAST("TID" AS TEXT)) <> \'\''
        ):
            post = dict(rad)
            try:
                nummer = int(post["TID"])
            except (TypeError, ValueError):
                continue
            typ = post.get("lamningstyp") or ""
            besked = [
                anmarkning.text
                for anmarkning in granska_status(tabell, post, typ)
                if anmarkning.regel != "obekräftad"
            ]
            besked += [a.text for a in granska_matning(tabell, post, typ)]
            geometri = granska_geometri(
                tabell, post, post.get("beskrivning") or ""
            )
            if geometri is not None and geometri.regel == "geometri":
                besked.append(geometri.text)
            if besked:
                ut.append((tabell, nummer, typ, besked))
    return sorted(ut, key=lambda rad: (rad[1] is None, rad[1] or 0))
