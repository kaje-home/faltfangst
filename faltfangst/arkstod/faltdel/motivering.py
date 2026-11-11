"""Nar en motivering till antikvarisk bedomning kravs.

KRFS 2022:3 och falthandboken sager samma sak: for lamningstyper som kan ha
tillkommit antingen fore eller efter 1850 ska grunden for antagandet om
tillkomsttid anges nar lamningen bedoms som fornlamning. Det ar ett villkorat
obligatoriefalt, inte en paminnelse man kan klicka bort.

Fragan modulen svarar pa ar smal: gor listans regel for den har typen 1850
avgorande? Det ar ett pastaende om regelns form, inte om utfallet -- och just
darfor tillatet. Ett stod som daremot gissade utfallet ur typen skulle gora
precis det falthandboken forbjuder.

Klassen ar lika viktig som kravet. "Ingen motivering behovs" och "listan sager
att typen alltid ar fornlamning" ar tva olika besked, och det andra ar det som
hjalper i falt. Formularet visar darfor klassen och listans egna ord, inte
bara ett tomt eller ifyllt falt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Listan formulerar sig i flera varianter. Pa ett stalle saknar kallan
# blanksteg: "tillkommit fore1850".
_ALLTID = re.compile(
    r"i och med att (?:den|det|de|dessa)?\s*alltid uppfyller"
    r"|alltid har tillkommit före\s*1850"
    r"|är alltid att betrakta som fornlämning"
    # Fangstgrop och Fangstgropssystem: listan gor dateringsbedomningen sjalv
    # och drar slutsatsen for hela typen -- "Gropfangst forbjods i lag 1864
    # men troligen har inga fangstgropar tillkommit 1850 eller senare.
    # Lamningstypen bedoms darfor uppfylla ... rekvisit". Da finns ingen
    # datering kvar for inventeraren att motivera.
    r"|[Ll]ämningstypen bedöms därför uppfylla"
)

# Listan skriver samma villkor i manga satsformer: "kan antas ha tillkommit",
# "kan antas att ha tillkommit", "kan antas att de tillkommit", "det kan antas
# att de tillkommit". Mellanledet ar fritt och far darfor vara det -- det som
# maste sta ar "antas", nagon form av tillkomma eller forlisa, och 1850.
_BEROENDE = re.compile(
    r"antas[^.]{0,40}?(?:tillkommit|förkommit|förlist)\s*före\s*1850"
    # Omrade med fartygslamningar villkorar utan "antas": "... och
    # fartygs /batlamningarna forlist fore 1850."
    r"|lämningarna förlist\s*före\s*1850"
)
_ALDRIG = re.compile(
    r"kan (?:aldrig|inte) bedömas som fornlämning"
    r"|[Bb]edöms aldrig som fornlämning"
    r"|uppfyller aldrig rekvisitet"
    r"|är inte en kulturhistorisk lämning"
)
_HANVISAR = re.compile(r"^Se (?:även )?antikvarisk bedömning för")

DATERINGSBEROENDE = "dateringsberoende"
ALLTID = "alltid"
ALDRIG = "aldrig"
HANVISAR = "hanvisar"
# Bedomningen hanger pa lamningens form eller pa vilket sammanhang den ingar
# i -- inte pa nagot antagande om ar. Kravet galler anda, men det som ska
# redovisas ar nagot annat an dateringen, och det ska formularet saga.
FORMBEROENDE = "formberoende"
OKLART = "oklart"

KALLA = "Lämningstypslistan 5.0, uppslagsordets antikvariska bedömning"

# Tre typer formulerar sin bedomning pa ett satt som ingen av formerna ovan
# fangar, och det ar inte en brist i monstren utan i sak: for dem ar det inte
# dateringen som avgor. De skrivs darfor ut, med den mening ur listan som
# visar varfor.
#
# En egen tabell och inte ett monster till: formuleringarna ar unika for
# respektive typ, och ett monster som bara traffar en post ar en tabellrad
# forkladd till regel. Testet kraver att varje post har verkligen skulle ha
# hamnat i OKLART -- annars dolde tabellen ett monster som gaar att forbattra.
SARFALL: dict[str, tuple[str, str]] = {
    "Fossil åker": (
        FORMBEROENDE,
        "För en fossil åker gäller inte generellt att den ska bedömas som "
        "fornlämning enbart för att ett antagande gjorts om att lämningen "
        "tillkommit före 1850. Bedömningen görs på åkerytans form: profil, "
        "terrasskanter, stensträngar eller vallar.",
    ),
    "Röjningsröse": (
        FORMBEROENDE,
        "Röjningsrösen har brukats in i sen tid och bedöms inte generellt "
        "uppfylla rekvisitet äldre tiders bruk. Om röjningsröset ingår i "
        "fossil åkermark eller annan lämning som bedömts som fornlämning "
        "bedöms även röjningsröset som fornlämning.",
    ),
    "Slagfält": (
        HANVISAR,
        "Slagfält utgör sällan lämningar i sig. Finns lämningar efter "
        "speciella konstruktioner — stridsvärn, gravar — bedöms dessa som "
        "fornlämning, men registreras under relevant lämningstyp med "
        "hänvisning till slagfältet.",
    ),
}

# Vad formularet ska saga for varje klass. Kravet ar en sak, beskedet en
# annan: "ingen motivering behovs" hjalper inte den som undrar varfor.
# Beskeden namner rekvisiten och inte bara arsgransen.
#
# "1850 avgor" stod ensamt, och det ar bade sant och vilseledande:
# arsgransen ar det sista man prover, inte det enda. Kulturmiljolagen kraver
# tre saker av en fornlamning -- en fysisk lamning efter manniskors
# verksamhet, aldre tiders bruk, och varaktigt overgiven -- och dateringen
# kommer nar de haller.
#
# Ordningen ar rekvisitmallens egen, och skalet staar dar: "dateringen ar
# aldrig det enda argumentet, den kommer nar allt annat ar bekraftat".
BESKED: dict[str, str] = {
    ALLTID: "Listan: typen uppfyller alltid rekvisiten — forna tider, äldre "
    "tiders bruk, varaktigt övergiven. Dateringen motiveras inte.",
    ALDRIG: "Listan: typen bedöms aldrig som fornlämning.",
    HANVISAR: "Bedömningen görs på en annan lämningstyp — se den.",
    DATERINGSBEROENDE: "Pröva först fysisk lämning, varaktigt övergiven och "
    "äldre tiders bruk. Ange grunden för samtliga. Sist tillkomsttiden: "
    "1850 avgör.",
    FORMBEROENDE: "Dateringen avgör inte ensam. Pröva övergivenhet och äldre "
    "tiders bruk, och ange vad bedömningen vilar på.",
    OKLART: "Listans formulering följer ingen känd form — motivera mot bruk "
    "och övergivenhet, och sist tillkomsttid.",
}


@dataclass(frozen=True)
class Motiveringskrav:
    """Om 1850 avgor for en lamningstyp, och vad i texten som visar det."""

    lamningstyp: str
    klass: str
    grund: str

    @property
    def kravs(self) -> bool:
        """Kravs motivering nar lamningen bedoms som fornlamning?

        Oklart raknas som ja. En motivering for mycket kostar en mening; en
        for lite ger ett beslut utan redovisad grund.
        """
        return self.klass in (DATERINGSBEROENDE, FORMBEROENDE, OKLART)

    @property
    def besked(self) -> str:
        """Den mening formularet visar for klassen."""
        return BESKED[self.klass]


def klassificera(lamningstyp: str, bedomning: str) -> Motiveringskrav:
    """Laser listans bedomningstext och avgor om 1850 ar avgorande."""
    text = " ".join(bedomning.split())

    if _HANVISAR.match(text):
        return Motiveringskrav(
            lamningstyp, HANVISAR, "hänvisar till annan lämningstyps bedömning"
        )

    beroende = _BEROENDE.search(text)
    alltid = _ALLTID.search(text)

    # Bada formerna i samma text betyder att typen kan ga at bada hallen --
    # Hagnad ar fornlamning som stenstrang men provas som stenmur. Da kravs
    # motivering.
    if beroende:
        return Motiveringskrav(
            lamningstyp, DATERINGSBEROENDE, f"listans ord: ”{beroende.group(0)}”"
        )
    if alltid:
        return Motiveringskrav(
            lamningstyp, ALLTID, f"listans ord: ”{alltid.group(0)}”"
        )
    if _ALDRIG.search(text):
        return Motiveringskrav(
            lamningstyp, ALDRIG, "listan utesluter fornlämning för typen"
        )
    if lamningstyp in SARFALL:
        klass, grund = SARFALL[lamningstyp]
        return Motiveringskrav(lamningstyp, klass, grund)
    return Motiveringskrav(
        lamningstyp, OKLART, "listans formulering följer ingen av de kända formerna"
    )


def krav(
    poster: list[tuple[str, str]],
    ingaende: dict[str, list[str]] | None = None,
) -> list[Motiveringskrav]:
    """Klassificerar alla lamningstyper. `poster` ar (benamning, bedomning).

    `ingaende` ar sammansatta typers delar. En typ vars regel bara hanvisar
    vidare -- "Se antikvarisk bedomning for den ingaende lamningstypen" --
    arver kravet fran den den pekar pa. Utan det slipper Fardvagssystem
    motiveringskravet trots att Fardvag har det, och kravet gaar forlorat
    just nar flera lamningar registreras tillsammans.
    """
    resultat = [klassificera(benamning, bedomning) for benamning, bedomning in poster]
    if not ingaende:
        return resultat

    per_namn = {post.lamningstyp: post for post in resultat}
    bedomningar = dict(poster)
    for index, post in enumerate(resultat):
        if post.klass != HANVISAR or post.lamningstyp in SARFALL:
            continue
        namngivna = ingaende.get(post.lamningstyp, [])
        if not namngivna:
            # Fardvagssystem har ingen "Ingaende lamningstyper"-rad utan
            # namner typen bara i bedomningstexten. Den ar ordagrann och
            # gaar att folja: "Se antikvarisk bedomning for den ingaende
            # lamningstypen Fardvag."
            namngivna = [
                namn
                for namn in per_namn
                if namn != post.lamningstyp
                and namn in bedomningar.get(post.lamningstyp, "")
            ]
        delar = [per_namn[namn] for namn in namngivna if namn in per_namn]
        if any(del_.kravs for del_ in delar):
            arvd = next(del_ for del_ in delar if del_.kravs)
            resultat[index] = Motiveringskrav(
                post.lamningstyp,
                DATERINGSBEROENDE,
                f"ärvt från ingående {arvd.lamningstyp}: {arvd.grund}",
            )
    return resultat


# Rekvisiten, som de brukar formuleras. En motivering som namner nagot av
# dem staar pa mer an arstalet.
_REKVISIT = re.compile(
    r"forna tider|äldre tiders bruk|varaktigt övergiv|övergivenhet"
    r"|bruksrekvisit|åldersrekvisit|ur bruk|upphört|inte längre"
    r"|allmänt förekommande|typologi|konstruktion|läge|kontext"
    r"|karta|belägg|källa|datering av|14c|kol-?14|analys",
    re.IGNORECASE,
)
_ARSTALET = re.compile(r"\b1850\b|\bdatering|\bdaterad", re.IGNORECASE)


def vilar_bara_pa_arstalet(text: str | None) -> bool:
    """Om motiveringen inte sager mer an att lamningen ar fore 1850.

    Falthandboken s. 20: *Dateringen fore ar 1850 ska aldrig vara det enda
    argumentet for att nagot ar en fornlamning.* Skalet staar pa s. 19: den
    som laser beskrivningen senare ska aldrig behova fundera over varfor en
    lamning har bedomts pa ett visst satt.

    Provet ar med flit trubbigt aat ena hallet: det slaar bara till nar
    arstalet **och inget annat** bar texten. Namner motiveringen ett
    rekvisit, en konstruktion, ett lage, en karta eller en analys sags
    ingenting -- da finns ett andra argument, och om det haaller ar inte
    verktygets sak att avgora.
    """
    if not text or not text.strip():
        return False
    return bool(_ARSTALET.search(text)) and not _REKVISIT.search(text)
