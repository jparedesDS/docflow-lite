# -*- coding: utf-8 -*-
"""Lo que la plantilla ya trae escrito se queda; solo se propone lo que cambia.

    docflow_env\\Scripts\\python.exe tests\\test_sugerencias.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.services import portadas_lote as P

fallos = 0


def ok(cond, msg):
    global fallos
    if not cond:
        fallos += 1
        print("  FALLO:", msg)


# Los documentos del pedido, como los da el ERP
DOCS = [
    {"Nº Pedido": "P-26/062-S00", "Cliente": "MOEVE - ONUVA", "Nº PO": "7011419725",
     "Nº Doc. Cliente": "V-2401HG04A-2206-300-DL-001", "Nº Doc. EIPSA": "26-062-DL-0001",
     "Título": "DOCUMENTS LIST", "Tipo Doc.": "VDDL", "Nº Revisión": 0.0},
    {"Nº Pedido": "P-26/062-S00", "Cliente": "MOEVE - ONUVA", "Nº PO": "7011419725",
     "Nº Doc. Cliente": "V-2401HG04A-2206-300-OHFE-0014-CAL-001",
     "Nº Doc. EIPSA": "26-062-CAL-0002", "Título": "EQUIPMENT CALCULATION - OHFE 0014",
     "Tipo Doc.": "Cálculos", "Nº Revisión": 1.0},
]

# La plantilla del cliente, rellena con uno de sus documentos (el DL-001)
HUECOS = [
    {"clave": "CLIENT", "tipo": "etiqueta", "ejemplo": "MOEVE - ONUBA SUSTAINABLE FUEL (OSF)"},
    {"clave": "PROJECT", "tipo": "etiqueta", "ejemplo": "ONUBA"},
    {"clave": "UNIT", "tipo": "etiqueta", "ejemplo": "OG"},
    {"clave": "PURCHASE ORDER N°", "tipo": "etiqueta", "ejemplo": "7011419725"},
    {"clave": "WOOD DWG. N°", "tipo": "etiqueta", "ejemplo": "V-2401HG04A-2206-300-DL-001"},
    {"clave": "VENDOR DOC. Nº", "tipo": "etiqueta", "ejemplo": "26-062-DL-0001"},
    {"clave": "MAT. REQ. Nº", "tipo": "etiqueta", "ejemplo": "RM-2401HG04A-2206-300"},
    {"clave": "VENDOR CAD FILE Nº", "tipo": "etiqueta",
     "ejemplo": "V-2401HG04A-2206-300-DL-001-R0.PDF"},
    {"clave": "CAD 2 CIFRAS", "tipo": "etiqueta",
     "ejemplo": "V-2401HG04A-2206-300-DL-001-R00.pdf"},
    {"clave": "ITEM N°", "tipo": "etiqueta", "ejemplo": "ALL TAGS"},
    {"clave": "FIRMA", "tipo": "etiqueta", "ejemplo": ""},
]

s = P.sugerir(HUECOS, DOCS)

# Lo que coincide con un dato del pedido: se propone el campo
ok(s["WOOD DWG. N°"] == "{Nº Doc. Cliente}", f"nº del cliente: {s['WOOD DWG. N°']!r}")
ok(s["VENDOR DOC. Nº"] == "{Nº Doc. EIPSA}", f"nº de EIPSA: {s['VENDOR DOC. Nº']!r}")
ok(s["PURCHASE ORDER N°"] == "{Nº PO}", f"pedido del cliente: {s['PURCHASE ORDER N°']!r}")

# Lo que NO coincide: se queda exactamente como estaba en la plantilla
ok(s["CLIENT"] == "MOEVE - ONUBA SUSTAINABLE FUEL (OSF)", f"cliente: {s['CLIENT']!r}")
ok(s["PROJECT"] == "ONUBA", f"proyecto: {s['PROJECT']!r}")
ok(s["MAT. REQ. Nº"] == "RM-2401HG04A-2206-300", f"nº de RM: {s['MAT. REQ. Nº']!r}")
ok(s["FIRMA"] == "", "un hueco vacío se queda vacío")

# El nombre del PDF lleva el número y la revisión pegados: se reconoce entero
ok(s["VENDOR CAD FILE Nº"] == "{Nº Doc. Cliente}-R{Nº Revisión}.PDF",
   f"nombre del fichero: {s['VENDOR CAD FILE Nº']!r}")
ok(s["CAD 2 CIFRAS"] == "{Fichero}",
   f"con dos cifras es exactamente el campo «Fichero»: {s['CAD 2 CIFRAS']!r}")
ok(P.aplicar(s["CAD 2 CIFRAS"], P.valores_documento(DOCS[1])).endswith("-R01.PDF"),
   "y da el nombre con dos cifras")

# «ALL TAGS» es lo que se pone cuando el documento no es de un tag concreto
ok(s["ITEM N°"] == "{Tag|ALL TAGS}", f"item/tag: {s['ITEM N°']!r}")

# «OG» son dos letras: no se propone campo por una coincidencia tan corta
ok(s["UNIT"] == "OG", f"unidad: {s['UNIT']!r}")

# Y lo propuesto, aplicado a cada documento, da lo que tiene que dar
v = P.valores_documento(DOCS[1])
ok(P.aplicar(s["WOOD DWG. N°"], v) == "V-2401HG04A-2206-300-OHFE-0014-CAL-001",
   "el hueco propuesto cambia con cada documento")
ok(P.aplicar(s["CLIENT"], v) == "MOEVE - ONUBA SUSTAINABLE FUEL (OSF)",
   "el texto fijo no cambia")
ok(P.aplicar(s["VENDOR CAD FILE Nº"], v) == "V-2401HG04A-2206-300-OHFE-0014-CAL-001-R1.PDF",
   f"el nombre del PDF sale con su revisión: {P.aplicar(s['VENDOR CAD FILE Nº'], v)}")

# Sin documentos no se propone nada, pero tampoco se pierde lo de la plantilla
sin = P.sugerir(HUECOS, [])
ok(sin["WOOD DWG. N°"] == "V-2401HG04A-2206-300-DL-001",
   f"sin datos, lo de la plantilla se respeta: {sin['WOOD DWG. N°']!r}")

print("FALLOS:", fallos)
