# -*- coding: utf-8 -*-
"""Volver a archivar una devolución que se descargó sin repartir.

    docflow_env\\Scripts\\python.exe tests\\test_rearchivo.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.services import dev_folders
from core.services import portal_downloads as P

fallos = 0


def ok(cond, msg):
    global fallos
    if not cond:
        fallos += 1
        print("  FALLO:", msg)


CODE = "1037010710-T-0066"
DEV = Path(r"M:\pedidos\P-23-037\2-Tecnico\dev NDE\revC AP")

tmp = Path(tempfile.mkdtemp())
registro, archivar_real = P.PORTAL_DOWNLOADS_FILE, dev_folders.archive_return
try:
    P.PORTAL_DOWNLOADS_FILE = tmp / "portal_downloads.json"
    P._mark_done(CODE, {"pedido": "P-23/037", "zip": r"M:\pedidos\…\1037010710-T-0066.zip",
                        "folder": r"M:\pedidos\…\001 (18-09-2026)"})
    ok(not P.downloaded_info(CODE).get("dev_folders"),
       "la descarga que no colocó nada no apunta ninguna carpeta")

    # Al repartirlo, las carpetas quedan apuntadas: son las que el correo enlaza
    dev_folders.archive_return = lambda *a, **k: {
        "archived": [("3998_18-1037010710-00019.pdf", DEV / "3998_18-1037010710-00019.pdf")],
        "skipped": [], "created": [DEV], "plan": []}
    res = P._archivar(CODE, Path("paquete.zip"), [], "P-23/037")
    ok(res["dev_folders"] == [str(DEV)], f"carpeta del reparto: {res['dev_folders']}")
    ok(P.downloaded_info(CODE).get("dev_folders") == [str(DEV)],
       "y quedan en el registro, que es de donde las saca el correo")
    ok(P.download_status("eGesDoc <egesdoc@grupotr.es>",
                         "eGesdoc - New transmittal registered (1037010710-T-0066) - PO(1037010710)"
                         ).get("dev_folders") == [str(DEV)],
       "la lista de devoluciones también las ve")

    # Si el reparto falla, no se lleva por delante la descarga ni el registro
    def revienta(*a, **k):
        raise OSError("M: no está conectada")

    dev_folders.archive_return = revienta
    res = P._archivar("OTRO-0001", Path("paquete.zip"), [], "P-23/037")
    ok(res["dev_folders"] == [] and res["archive"]["skipped"],
       f"el fallo se cuenta como «sin colocar», no como excepción: {res}")
    ok(P.downloaded_info("OTRO-0001") is None, "y no se inventa un registro")
finally:
    dev_folders.archive_return = archivar_real
    P.PORTAL_DOWNLOADS_FILE = registro
    shutil.rmtree(tmp, ignore_errors=True)

# ── Lo que cada portal añade a los documentos del correo ────────────────────
docs = [{"Doc. EIPSA": "23-037-PRC-0006", "Rev.": "C"}]

mismos, ficheros = P._docs_y_ficheros({"portal": "prodoc", "code": "X", "po": "1"},
                                      docs, "asunto", b"")
ok(mismos is docs and ficheros == {},
   "un portal cuyos ficheros ya llevan el código no necesita mapa")

# Y si el portal no contesta, se archiva lo que se pueda en vez de fallar
guardado = P.egesdoc.transmittal_file_map
try:
    def no_contesta(*a, **k):
        raise TimeoutError("eGesDoc no responde")

    P.egesdoc.transmittal_file_map = no_contesta
    mismos, ficheros = P._docs_y_ficheros({"portal": "egesdoc", "code": "X", "po": "1"},
                                          docs, "asunto", b"")
    ok(mismos is docs and ficheros == {}, "sin mapa de ficheros, pero sin reventar")
finally:
    P.egesdoc.transmittal_file_map = guardado

print("FALLOS:", fallos)
