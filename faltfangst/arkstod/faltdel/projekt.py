"""Kontroll av att en QGIS-projektfil gaar att flytta.

Verktyget ska kunna laggas in pa vilken dator som helst. En absolut sokvag i
projektfilen bryter det -- och den bryter det tyst: QGIS oppnar projektet,
lagren ser ut att finnas, och forst nar nagon klickar pa en lamning visar det
sig att formularet inte laddades eller att rullistan ar tom. Samma slags fel
som XYZ-URI:er som rapporteras giltiga och anda inte renderar.

QGIS relativiserar sjalv det den kanner till: datakallor och formularsokvag
gaar genom projektets sokvagsloesare. Det som star i widgetkonfigurationer och
i projektinstallningar skrivs daremot ordagrant. Det ar de senare som maste
kontrolleras, och det gaar inte att lita pa att en sparning stadar upp dem.

Kontrollen laser filen som text. Den behover inte QGIS igaang, och kan darfor
koras i testsviten.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

# En enhetsbeteckning foljd av separator (C:/ eller C:\), eller en UNC-sokvag.
# Enheten ar ett ensamt tecken -- utan den avgransningen fastnar slutet av
# varje URI-schema i uttrycket: `http://` lases som enheten "p".
_ENHET = re.compile(
    r"(?<![A-Za-z])(?:[A-Za-z]:[\\/]|\\\\[A-Za-z0-9_.-]+\\)[^\"'<>|*?\n]*"
)

# file:// pekar ocksa ut en plats i ett filsystem.
_FILURI = re.compile(r"file://[^\"'<>|\n]*")

# Sokvagar som inte hor till projektets egen mapp men anda ar giltiga att
# lamna kvar: QGIS skriver sina egna resursreferenser sa har.
_UNDANTAG = ("qgis://", "memory://", "base64:")


def las_projektfil(qgz: Path | str) -> str:
    """Projektets XML, oavsett om det ar en .qgz eller en .qgs."""
    qgz = Path(qgz)
    if qgz.suffix.lower() != ".qgz":
        return qgz.read_text(encoding="utf-8")
    with zipfile.ZipFile(qgz) as arkiv:
        namn = [
            post.filename
            for post in arkiv.infolist()
            if post.filename.lower().endswith(".qgs")
        ]
        if not namn:
            raise ValueError(f"{qgz.name} innehaller ingen .qgs")
        return arkiv.read(namn[0]).decode("utf-8")


def _absoluta_i_text(xml: str) -> list[str]:
    traffar: list[str] = []
    for monster in (_ENHET, _FILURI):
        for traff in monster.finditer(xml):
            text = traff.group(0).strip()
            if any(text.startswith(undantag) for undantag in _UNDANTAG):
                continue
            if text not in traffar:
                traffar.append(text)
    return traffar


def absoluta_sokvagar(qgz: Path | str) -> list[str]:
    """Alla absoluta filsokvagar i projektfilen, i den ordning de star.

    Tom lista betyder att projektet gaar att flytta.
    """
    return _absoluta_i_text(las_projektfil(qgz))


def relativisera(qgz: Path | str) -> list[str]:
    """Byter absoluta sokvagar in i projektets egen mapp mot relativa.

    QGIS relativiserar sjalv det den kanner till, men widgetkonfigurationer
    skrivs ordagrant -- och en value relation far tillbaka sin absoluta
    LayerSource sa fort lagret laddas om och projektet sparas. Fixen maste
    darfor gaa att koera om, inte utforas for hand en gaang.

    Returnerar de sokvagar som byttes. Sokvagar som pekar utanfor
    projektmappen lamnas i fred: de ar ett annat problem och ska synas.
    """
    qgz = Path(qgz)
    mapp = qgz.parent.resolve()
    prefix = str(mapp).replace("\\", "/") + "/"

    if qgz.suffix.lower() != ".qgz":
        text = qgz.read_text(encoding="utf-8")
        bytta = [rad for rad in absoluta_sokvagar(qgz) if rad.startswith(prefix)]
        if bytta:
            qgz.write_text(text.replace(prefix, "./"), encoding="utf-8")
        return bytta

    with zipfile.ZipFile(qgz) as arkiv:
        poster = {post.filename: arkiv.read(post.filename) for post in arkiv.infolist()}

    bytta: list[str] = []
    for namn, innehall in list(poster.items()):
        if not namn.lower().endswith(".qgs"):
            continue
        text = innehall.decode("utf-8")
        traffar = [rad for rad in _absoluta_i_text(text) if rad.startswith(prefix)]
        if not traffar:
            continue
        bytta.extend(traffar)
        poster[namn] = text.replace(prefix, "./").encode("utf-8")

    if bytta:
        with zipfile.ZipFile(qgz, "w", zipfile.ZIP_DEFLATED) as arkiv:
            for namn, innehall in poster.items():
                arkiv.writestr(namn, innehall)
    return bytta


# Geometrilagren i arbetsfilen. Det ar deras utbredning kartan ska visa.
_GEOMETRILAGER = ("point", "linestring", "polygon")

# Luft runt om, som andel av utbredningen. Utan den ligger de yttersta
# lamningarna precis i kartans kant.
_MARGINAL = 0.02


def utbredning(gpkg: Path | str) -> tuple[float, float, float, float] | None:
    """Lamningarnas utbredning i arbetsfilen: (xmin, ymin, xmax, ymax).

    Lases ur gpkg_contents, dar RAA:s uttag bar utbredningen per lager, och
    i andra hand ur lagrens rumsliga index. None om ingetdera finns.
    """
    import sqlite3

    anslutning = sqlite3.connect(f"file:{Path(gpkg)}?mode=ro", uri=True)
    try:
        rutor = []
        for lager in _GEOMETRILAGER:
            try:
                rad = anslutning.execute(
                    "SELECT min_x, min_y, max_x, max_y FROM gpkg_contents"
                    " WHERE table_name = ?",
                    (lager,),
                ).fetchone()
            except sqlite3.Error:
                rad = None
            if rad is None or any(varde is None for varde in rad):
                try:
                    rad = anslutning.execute(
                        "SELECT min(minx), min(miny), max(maxx), max(maxy)"
                        f' FROM "rtree_{lager}_geometri"'
                    ).fetchone()
                except sqlite3.Error:
                    rad = None
            if rad is not None and all(varde is not None for varde in rad):
                rutor.append(rad)
    finally:
        anslutning.close()
    if not rutor:
        return None
    return (
        min(r[0] for r in rutor),
        min(r[1] for r in rutor),
        max(r[2] for r in rutor),
        max(r[3] for r in rutor),
    )


def satt_utsnitt(
    qgz: Path | str, gpkg: Path | str
) -> tuple[float, float, float, float] | None:
    """Staller kartan sa att den visar uttagets lamningar nar projektet oppnas.

    Mallprojektet bar ett sparat utsnitt, och det foljde forr med till varje
    uttag: ett uttag for Skane oppnade inzoomat pa en ruta i Harjedalen, och
    kartan sag tom ut tills man sjalv zoomade till lagren. Nu skrivs
    utbredningen for det eller de lan uttaget galler, med lite luft omkring.

    Returnerar utsnittet, eller None om arbetsfilen inte sager var
    lamningarna ligger. Da lamnas projektet som det ar.
    """
    ruta = utbredning(gpkg)
    if ruta is None:
        return None
    xmin, ymin, xmax, ymax = ruta
    luft_x = (xmax - xmin) * _MARGINAL or 100.0
    luft_y = (ymax - ymin) * _MARGINAL or 100.0
    xmin, ymin, xmax, ymax = xmin - luft_x, ymin - luft_y, xmax + luft_x, ymax + luft_y

    qgz = Path(qgz)
    with zipfile.ZipFile(qgz) as arkiv:
        poster = {post.filename: arkiv.read(post.filename) for post in arkiv.infolist()}

    satt = False
    for namn, innehall in list(poster.items()):
        if not namn.lower().endswith(".qgs"):
            continue
        xml = innehall.decode("utf-8")

        # Kartfonstrets eget utsnitt: det QGIS staller in nar projektet oppnas.
        kanvas = re.search(
            r'(<mapcanvas[^>]*name="theMapCanvas"[^>]*>.*?<extent>)(.*?)(</extent>)',
            xml,
            re.S,
        )
        if kanvas:
            indrag = re.match(r"\s*", kanvas.group(2)).group(0) or "\n      "
            slut = re.search(r"\s*$", kanvas.group(2)).group(0) or "\n    "
            rader = indrag.join(
                f"<{tagg}>{varde!r}</{tagg}>"
                for tagg, varde in (
                    ("xmin", xmin), ("ymin", ymin), ("xmax", xmax), ("ymax", ymax)
                )
            )
            xml = (
                xml[: kanvas.start(2)] + indrag + rader + slut + xml[kanvas.end(2):]
            )
            satt = True

        # Och projektets forvalda vy -- "zooma till hela projektet".
        def _vy(traff: re.Match) -> str:
            tagg = traff.group(0)
            for attribut, varde in (
                ("xmin", xmin), ("ymin", ymin), ("xmax", xmax), ("ymax", ymax)
            ):
                tagg = re.sub(rf'\b{attribut}="[^"]*"', f'{attribut}="{varde!r}"', tagg)
            return tagg

        xml = re.sub(r"<DefaultViewExtent\b[^>]*>", _vy, xml, count=1)
        poster[namn] = xml.encode("utf-8")

    if not satt:
        return None
    with zipfile.ZipFile(qgz, "w", zipfile.ZIP_DEFLATED) as arkiv:
        for namn, innehall in poster.items():
            arkiv.writestr(namn, innehall)
    return (xmin, ymin, xmax, ymax)
