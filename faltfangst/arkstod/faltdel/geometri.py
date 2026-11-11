"""De geometrifunktioner GeoPackagens egna triggrar behover.

En GPKG bar rtree-triggrar som anropar ST_IsEmpty och ST_MinX/MaxX/MinY/MaxY.
Funktionerna kommer fran SpatiaLite, som Pythons inbyggda sqlite3 inte har.
Tva av triggrarna -- update4 och update5 -- saknar dessutom kolumnbegransning,
sa deras WHEN-sats utvarderas vid *varje* UPDATE pa tabellen. Utan
funktionerna gaar det darfor inte att skriva en enda kolumn.

Det ar samma vagg som fick den forsta migreringen att kopiera data i stallet
for att anvanda vyer: vyer med triggrar gick inte att skriva i utan
SpatiaLite. Men vaggen ar lagre an den ser ut: GeoPackagens binarformat bar sitt eget omslutande
rektangel i huvudet, och nar det saknas -- GDAL utelamnar det for punkter --
gaar koordinaterna att lasa direkt ur WKB:n.

Funktionerna registreras pa anslutningen och ror ingenting i filen.
"""

from __future__ import annotations

import sqlite3
import struct

# GeoPackage-huvudet: 'GP', version, flaggor, srs_id, darefter omslutande
# rektangel enligt flaggornas indikator.
_MAGI = b"GP"
_ENVELOPE_LANGD = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}


def _huvud(blob: bytes) -> tuple[int, bool, int]:
    """Returnerar (huvudlangd, ar_tom, envelope_indikator)."""
    if len(blob) < 8 or blob[:2] != _MAGI:
        raise ValueError("inte en GeoPackage-geometri")
    flaggor = blob[3]
    indikator = (flaggor >> 1) & 0x07
    ar_tom = bool((flaggor >> 4) & 0x01)
    if indikator not in _ENVELOPE_LANGD:
        raise ValueError(f"okänd envelope-indikator {indikator}")
    return 8 + _ENVELOPE_LANGD[indikator], ar_tom, indikator


def _envelope_ur_huvud(blob: bytes, indikator: int) -> tuple[float, ...] | None:
    if indikator == 0:
        return None
    little = bool(blob[3] & 0x01)
    ordning = "<" if little else ">"
    minx, maxx, miny, maxy = struct.unpack_from(f"{ordning}4d", blob, 8)
    return minx, maxx, miny, maxy


def _koordinater(wkb: bytes) -> list[tuple[float, float]]:
    """Alla x/y i en WKB, oavsett geometrityp. Z och M hoppas over."""
    punkter: list[tuple[float, float]] = []

    def las(position: int) -> int:
        little = wkb[position] == 1
        ordning = "<" if little else ">"
        (typ,) = struct.unpack_from(f"{ordning}I", wkb, position + 1)
        position += 5

        # Dimensionen ligger i tusentalen: 1000 = Z, 2000 = M, 3000 = ZM.
        # ISO-varianten anvander dem; EWKB satter i stallet hoga bitar.
        extra = 0
        if typ & 0x80000000:
            extra += 1
        if typ & 0x40000000:
            extra += 1
        bastyp = typ & 0xFFFF
        if bastyp > 3000:
            bastyp, extra = bastyp - 3000, extra + 2
        elif bastyp > 2000:
            bastyp, extra = bastyp - 2000, extra + 1
        elif bastyp > 1000:
            bastyp, extra = bastyp - 1000, extra + 1
        stegets_langd = 8 * (2 + extra)

        def las_punkter(position: int, antal: int) -> int:
            for _ in range(antal):
                x, y = struct.unpack_from(f"{ordning}2d", wkb, position)
                punkter.append((x, y))
                position += stegets_langd
            return position

        if bastyp == 1:  # Point
            return las_punkter(position, 1)
        if bastyp == 2:  # LineString
            (antal,) = struct.unpack_from(f"{ordning}I", wkb, position)
            return las_punkter(position + 4, antal)
        if bastyp == 3:  # Polygon
            (ringar,) = struct.unpack_from(f"{ordning}I", wkb, position)
            position += 4
            for _ in range(ringar):
                (antal,) = struct.unpack_from(f"{ordning}I", wkb, position)
                position = las_punkter(position + 4, antal)
            return position
        if bastyp in (4, 5, 6, 7):  # Multi* och GeometryCollection
            (delar,) = struct.unpack_from(f"{ordning}I", wkb, position)
            position += 4
            for _ in range(delar):
                position = las(position)
            return position
        raise ValueError(f"okänd WKB-typ {bastyp}")

    las(0)
    return punkter


def wkb(blob: bytes | None) -> bytes | None:
    """Den rena WKB:n ur en GeoPackage-geometri, utan dess huvud.

    GeoPackagen lagrar WKB med ett eget huvud framfor: magi, flaggor,
    srs-id och ibland en omslutande rektangel. Allt utanfor det ar vanlig
    WKB, som vilket geometribibliotek som helst laser.
    """
    if blob is None:
        return None
    huvudlangd, ar_tom, _ = _huvud(blob)
    if ar_tom:
        return None
    return blob[huvudlangd:]


def omslutande(blob: bytes | None) -> tuple[float, float, float, float] | None:
    """Rektangeln (minx, maxx, miny, maxy), eller None for tom geometri."""
    if blob is None:
        return None
    huvudlangd, ar_tom, indikator = _huvud(blob)
    if ar_tom:
        return None
    ur_huvudet = _envelope_ur_huvud(blob, indikator)
    if ur_huvudet is not None:
        return ur_huvudet  # type: ignore[return-value]

    punkter = _koordinater(blob[huvudlangd:])
    if not punkter:
        return None
    x = [punkt[0] for punkt in punkter]
    y = [punkt[1] for punkt in punkter]
    return min(x), max(x), min(y), max(y)


def ar_tom(blob: bytes | None) -> int:
    """ST_IsEmpty. Triggrarnas WHEN-satser bygger pa den."""
    try:
        return 1 if omslutande(blob) is None else 0
    except (ValueError, struct.error):
        # Hellre "tom" an ett undantag mitt i en trigger: da stannar
        # skrivningen, och felet syns som ett trasigt rtree i stallet.
        return 1


def registrera(anslutning: sqlite3.Connection) -> None:
    """Ger anslutningen de funktioner GeoPackagens triggrar anropar."""

    def hamta(index: int):
        def funktion(blob):
            rektangel = omslutande(blob)
            return None if rektangel is None else rektangel[index]

        return funktion

    anslutning.create_function("ST_IsEmpty", 1, ar_tom)
    anslutning.create_function("ST_MinX", 1, hamta(0))
    anslutning.create_function("ST_MaxX", 1, hamta(1))
    anslutning.create_function("ST_MinY", 1, hamta(2))
    anslutning.create_function("ST_MaxY", 1, hamta(3))
