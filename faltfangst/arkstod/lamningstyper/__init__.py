"""Lager 1: Lamningstypslistan som relationsmodell.

Lagret ar avsiktligt spraakmodellfritt. Listans text aterges ordagrant och
kopplingen mellan uppslagsord och dess bedomningsregel bryts aldrig upp.

Paketet importerar med flit ingenting sjalvt. Parsningen kraver PyMuPDF, som
finns pa den dator dar listan byggs men inte i QGIS -- och faltdelen laser
bara den fardiga databasen. Importera undermodulen du behover.
"""
