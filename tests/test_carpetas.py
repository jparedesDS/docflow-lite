# -*- coding: utf-8 -*-
"""En qué carpeta env./dev. cae cada documento.

Se ejecuta a mano, sin pytest, con el intérprete de la app:

    docflow_env\\Scripts\\python.exe tests\\test_carpetas.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.services import dev_folders as D

fallos = 0


def ok(cond, msg):
    global fallos
    if not cond:
        fallos += 1
        print("  FALLO:", msg)


def carpetas(*nombres):
    return [{"kind": "env", "name": n, "dotted": True, "path": Path("X") / n} for n in nombres]


# Las de un pedido real de WOOD (P-26/062)
ENV = carpetas("Certificados Prueba y Materiales", "Cálculos", "FINAL QUALITY DOSSIER",
               "ITP", "MANUAL", "Manufacturing Program", "Planos", "VDDL")


def elegida(tipo, titulo):
    f = D._by_type_and_title(ENV, tipo, titulo)
    return f["name"] if f else None


# El tipo manda sobre una palabra del título que coincide por casualidad:
# «QUALITY CONTROL PLAN» comparte QUALITY con la carpeta del dossier.
ok(elegida("PPI", "QUALITY CONTROL PLAN") == "ITP",
   f"el ITP va a su carpeta: {elegida('PPI', 'QUALITY CONTROL PLAN')}")
ok(elegida("Dossier", "FINAL QUALITY DOSSIER") == "FINAL QUALITY DOSSIER",
   f"el dossier, a la suya: {elegida('Dossier', 'FINAL QUALITY DOSSIER')}")

# El tipo del ERP no está escrito igual que la clave del catálogo
ok(elegida("Certificados", "MATERIAL AND TEST CERTIFICATES") == "Certificados Prueba y Materiales",
   f"«Certificados» (plural) encuentra su carpeta: {elegida('Certificados', 'MATERIAL AND TEST CERTIFICATES')}")
ok(D._palabras_del_tipo("certificados") == D.TYPE_KEYWORDS["Certificado"],
   "el tipo se busca sin acentos, sin mayúsculas y en singular/plural")
ok(D._palabras_del_tipo("") == [] and D._palabras_del_tipo("Inventado") == [],
   "un tipo desconocido no trae palabras")

# El tipo que ES el nombre de la carpeta, aunque el título no se parezca
ok(elegida("VDDL", "DOCUMENTS LIST") == "VDDL", f"VDDL: {elegida('VDDL', 'DOCUMENTS LIST')}")
ok(elegida("VDDL", "Lista de documentos") == "VDDL", "VDDL con el título en español")

# Los de siempre, que no se rompen
ok(elegida("Planos", "OVERALL DRAWING") == "Planos", f"planos: {elegida('Planos', 'OVERALL DRAWING')}")
ok(elegida("Manual", "INSTALLATION AND MAINTENANCE") == "MANUAL", "manual")
ok(elegida("Programa", "MANUFACTURING PLANNING") == "Manufacturing Program", "programa")

# Y cuando no hay carpeta, no se inventa ninguna
ok(elegida("Repuestos", "LIST OF RECOMMENDED SPARE PARTS") is None,
   f"sin carpeta de repuestos no se inventa: {elegida('Repuestos', 'LIST OF RECOMMENDED SPARE PARTS')}")
ok(elegida("Procedimientos", "PMI PROCEDURE") is None, "sin carpeta de procedimientos tampoco")

print("FALLOS:", fallos)
