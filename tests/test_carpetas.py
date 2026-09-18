# -*- coding: utf-8 -*-
"""En qué carpeta env./dev. cae cada documento.

Se ejecuta a mano, sin pytest, con el intérprete de la app:

    docflow_env\\Scripts\\python.exe tests\\test_carpetas.py
"""
import shutil
import sys
import tempfile
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

# ── El sufijo de la carpeta, según cómo vuelva el documento ─────────────────
for estado, espera in (
    ("Rechazado", "REJ"),          # rehacerlo: carpeta propia, como se archiva a mano
    ("1R - WITH COMMENTS - REJECTED", "REJ"),
    ("Com. Mayores", "COM"),       # corregirlo
    ("Com. Menores", "com"),
    ("Comentado", "com"),
    ("Aprobado", "AP"),
    ("Informativo", "AP"),
    ("Certificado", "AP"),
    ("", "com"),                   # sin estado, lo prudente es «con comentarios»
):
    ok(D._suffix(estado) == espera,
       f"«{estado}» debería ir a rev<N> {espera}, no {D._suffix(estado)}")

# ── Revisiones en letra: «rev C» sin número por ninguna parte ───────────────
ok(D._partes_rev("rev2-50 AP") == (2, "50", "AP"), f"correlativo: {D._partes_rev('rev2-50 AP')}")
ok(D._partes_rev("rev51 COM") == (51, "", "COM"), "el número ES la revisión")
ok(D._partes_rev("revC com") == (None, "C", "com"), f"en letra: {D._partes_rev('revC com')}")
ok(D._partes_rev("rev B") == (None, "B", ""), "con espacio, igual")
ok(D._partes_rev("revisión pendiente") is None, "y lo que no es una carpeta de revisión, no lo es")
ok(D._env_rev_casa("revC", None, "C"), "la carpeta de envío «revC» es la de la revisión C")
ok(not D._env_rev_casa("revB", None, "C"), "pero «revB» no")
ok(not D._env_rev_casa("rev0", None, "C"), "y sin revisión que comparar, tampoco")

tmp = Path(tempfile.mkdtemp())
try:
    dev = tmp / "dev NDE"
    (dev / "revB com").mkdir(parents=True)             # la devolución de la rev B
    ruta, existe = D._rev_folder_for(dev, None, "C", "AP")
    ok(not existe and ruta.name == "revC AP",
       f"la carpeta sigue el estilo en letra del pedido: {ruta.name}")
    (dev / "revC AP").mkdir()
    otra, existe = D._rev_folder_for(dev, None, "C", "AP")
    ok(existe and otra == ruta, f"y si ya está, se reutiliza: {otra.name} ({existe})")

    # Carpeta dev vacía: manda el nombre de la carpeta de envío
    vacia = tmp / "dev PMI"
    vacia.mkdir()
    ruta, _ = D._rev_folder_for(vacia, None, "C", "com", envio=Path("revC"))
    ok(ruta.name == "revC com", f"lo enviado desde «env PMI\\revC» vuelve a «revC com»: {ruta.name}")
    ruta, _ = D._rev_folder_for(vacia, None, "C", "com")
    ok(ruta.name == "revC com", f"y sin carpeta de envío, igual: {ruta.name}")

    # Donde se lleva correlativo, la letra va detrás del guion, como siempre
    corr = tmp / "dev planos"
    (corr / "rev0-B com").mkdir(parents=True)
    ruta, _ = D._rev_folder_for(corr, None, "C", "com")
    ok(ruta.name == "rev1-C com", f"correlativo con revisión en letra: {ruta.name}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# Y que la carpeta se llame así de verdad, no solo el sufijo suelto
tmp = Path(tempfile.mkdtemp())
try:
    dev = tmp / "dev NDE"
    (dev / "rev1-49 com").mkdir(parents=True)          # la devolución anterior
    ruta, existe = D._rev_folder_for(dev, 50, "", D._suffix("Rechazado"))
    ok(not existe and ruta.name == "rev2-50 REJ",
       f"la nueva carpeta lleva REJ y el correlativo siguiente: {ruta.name}")
    # una carpeta REJ que ya exista se reutiliza en vez de duplicarse
    (dev / ruta.name).mkdir()
    otra, existe = D._rev_folder_for(dev, 50, "", "REJ")
    ok(existe and otra.name == ruta.name, f"se reutiliza la REJ existente: {otra.name} ({existe})")
    # y no se confunde con la de comentarios mayores
    com, _ = D._rev_folder_for(dev, 50, "", "COM")
    ok(com.name != ruta.name, f"REJ y COM son carpetas distintas: {com.name} vs {ruta.name}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("FALLOS:", fallos)
