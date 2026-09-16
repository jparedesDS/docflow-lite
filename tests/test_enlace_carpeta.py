# -*- coding: utf-8 -*-
"""El enlace «Guardado en» del correo de devolución.

    docflow_env\\Scripts\\python.exe tests\\test_enlace_carpeta.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.services.dev_folders import carpeta_vigente
from core.services.transmittal import folder_link_html

fallos = 0


def ok(cond, msg):
    global fallos
    if not cond:
        fallos += 1
        print("  FALLO:", msg)


RUTA = (r"M:\base de datos de pedidos\Año 2026\2026 Pedidos"
        r"\P-26-030-S00 - TR-SILLENO - VENTURIS 10\2-Tecnico\dev CÁLCULOS\rev2-C com")

html = folder_link_html(RUTA, depth=2)
href = html.split('href="', 1)[1].split('"', 1)[0]

# El enlace es la ruta a secas: con «file:» el clic se lo lleva el navegador
# —y Chrome bloquea las rutas locales que le llegan de fuera—, y sin esquema lo
# atiende el sistema, que abre el Explorador.
ok(not href.lower().startswith("file:"), f"nada de file:: {href[:40]}")
ok(href == RUTA, f"la ruta, tal cual: {href}")
ok("%20" not in href and "%C3" not in href,
   "ni escapes: en una ruta de Windows «%20» sería literal y la carpeta no existiría")
ok("Año" in href and "CÁLCULOS" in href, "los acentos, enteros")
ok(html.count("<a ") == 1 and html.rstrip().endswith("</a>"), "un solo enlace, bien cerrado")
ok(f'title="{RUTA}"' in html, "el tooltip lleva la ruta completa, para copiarla")
ok(">📂 dev CÁLCULOS\\rev2-C com<" in html, "la etiqueta enseña los dos últimos tramos")

# Lo que en HTML hay que escapar, escapado (una carpeta puede llamarse así)
raro = folder_link_html(r"M:\pedidos\rev1 <pendiente> & dudas", depth=1)
ok("&lt;pendiente&gt;" in raro and "&amp;" in raro, f"HTML escapado: {raro[:130]}")

# Una ruta relativa no genera enlace: mejor texto suelto que un enlace roto
suelto = folder_link_html("dev CÁLCULOS")
ok("<a " not in suelto, f"ruta relativa sin enlace: {suelto}")

# ── La carpeta apuntada puede haberse renombrado a mano ─────────────────────
tmp = Path(tempfile.mkdtemp())
try:
    dev = tmp / "dev NDE"
    (dev / "rev2-50 REJ").mkdir(parents=True)     # se renombró desde «rev2-50 COM»
    (dev / "rev1-2 AP").mkdir()
    ok(carpeta_vigente(dev / "rev2-50 COM") == str(dev / "rev2-50 REJ"),
       f"encuentra la carpeta renombrada: {carpeta_vigente(dev / 'rev2-50 COM')}")
    ok(carpeta_vigente(dev / "rev1-2 AP") == str(dev / "rev1-2 AP"),
       "la que sigue ahí se devuelve tal cual")
    ok(carpeta_vigente(dev / "rev9-99 COM") == "", "una que no existe no enlaza a nada")
    ok(carpeta_vigente("") == "", "y sin ruta, tampoco")
    # No se confunde con otra revisión que casualmente tenga el mismo sufijo
    ok(carpeta_vigente(dev / "rev2-49 REJ") == "",
       "el número de revisión tiene que cuadrar, no vale cualquier REJ")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("FALLOS:", fallos)
