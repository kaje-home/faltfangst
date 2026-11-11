"""Geometrileveransen till Fornreg: en zip med shapefiler.

Handledningen *Arbeta med lamningsinformation* (Fornreg 4.0, s. 46-47) sager
vad som galler, och tva meningar dar styr hela konstruktionen:

    Attribut som anges for respektive objekt (feature) lagras inte. De
    attribut som tillhor din GIS-fil visas dock i listan nar du laddat upp
    den i Fornreg. Se darfor till att du har tydliga attribut for att
    underlatta ditt arbete.

Zippen ar alltsa en **geometrileverans och ingen attributleverans**.
Beskrivning, bedomning och allt annat skrivs in i Fornreg for hand, ur
leveranslistan. Attributen har finns bara for att man ska kunna se vilken
geometri som ar vilken i uppladdningslistan -- och darfor bar de TID, samma
lopnummer som leveranslistan ar sorterad efter. Det ar den enda kopplingen
som behovs mellan de tva, och den ar en manniska laser.

Ovriga krav ur samma sidor, och alla provas innan zippen skrivs:

* Referenssystemet ska vara SWEREF 99 TM (EPSG:3006).
* Koordinaterna ska innehalla max 3 decimaler.
* Filerna .shp, .shx, .dbf och .prj maste ingaa -- projektionsfilen kravs
  for valideringen aven om standarden inte kraver den. Zippen bar dessutom
  en .cpg: den sager att DBF:en ar UTF-8, och utan den blir åäö en gissning.
* Geometrityperna point, linestring och polygon gaar att ladda upp, **inte
  multipolygon**.
* Ingen lamning far ha dubblerade identiska geometrier, ingen linje far
  korsa sig sjalv, och varje objekt maste ha en geometri.

Samtliga geometrityper far ligga i samma zip, vilket handledningen sager
uttryckligen. Det blir en fil att ladda upp och en att kasta.

Urvalet ar leveranslistans, inte ett eget: `leverans.leverans` avgor vad som
ar rort sedan uttaget, och zippen bar exakt de lamningarna. Ett eget urval
har hade kunnat glida isar fran listan, och da hade man laddat upp en
geometri utan text eller skrivit en text utan geometri.

**Med ett tillagg: delarna.** En fangstgrop som blivit del av ett system ar
ingen egen lamning och staar darfor inte i listan -- men dess geometri hor
till systemet och ska levereras. Beskrivningsprincipen sager det rakt ut:
*pa kartan ritas varje grop in som en punkt, darefter sammanbinds groparna
till ett system med en omgivande begransningslinje.* Systemets geometri ar
alltsa punkterna **och** ytan, och en lamning far ha flera geometrier --
handledningen forutsatter det nar den beskriver hur centrumpunkten satts ut
"mellan geometrierna".

Delarnas TID i filen ar **systemets** och inte deras egen. Det ar TID som
sager vilken lamning en geometri hor till, och i uppladdningslistan ska de
tjugo raderna gaa att se som ett.
"""

from __future__ import annotations

import re
import sqlite3
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from arkstod.faltdel import geometri as geometrimodul
from arkstod.faltdel.leverans import SaknarUtgangslage, leverans

# EPSG:3006. Skrivs som .prj, for utan projektionsfil gaar filen inte att
# validera mot Kulturmiljoregistrets godkanda referenssystem.
SWEREF99TM = 3006

# Max tre decimaler, enligt kraven. Millimeter -- langt under den
# lagesosakerhet en GPS i skog ger, sa ingenting gaar forlorat.
DECIMALER = 3

# Shapefilens faltnamn far vara hogst tio tecken.
FALT = (("TID", "TID"), ("TYP", "lamningstyp"), ("LAMNINGSNR", "lamningsnummer"))

@dataclass(frozen=True)
class Rad:
    """En geometri att leverera, och den lamning den hor till."""

    tabell: str
    fid: int
    # Lamningens lopnummer. For en del ar det systemets, inte dess eget.
    tid: int | None
    typ: str
    lamningsnummer: str
    # Sant for en grop som levereras som del av ett system.
    ar_del: bool = False

    @property
    def namn(self) -> str:
        return f"TID {self.tid}" if self.tid is not None else f"fid {self.fid}"


class SaknarGdal(Exception):
    """Utan GDAL gaar ingen shapefil att skriva."""


@dataclass
class Resultat:
    """Vad som lades i zippen, och vad som inte gick att lagga dit."""

    fil: Path | None = None
    antal: dict[str, int] = field(default_factory=dict)
    anmarkningar: list[str] = field(default_factory=list)

    @property
    def totalt(self) -> int:
        return sum(self.antal.values())


def _ogr():
    try:
        from osgeo import ogr, osr
    except ImportError as fel:  # pragma: no cover -- beror pa miljon
        raise SaknarGdal(
            "GDAL (osgeo) saknas. Kör exporten från QGIS, där den finns."
        ) from fel
    ogr.UseExceptions()
    osr.UseExceptions()
    return ogr, osr


def filnamn(gpkg: Path) -> str:
    """Zippens namn, ur arbetsfilens.

    Arbetsfilen heter `lamningar_lan_jamtland_20260827.gpkg` efter uttaget,
    och zippen ska ga att kanna igen bland nedladdade filer manader senare.
    """
    stam = gpkg.stem
    for prefix in ("lämningar_län_", "lamningar_lan_", "lämningar_", "lamningar_"):
        if stam.startswith(prefix):
            stam = stam[len(prefix):]
            break
    return f"fornreg_{stam}.zip"


def _avrunda(wkt: str) -> str:
    """Klipper koordinaterna till tre decimaler.

    Pa texten och inte pa geometrin: en WKT ser likadan ut for punkt, linje
    och yta, sa en regel racker for alla tre. Att ga in i ringar och delar
    hade varit tre fall som kan bli fel var for sig.
    """
    return re.sub(
        r"-?\d+\.\d+",
        lambda traff: f"{round(float(traff.group()), DECIMALER):.{DECIMALER}f}",
        wkt,
    )


def _granska(ogr, geometri, rad: "Rad") -> str | None:
    """Kraven ur handledningen, provade innan filen skrivs."""
    if geometri is None or geometri.IsEmpty():
        return f"{rad.namn} ({rad.typ}) saknar geometri och kom inte med."
    typ = ogr.GT_Flatten(geometri.GetGeometryType())
    if typ in (ogr.wkbMultiPolygon, ogr.wkbMultiLineString, ogr.wkbMultiPoint):
        return (
            f"{rad.namn} ({rad.typ}) är flerdelad. Fornreg tar emot"
            " point, linestring och polygon — inte multipolygon."
        )
    if typ == ogr.wkbLineString and not geometri.IsSimple():
        return f"{rad.namn} ({rad.typ}) har en linje som korsar sig själv."
    if typ == ogr.wkbPolygon and not geometri.IsValid():
        return f"{rad.namn} ({rad.typ}) har en ogiltig yta."
    return None


def _rader(rapport) -> list["Rad"]:
    """Allt som ska levereras: lamningarna, och delarnas geometrier.

    En del far **systemets** TID. Det ar TID som sager vilken lamning en
    geometri hor till, och i Fornregs uppladdningslista ska systemets yta och
    dess tjugo punkter gaa att se som ett.
    """
    rader = [
        Rad(
            tabell=post.tabell,
            fid=post.fid,
            tid=post.tid,
            typ=post.lamningstyp,
            lamningsnummer=post.lamningsnummer,
        )
        for post in rapport.poster
    ]
    rader += [
        Rad(
            tabell=del_.tabell,
            fid=del_.fid,
            tid=del_.ingar_i,
            typ=del_.lamningstyp,
            lamningsnummer="",
            ar_del=True,
        )
        for del_ in rapport.delposter
    ]
    return rader


def _geometrier(gpkg: Path, poster) -> dict[tuple[str, int], bytes]:
    """WKB for de lamningar leveranslistan pekar ut."""
    per_tabell: dict[str, list[int]] = {}
    for post in poster:
        per_tabell.setdefault(post.tabell, []).append(post.fid)

    ut: dict[tuple[str, int], bytes] = {}
    anslutning = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    try:
        for tabell, fidar in per_tabell.items():
            platser = ", ".join("?" for _ in fidar)
            for fid, blob in anslutning.execute(
                f'SELECT fid, geometri FROM "{tabell}" WHERE fid IN ({platser})',
                fidar,
            ):
                try:
                    ren = geometrimodul.wkb(blob)
                except ValueError:
                    ren = None
                if ren is not None:
                    ut[(tabell, fid)] = ren
    finally:
        anslutning.close()
    return ut


def skriv(gpkg: Path | str, mapp: Path | str | None = None) -> Resultat:
    """Skriver geometrizippen bredvid arbetsfilen.

    Hojer `SaknarUtgangslage` om arbetsfilen saknar avtryck -- da gaar det
    inte att veta vad som ar rort sedan uttaget, och en leverans utan det
    urvalet vore en gissning.
    """
    ogr, osr = _ogr()
    gpkg = Path(gpkg)
    mapp = Path(mapp) if mapp else gpkg.parent
    rapport = leverans(gpkg)          # hojer SaknarUtgangslage
    resultat = Resultat()

    rader = _rader(rapport)
    if not rader:
        resultat.anmarkningar.append(
            "Ingenting är ändrat sedan uttaget, så det finns inga geometrier"
            " att leverera."
        )
        return resultat

    hamtade = _geometrier(gpkg, rader)

    referens = osr.SpatialReference()
    referens.ImportFromEPSG(SWEREF99TM)

    drivrutin = ogr.GetDriverByName("ESRI Shapefile")
    arbetsmapp = mapp / "_fornreg"
    if arbetsmapp.exists():
        for gammal in arbetsmapp.iterdir():
            gammal.unlink()
    else:
        arbetsmapp.mkdir(parents=True)

    sedda: dict[str, set[str]] = {}
    skrivna: list[Path] = []
    try:
        for tabell, ogrtyp in (
            ("point", ogr.wkbPoint),
            ("linestring", ogr.wkbLineString),
            ("polygon", ogr.wkbPolygon),
        ):
            valda = [rad for rad in rader if rad.tabell == tabell]
            if not valda:
                continue

            sokvag = arbetsmapp / f"{tabell}.shp"
            kalla = drivrutin.CreateDataSource(str(sokvag))
            # ENCODING=UTF-8 gor tva saker: DBF:ens sprakbyte satts till 0
            # i stallet for 87 (ANSI), och en .cpg skrivs som sager UTF-8.
            #
            # Utan det skrevs bytena som UTF-8 medan filen pastod Latin-1,
            # sa varje lasare gav "FÃ¥ngstgrop". Rapporterat fran falt: "nar
            # man oppnar den exporterade zipfilen finns inte å ä ö".
            lager = kalla.CreateLayer(
                tabell, referens, ogrtyp, options=["ENCODING=UTF-8"]
            )
            for namn, _ in FALT:
                definition = ogr.FieldDefn(
                    namn, ogr.OFTInteger if namn == "TID" else ogr.OFTString
                )
                if namn != "TID":
                    definition.SetWidth(80)
                lager.CreateField(definition)

            antal = 0
            # Efter lamningens nummer, sa att systemets yta och dess punkter
            # hamnar bredvid varandra i uppladdningslistan.
            for post in sorted(
                valda, key=lambda r: (r.tid is None, r.tid or 0, r.fid)
            ):
                raa = hamtade.get((post.tabell, post.fid))
                geometri = (
                    ogr.CreateGeometryFromWkb(raa) if raa is not None else None
                )
                fel = _granska(ogr, geometri, post)
                if fel:
                    resultat.anmarkningar.append(fel)
                    continue

                geometri = ogr.CreateGeometryFromWkt(
                    _avrunda(geometri.ExportToWkt())
                )
                nyckel = geometri.ExportToWkt()
                if nyckel in sedda.setdefault(tabell, set()):
                    resultat.anmarkningar.append(
                        f"TID {post.tid} har samma geometri som en annan"
                        " lämning i leveransen. Fornreg tar inte emot"
                        " dubbletter."
                    )
                    continue
                sedda[tabell].add(nyckel)

                objekt = ogr.Feature(lager.GetLayerDefn())
                objekt.SetGeometry(geometri)
                objekt.SetField("TID", post.tid if post.tid is not None else 0)
                objekt.SetField("TYP", post.typ or "")
                objekt.SetField("LAMNINGSNR", post.lamningsnummer or "")
                lager.CreateFeature(objekt)
                antal += 1

            kalla = None      # stanger filen; utan det saknas .shx pa Windows
            if antal:
                resultat.antal[tabell] = antal
                skrivna.extend(
                    arbetsmapp / f"{tabell}{andelse}"
                    # .cpg ar inte ett av Fornregs fyra krav, men det ar den
                    # som sager vilken teckenkodning DBF:en har. Utan den ar
                    # åäö en gissning for den som laser filen.
                    for andelse in (".shp", ".shx", ".dbf", ".prj", ".cpg")
                )
            else:
                for skrap in arbetsmapp.glob(f"{tabell}.*"):
                    skrap.unlink()

        if not skrivna:
            resultat.anmarkningar.append("Ingen geometri gick att leverera.")
            return resultat

        # Samtliga geometrityper i samma zip, som handledningen tillater.
        mal = mapp / filnamn(gpkg)
        with zipfile.ZipFile(mal, "w", zipfile.ZIP_DEFLATED) as arkiv:
            for fil in skrivna:
                if fil.exists():
                    arkiv.write(fil, fil.name)
        resultat.fil = mal
        return resultat
    finally:
        for skrap in arbetsmapp.glob("*"):
            skrap.unlink()
        arbetsmapp.rmdir()


__all__ = ["Resultat", "SaknarGdal", "SaknarUtgangslage", "filnamn", "skriv"]
