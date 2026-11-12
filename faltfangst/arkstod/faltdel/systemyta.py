"""Att lagga ytan runt punkterna -- den del som behover QGIS geometrimotor.

Klungorna och matten raknas i `sammansatt`, utan bibliotek och utan QGIS.
Har gors bara det som kraver riktig geometri: buffra ihop kanterna till en
omgivande begransningslinje, och skriva in ytan i lagret.

Formen foljer beskrivningsprincipen: *pa kartan ritas varje grop in som en
punkt, darefter sammanbinds groparna till ett system med en omgivande
begransningslinje.* Kanterna ar tradet fran `sammansatt.kanter`, och
begransningslinjen ar en buffert kring dem.

Verktyget skapar ytan men avgor ingenting: beskrivningen ar ett utkast med
en oppen lucka, och den antikvariska bedomningen lamnas tom. Det ar
arkeologen som avgor om groparna bildar en funktionell enhet -- se
`sammansatt` for varfor den gransen gaar dar.

Tva vagar in, och skillnaden ar vem som bedomt avstandet:

* `foresla` kedjar vid grundregelns 50 m och namner de klungor som ligger
  nara varandra.
* `skapa_av_valda` tar de gropar som ar markerade i kartan och fragar inte
  om avstand alls. Da har nagon redan tittat pa terrangen, och det ar den
  bedomning kommentaren talar om.

Antalet galler bada vagarna: "minst fem" ar ett tal i listan.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from arkstod.faltdel import sammansatt

# Faltet som sager att en grop ar del av ett system. Se falt.py: en sadan
# grop levereras inte som en egen lamning, utan som systemets del.
INGAR_I = "ingar_i"
TYPFALT = "lamningstyp"


@dataclass
class Resultat:
    skapade: list[str] = field(default_factory=list)
    for_faa: list[int] = field(default_factory=list)
    narliggande: list[tuple[int, int, int]] = field(default_factory=list)
    beroorda_delar: int = 0


def levande_system(ytlager, regel) -> set:
    """Lopnumren pa de sammansatta lamningar som faktiskt finns.

    Behovs for att `ingar_i` ska ga att lita pa. Tar man bort en systemyta i
    kartan staar dess delar kvar med sitt marke, och da ar de upptagna av
    nagot som inte langre finns: forslaget hittar inga lediga gropar, och
    markeringen sager att inga av de markerade hor till typen. Bada
    atgarderna slutar fungera, och ingenting sager varfor.

    Rapporterat fran falt, och det ar inget kantfall: att titta pa ytan,
    tycka att den blev fel och ta bort den ar det forsta man gor.
    """
    from qgis.core import QgsExpression, QgsFeatureRequest

    begaran = QgsFeatureRequest()
    begaran.setFlags(QgsFeatureRequest.NoGeometry)
    begaran.setFilterExpression(
        f'"{TYPFALT}" = {QgsExpression.quotedValue(regel.sammansatt)}'
    )
    levande = set()
    for post in ytlager.getFeatures(begaran):
        try:
            levande.add(int(post["TID"]))
        except (TypeError, ValueError):
            continue
    return levande


def _ledig(post, levande: set) -> bool:
    """Sant om lamningen inte hor till ett system som finns."""
    try:
        return int(post[INGAR_I]) not in levande
    except (TypeError, ValueError):
        return True


def las_punkter(lager, typer, levande: set) -> list[sammansatt.Punkt]:
    """Lamningarna av ratt typ som jobbet sjalvt satt, och som ar lediga.

    Tre villkor:

    * **ratt typ** -- de typer listan sager att den sammansatta bestar av.
      Ett fangstgropssystem har en enda, ett gravfalt tolv.
    * **eget lopnummer** -- TID satts av blanketten och bara av den, sa det
      skiljer jobbets egna lamningar fran RAA:s. Utan det villkoret gick
      forslaget lost pa hela lansuttaget: ett prov mot Blekinge tog med 65
      redan registrerade gropar och ville gora system av dem.
    * **inte upptagen av ett system som finns** -- se `levande_system`. Ett
      marke som pekar pa en borttagen yta ar inget marke.
    """
    from qgis.core import QgsExpression, QgsFeatureRequest

    begaran = QgsFeatureRequest()
    val = ", ".join(QgsExpression.quotedValue(typ) for typ in typer)
    begaran.setFilterExpression(
        f'"{TYPFALT}" in ({val}) and "TID" is not null'
    )
    punkter = []
    for post in lager.getFeatures(begaran):
        if not _ledig(post, levande):
            continue
        geometri = post.geometry()
        if geometri.isEmpty():
            continue
        mitt = geometri.centroid().asPoint()
        punkter.append(
            sammansatt.Punkt(
                fid=post.id(), x=mitt.x(), y=mitt.y(),
                typ=post[TYPFALT] or "",
            )
        )
    return punkter


def yta(kandidat: sammansatt.Kandidat, marginal: int = sammansatt.MARGINAL):
    """Begransningslinjen: kanterna buffrade at bada hallen.

    En buffert och inte ett holje. Ett konvext holje kring en kedja som
    bojer av tar med stora ytor dar det inte finns nagon grop -- ett
    fangstgropssystem foljer en terrangpassage och ar sallan rakt.
    """
    from qgis.core import QgsGeometry, QgsPointXY

    strak = [
        [QgsPointXY(a.x, a.y), QgsPointXY(b.x, b.y)] for a, b in kandidat.kanter
    ]
    if strak:
        linjerna = QgsGeometry.fromMultiPolylineXY(strak)
    else:
        # En ensam grop blir aldrig ett system, men koden ska inte falla pa
        # det -- den anropas ocksa vid provning.
        punkt = kandidat.punkter[0]
        linjerna = QgsGeometry.fromPointXY(QgsPointXY(punkt.x, punkt.y))
    return linjerna.buffer(marginal, 12)


def _beskrivningar(lager, punkter) -> list[str]:
    """Groparnas egna beskrivningar, skrivna i falt.

    De behovs for att slaa ihop matten till systemets beskrivning -- det ar
    dar minsta och storsta diameter kommer ifran. Texterna ror vi inte;
    groparna behaller dem, de levereras bara inte som egna lamningar.
    """
    fidar = {punkt.fid for punkt in punkter}
    return [
        post["beskrivning"]
        for post in lager.getFeatures()
        if post.id() in fidar and post["beskrivning"]
    ]


def _samsta_kvaliteten(lager, punkter):
    """Delarnas samsta matmetod och medelfel. Se status.samsta_kvaliteten."""
    from qgis.core import QgsFeatureRequest

    from arkstod.faltdel.blankettkod import falt
    from arkstod.faltdel.status import samsta_kvaliteten

    fids = {punkt.fid for punkt in punkter}
    begaran = QgsFeatureRequest().setFilterFids(list(fids))
    begaran.setFlags(QgsFeatureRequest.NoGeometry)
    return samsta_kvaliteten(
        (falt(post, "matmet"), falt(post, "medelfel"))
        for post in lager.getFeatures(begaran)
    )


def _granskningsdatum(lager, punkter) -> object:
    """Systemets datum ar besokets, inte kontorsdagens.

    Groparna prickades i falt en viss dag; ytan ritas veckor senare. Det ar
    faltdagen som ar granskningsdatum, sa den senaste av groparnas datum
    ars ut.
    """
    datum = []
    for post in lager.getFeatures():
        if post.id() not in {p.fid for p in punkter}:
            continue
        varde = post["Granskningsdatum"]
        if varde:
            datum.append(varde)
    return max(datum) if datum else None


def skapa(punktlager, ytlager, kandidat, regel, marginal=sammansatt.MARGINAL) -> str:
    """Skriver in en systemyta och markerar groparna som dess delar."""
    from qgis.core import QgsFeature

    from arkstod.faltdel import blankettkod

    if not regel.har_begransningsyta:
        # Handledningen s. 50: fardvagsystem ska inte registreras med en yta
        # for den yttre begransningen, utan endast med linjer. En yta har
        # hade varit ett fel att stada bort pa kontoret.
        raise UtanYta(
            f"{regel.sammansatt} ska inte ha någon yttre begränsningsyta —"
            " systemet registreras som linjer. Fornreg 4.0, s. 50."
        )

    post = QgsFeature(ytlager.fields())
    geometri = yta(kandidat, marginal)
    post.setGeometry(geometri)
    post[TYPFALT] = regel.sammansatt
    post["beskrivning"] = sammansatt.beskrivningsutkast(
        kandidat.matt,
        regel,
        _beskrivningar(punktlager, kandidat.punkter),
        kandidat.punkter,
        # Langden ar ytans, raknad med samma funktion som knappen Matt ur
        # geometrin. Systemet ar den avgransade ytan, marginalen inraknad.
        storlek=blankettkod.matt_for_lamningen(
            ytlager, geometri, "polygon", regel.sammansatt
        ),
    )
    nummer = blankettkod.nasta_lopnummer(ytlager)
    post["TID"] = nummer
    datum = _granskningsdatum(punktlager, kandidat.punkter)
    if datum:
        post["Granskningsdatum"] = datum

    # Handledningen s. 56: ar lamningen inmatt vid flera tillfallen och med
    # olika metoder ar det den samsta kvaliteten som ska anges for helheten.
    # Ytan ar ritad ur punkterna och kan omojligt vara battre an de var.
    kvalitet = _samsta_kvaliteten(punktlager, kandidat.punkter)
    if kvalitet is not None:
        metod, medelfel = kvalitet
        if metod:
            post["matmet"] = metod
        post["medelfel"] = medelfel

    if not ytlager.isEditable():
        ytlager.startEditing()
    ytlager.addFeature(post)

    if not punktlager.isEditable():
        punktlager.startEditing()
    index = punktlager.fields().indexOf(INGAR_I)
    for punkt in kandidat.punkter:
        punktlager.changeAttributeValue(punkt.fid, index, nummer)

    return f"TID {nummer}: {regel.sammansatt}, {kandidat.matt.antal} delar"


def regler_for_arbetsfilen(punktlager) -> dict:
    """Reglerna ur arbetsfilens egen lamningstypslista.

    Varje uttag bar listan som `ark_`-tabeller, sa reglerna behover varken
    laddas ner eller skrivas av. Se `sammansatt.regler`.
    """
    import sqlite3

    kalla = punktlager.dataProvider().dataSourceUri().split("|")[0]
    anslutning = sqlite3.connect(f"file:{kalla}?mode=ro", uri=True)
    try:
        return sammansatt.regler(anslutning)
    finally:
        anslutning.close()


def aktuella_regler(punktlager, ytlager) -> list:
    """Bara de sammansatta typer jobbets egna lamningar kan bilda.

    Listan har tjugoen regler, och att lata anvandaren valja ur dem vore att
    fraaga om nagot datan redan svarar pa: har man inte prickat en enda
    fangstgrop finns det inget fangstgropssystem att foresla.
    """
    from qgis.core import QgsFeatureRequest

    begaran = QgsFeatureRequest()
    begaran.setFlags(QgsFeatureRequest.NoGeometry)
    begaran.setSubsetOfAttributes([TYPFALT, "TID", INGAR_I], punktlager.fields())
    # QGIS NULL ar inget None. `post["TID"] is not None` ar sant aven for ett
    # tomt falt, och da raknades hela lansuttaget som jobbets eget -- alla
    # tjugoen regler slog till. Provet ar att talet gaar att lasa.
    def eget(post) -> bool:
        try:
            int(post["TID"])
        except (TypeError, ValueError):
            return False
        return True

    egna = {
        post[TYPFALT]: []
        for post in punktlager.getFeatures(begaran)
        if post[TYPFALT] and eget(post)
    }
    aktuella = []
    for regel in regler_for_arbetsfilen(punktlager).values():
        if not egna.keys() & set(regel.ingaende):
            continue
        # Ett fardvagssystem har ingen yttre begransningsyta att foresla.
        # Se sammansatt.UTAN_BEGRANSNINGSYTA.
        if not regel.har_begransningsyta:
            continue
        # En lamning som hor till en yta som tagits bort ar ledig igen, och
        # regeln ska darfor stanna kvar i listan. Levande system laeses per
        # regel eftersom lopnumren galler per sammansatt typ.
        aktuella.append(regel)
    return aktuella


class ForFaa(Exception):
    """Fardre gropar an listan kraver. Ett tal, inte en bedomning."""


class UtanYta(Exception):
    """Den sammansatta typen ska inte ha nagon begransningsyta alls."""


def skapa_av_valda(punktlager, ytlager, regel, marginal=sammansatt.MARGINAL) -> str:
    """Gor ett system av de gropar som ar markerade i kartan.

    Ingen avstandsprovning. Den som markerat har sett terrangen, och det ar
    precis den bedomning kommentaren lamnar at arkeologen: avstandet *kan*
    overstiga femtio meter om topografin och sammanhanget visar att groparna
    hor ihop.

    Antalet provas daremot. "Minst fem fangstgropar" staar i definitionen och
    ar inget verktyget far vika pa.
    """
    levande = levande_system(ytlager, regel)
    valda = []
    upptagna: dict[int, int] = {}
    for post in punktlager.selectedFeatures():
        if post[TYPFALT] not in regel.ingaende:
            continue
        if not _ledig(post, levande):
            nummer = int(post[INGAR_I])
            upptagna[nummer] = upptagna.get(nummer, 0) + 1
            continue
        geometri = post.geometry()
        if geometri.isEmpty():
            continue
        mitt = geometri.centroid().asPoint()
        valda.append(
            sammansatt.Punkt(
                fid=post.id(), x=mitt.x(), y=mitt.y(), typ=post[TYPFALT] or ""
            )
        )

    if len(valda) < regel.minsta_antal:
        # Skalet forst. "Noll horde till typen" ar bade osant och obegripligt
        # nar de i sjalva verket redan ar upptagna av ett system som finns.
        if upptagna and not valda:
            var = ", ".join(
                f"TID {nummer} ({antal} st)"
                for nummer, antal in sorted(upptagna.items())
            )
            raise ForFaa(
                f"De markerade lämningarna ingår redan i {var}."
                " Ta bort den sammansatta lämningen först, eller markera"
                " andra lämningar."
            )
        besked = (
            f"{len(valda)} markerade lämningar hör till {regel.sammansatt}"
            f" och är lediga. Listan kräver minst {regel.minsta_antal}."
        )
        if upptagna:
            besked += (
                f" {sum(upptagna.values())} av de markerade ingår redan i en"
                " sammansatt lämning."
            )
        raise ForFaa(besked)

    kandidat = sammansatt.Kandidat(
        punkter=valda,
        matt=sammansatt.mat(valda),
        kanter=sammansatt.kanter(valda),
    )
    return skapa(punktlager, ytlager, kandidat, regel, marginal)


def foresla(
    punktlager,
    ytlager,
    regel,
    avstand: float | None = None,
    marginal: int = sammansatt.MARGINAL,
) -> Resultat:
    """Gaar igenom groparna, skapar ytorna och beskriver det som lamnas kvar.

    Kedjar vid grundregelns avstand ur listan. Det som ligger langre isar
    lamnas at markeringen -- se `skapa_av_valda`.
    """
    avstand = regel.normalt_avstand if avstand is None else avstand
    punkter = las_punkter(
        punktlager, regel.ingaende, levande_system(ytlager, regel)
    )
    rapport = sammansatt.forslag(punkter, regel, avstand)

    resultat = Resultat(
        for_faa=[len(klunga) for klunga in rapport.for_faa],
        narliggande=rapport.narliggande,
    )
    for kandidat in rapport.kandidater:
        resultat.skapade.append(skapa(punktlager, ytlager, kandidat, regel, marginal))
        resultat.beroorda_delar += kandidat.matt.antal
    return resultat
