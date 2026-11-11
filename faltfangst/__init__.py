"""Faltfangst — QGIS-plugin for arkeologisk inventering.

Pluginen bar med sig paketet arkstod, lamningstypsdatabasen och mallfilerna. Den ska
gaa att installera som en zip och fungera direkt, utan pip och utan
kommandorad: inventeraren ska klicka en knapp och kunna borja arbeta.
"""

import os
import sys

# Den medfoljande arkstod-kopian maste ligga pa sokvagen innan nagot av
# paketets egna absoluta importer korer.
_HAR = os.path.dirname(__file__)
if _HAR not in sys.path:
    sys.path.insert(0, _HAR)


def classFactory(iface):  # noqa: N802  (QGIS bestammer namnet)
    from .plugin import Lamningsdatabas

    return Lamningsdatabas(iface)
