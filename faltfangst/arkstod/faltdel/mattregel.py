"""Falthandbokens allmanna formregler for matt.

Den har modulen holl tidigare en *harledd* mattregel per lamningstyp: hette
typen nagot med "grop" gavs gropregeln, annars totalmattet. Det var fel pa tva
satt. Regeln fanns redan skriven, per lamningstyp, i Exempelsamlingen -- och
falthandboken pekar sjalv dit: "For detaljerade instruktioner gallande
beskrivning av varje enskild lamning hanvisas till exempelsamlingen." Att
harleda den ur namnet var att gissa fram nagot som gick att lasa.

Dessutom limmades reglerna ihop. En typ med flera egenskapsvarden fick en
basregel plus en regel per varde, sammanfogade till en text -- och for
Kolningsanlaggning blev resultatet tre motstridiga anvisningar efter varandra:
"Hela lamningens storsta utbredning. ... Bottnens matt forst, rannan darefter.
Gropens matt forst, vallen darefter."

Per typ kommer nu i stallet:

  * `beskrivningsprincip` -- kallans egna ord, en per lamningstyp
  * `beskrivningsexempel` -- fardiga beskrivningar, nycklade pa egenskapsvarde

Se `arkstod.lamningstyper.exempel`.

Kvar har ligger det som faktiskt ar allmant: siffrornas form. De galler varje
lamningstyp och hor darfor inte hemma som en rad per typ -- de star en gaang i
formularet. Falthandboken sager dem rakt ut, och de citeras darfor har i
stallet for att harledas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

KALLA = "Fälthandbok i arkeologisk inventering 2.0 (2023-11-28), Jamtli. CC BY."
NIVA = "regional erfarenhet"


@dataclass(frozen=True)
class Formregel:
    """En regel for hur matt skrivs. Galler alla lamningstyper."""

    rubrik: str
    text: str
    kalla: str = KALLA
    niva: str = NIVA


# Ordagrant efter falthandbokens avsnitt om beskrivning. Ordningen ar
# handbokens: forst vilka matt och i vilken foljd, sedan hur de skrivs, sist
# varifran de mats.
FORMREGLER: tuple[Formregel, ...] = (
    Formregel(
        "Ordning",
        "Längd (med längdriktning inom parentes), bredd, höjd/djup. "
        "Längdorienteringen anges med det längsta värdet först och riktningen "
        "enligt huvudväderstrecken, till exempel 80×30 m (NNV–SSÖ).",
    ),
    Formregel(
        "Konstruktioner",
        "Därefter beskrivs konstruktioner vanligtvis från insidan och ut, "
        "från centrum och ut mot kanterna.",
    ),
    Formregel(
        "Enhet",
        "Avstånd och storleksmått anges i meter med en eller högst två "
        "decimaler: 1 m, 1,2 m eller 1,45 m. Undantagna är skålgropar, "
        "ristningar och inskriptioner som anges i centimeter utan decimaler.",
    ),
    Formregel(
        "Djup och höjd",
        "Djup mäts alltid från ursprunglig markyta, aldrig till vallens "
        "överkant. Även höjder mäts från markytan och inte från botten av en "
        "eventuell grop i lämningen.",
    ),
    Formregel(
        "Antal",
        "Antal i uppräkningar anges i siffror. Antal under 10 bör inte "
        "uppskattas — använd inte ”ca 4” eller ”ett 5-tal”.",
    ),
)


# Vaderstrecken, som kallorna skriver dem. Sexton punkter, och ostlig
# riktning alltid med prickar.
#
# **Raknat i manualerna, inte i registret.** Materialet ar Exempelsamling 1.0
# (2008) -- 387 beskrivningsexempel och 153 beskrivningsprinciper -- samt
# lamningstypslistans egna definitioner och kommentarer. Redan registrerade
# lamningar ar inte kalla for hur nagot ska skrivas: de bar egna fel, och en
# raknad majoritet bland dem hade bara varit en majoritet.
#
# Utfallet: 390 forekomster med O-med-prickar, noll med O.
VADERSTRECK: tuple[str, ...] = (
    "N", "NNÖ", "NÖ", "ÖNÖ", "Ö", "ÖSÖ", "SÖ", "SSÖ",
    "S", "SSV", "SV", "VSV", "V", "VNV", "NV", "NNV",
)

# Langdriktningens skiljetecken. Falthandboken skriver regeln och visar den:
# "80×30 m (NNV–SSÖ)" -- se FORMREGLER, "Ordning". Raknat pa 476 streckpar i
# manualerna staar 470 med tankstreck, 6 med bindestreck och 4 med mellanslag
# omkring; de faa avvikelserna ar kallornas egna.
TANKSTRECK = "–"

# **Andra medvetna undantaget, av samma skal som gangertecknet.** Verktyget
# skriver bindestreck: det finns pa faltdatorns tangentbord, tankstrecket
# maste letas fram. Bada laeses -- se GODTAGNA_STRECK -- sa en text som
# kommer fran RAA med tankstreck anmarks inte pa.
STRECK = "-"
GODTAGNA_STRECK: tuple[str, ...] = (TANKSTRECK, STRECK)


def inleder_ratt(streck: str) -> bool:
    """Nordlig riktning forst, i andra hand ostlig.

    Falthandboken: "Langdorienteringen anges med det langsta vardet forst och
    riktningen enligt huvudvaderstrecken, till exempel 80x30 m (NNV-SSÖ)."
    """
    streck = streck.upper()
    if streck.startswith(("N", "S")):
        return streck.startswith("N")
    return streck.startswith(("Ö", "O"))


def axel(barning: float) -> str:
    """Barningen som ett streckpar i ratt ordning: N–S, Ö–V, NNV–SSÖ.

    Ordningen ar inte kosmetik. Verktyget skriver sjalvt huvudriktningen i
    ett fangstgropssystems beskrivning, och den forsta versionen gav
    "SÖ–NV" -- en text som verktygets egen kontroll hade anmarkt pa. Regeln
    bor darfor har, dar bade den som skriver och den som granskar hamtar
    den.
    """
    ett = VADERSTRECK[round(barning / 22.5) % 16]
    tva = VADERSTRECK[round((barning + 180) / 22.5) % 16]
    return f"{ett}{STRECK}{tva}" if inleder_ratt(ett) else f"{tva}{STRECK}{ett}"


def motsatt(streck: str) -> str:
    """Vaderstrecket mitt emot. Tom strang om det inte ar ett vaderstreck.

    En langdriktning ar en axel: bada andarna ar samma linje, sett at var
    sitt hall. "NÖ–SSV" ar darfor inte en riktning utan tva.
    """
    streck = streck.upper()
    if streck not in VADERSTRECK:
        return ""
    return VADERSTRECK[(VADERSTRECK.index(streck) + 8) % 16]


def formregler() -> list[Formregel]:
    """Handbokens allmanna formregler, i handbokens ordning."""
    return list(FORMREGLER)


# Vid vilken storlek ett matt slutar vara meningsfullt pa metern nar.
#
# Gransen var forst raknad i Blekingeuttaget -- alltsa i redan registrerade
# lamningar, som inte ar kalla for hur nagot ska skrivas. Den ar nu raknad om
# i manualerna, och de sager samma sak tydligare:
#
#     under 20 m    851 heltalsmatt, varav 19 % femtal
#     20-99 m       176 heltalsmatt, varav 94 % femtal
#     100 m och mer  69 heltalsmatt, varav 97 % femtal
#
# Gransen ligger alltsa dar Exempelsamlingen sjalv lagger den. Under tjugo
# meter ar femtalen for grova -- en gardstomt pa 12 m ar inte 10 -- och over
# den skriver kallan knappast nagot annat an femtal.
AVRUNDNINGSGRANS = 20


def avrundat(matt: float, storsta: float | None = None) -> int:
    """Mattet som en manniska skriver det: femtal over 20 m, annars heltal.

    Steget valjs av lamningens **storsta** matt och inte av talet i handen.
    Annars blir en yta pa 35×17 skriven som "35×17 m" -- ena talet i femtal
    och andra pa metern -- medan Exempelsamlingen skriver "45×20", "60×30",
    "85×50". Ar lamningen stor nog att avrundas ar den det ocksa i sin
    smala led.
    """
    if (storsta if storsta is not None else matt) >= AVRUNDNINGSGRANS:
        return int(round(matt / 5) * 5)
    return int(round(matt))


# Gangertecknet mellan tva matt.
#
# **Ett medvetet undantag, beslutat av den som anvander verktyget.** Raknat i
# manualerna skriver Exempelsamlingen och lamningstypslistan 528 matt med
# gangertecknet × och noll med bokstaven x, och falthandboken visar × i sin
# egen formregel -- "80×30 m (NNV–SSÖ)", se FORMREGLER. Kallorna ar alltsa
# entydiga, och verktyget foljer dem anda inte.
#
# Skalet ar faltdatorn. Bokstaven x finns pa varje tangentbord; × maste
# letas fram, och en text som ska kunna rattas for hand i skogen ska inte
# innehalla tecken som inte gaar att skriva dar. Vad som lases in ar en
# annan sak -- kontrollernas uttryck tar bada, se kontroller._UTBREDNING.
#
# Undantaget staar har och inte i data eftersom det galler alla
# lamningstyper. De typvisa undantagen -- "bottnens storlek forst" och de
# ovriga forydliganden falthandboken gor till Exempelsamlingens princip --
# bor i tabellen `beskrivningstillagg`, en rad per lamningstyp.
GANGER = "x"


def ytmatt(langd: float, bredd: float, barning: float) -> str:
    """Ytans matt som handboken skriver dem: "65x45 m (N–S)".

    Falthandboken: *Langdorienteringen anges med det langsta vardet forst
    och riktningen enligt huvudvaderstrecken, till exempel 80x30 m
    (NNV-SSÖ).* Riktningen kommer ur `axel` och inte ur en egen rakning --
    samma kalla som kontrollen anvander, sa det som skrivs in inte kan
    anmarkas pa.
    """
    return (
        f"{avrundat(langd, langd)}{GANGER}{avrundat(bredd, langd)} m"
        f" ({axel(barning)})"
    )


# Vilken form mattet tar staar i lamningstypens egen beskrivningsprincip,
# och behover darfor inte skrivas som en lista har.
#
# Rapporterat fran falt: *ett fangstgropssystems matt skrivs inte 590x100 m
# (NÖ-SV) utan ca 640 m (huvudriktning NÖ-SV).* Och riktigt: principen for
# Fangstgropssystem sager "Forst anges hela systemets langd och
# huvudriktning" -- ingen bredd. Detsamma for sju typer till.
#
# Uppmatt mot listans 157 principtexter: 96 sager "langd×bredd med
# huvudriktning", 8 sager langd utan bredd -- Drag, Fardvag, Fardvagssystem,
# Fangstgropssystem, Gravhagnad, Hagnad, Kanal, Vad. Det ar den skillnad
# knappen missade: den gav ytmatt aat allt som ritats som en yta.
_BARA_LANGD = re.compile(r"längd (?:med|och) huvudriktning")
_LANGD_BREDD = "längd×bredd"


def bara_langd(princip: str) -> bool:
    """Sager typens princip langd utan bredd?

    Ett fangstgropssystem ritas som en yta -- "sammanbinds groparna till ett
    system med en omgivande begransningslinje" -- men beskrivs anda med en
    enda langd. Geometrin sager alltsa inte vilket matt som ska skrivas.
    """
    if not princip:
        return False
    return _LANGD_BREDD not in princip and bool(_BARA_LANGD.search(princip))


def skriver_huvudriktning(exempeltexter) -> bool:
    """Skriver typens egna exempel ut ordet, eller bara vaderstrecket?

    Bada formerna staar i Exempelsamlingen, och rakningen avgor vilken som
    ar normen: av 476 riktningsparenteser ar 472 bara "(NÖ–SV)". Ordet
    "huvudriktning" star i fyra, och de tillhor tre typer -- Fangstgropssystem,
    Hagnad, Stridsvarn -- alltsa dar foremalet slingrar sig och riktningen ar
    en huvudsaklig och inte en uppmatt strackning.

    Regeln laeses darfor ur typens egna exempel i stallet for att gissas ur
    vaderstreckets grovlek: skriver exemplet ordet skriver verktyget det med.
    """
    return any("huvudriktning" in (t or "") for t in exempeltexter)


def langdmatt(langd: float, barning: float, huvudriktning: bool = False) -> str:
    """Ett enda matt med sin riktning: "ca 640 m l (huvudriktning NÖ–SV)".

    "ca" darfor att talet ar en utstrackning raknad ur en handritad
    begransningslinje och avrundad till femtal -- samma ord som verktyget
    redan satter nar det skriver ett fangstgropssystems beskrivning sjalvt.
    """
    riktning = axel(barning)
    if huvudriktning:
        riktning = f"huvudriktning {riktning}"
    return f"ca {avrundat(langd)} m l ({riktning})"


def linjematt(langd: float, barning: float) -> str:
    """Linjens matt: "140 m l (NNV–SSÖ)".

    En linje har ingen bredd att ange -- halvagens bredd hor till
    beskrivningen, inte till strackningen.
    """
    return f"{avrundat(langd)} m l ({axel(barning)})"
