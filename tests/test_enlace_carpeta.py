# -*- coding: utf-8 -*-
"""El enlace «Guardado en» del correo de devolución.

    docflow_env\\Scripts\\python.exe tests\\test_enlace_carpeta.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.services.transmittal import folder_link_html, uri_carpeta

fallos = 0


def ok(cond, msg):
    global fallos
    if not cond:
        fallos += 1
        print("  FALLO:", msg)


RUTA = (r"M:\base de datos de pedidos\Año 2026\2026 Pedidos"
        r"\P-26-030-S00 - TR-SILLENO - VENTURIS 10\2-Tecnico\dev CÁLCULOS\rev2-C com")

uri = uri_carpeta(RUTA)

# Lo importante: los acentos van tal cual. Windows descodifica los %XX de un
# enlace file: con la página de códigos ANSI, así que «A%C3%B1o» le llega como
# «AÃ±o» y no encuentra la carpeta.
ok("Año" in uri, f"la eñe va sin escapar: {uri}")
ok("CÁLCULOS" in uri, "y la tilde también")
ok("%C3" not in uri and "%C1" not in uri, f"nada de acentos escapados: {uri}")

# Lo que sí rompería la URL, escapado
ok("%20" in uri and " " not in uri, "los espacios sí se escapan")
ok(uri.startswith("file:///M:/"), f"empieza como toca: {uri[:24]}")
ok("\\" not in uri, "barras hacia delante en la URL")

# Una ruta de red mantiene sus dos barras iniciales
red = uri_carpeta(r"\\SRV\recurso\Año 2026")
ok(red == "file://SRV/recurso/Año%202026", f"ruta de red: {red}")

# Y lo que se ve en el correo
html = folder_link_html(RUTA, depth=2)
ok('title="M:\\base de datos' in html, f"el tooltip lleva la ruta de siempre: {html[:120]}")
ok(">📂 dev CÁLCULOS\\rev2-C com<" in html, "la etiqueta enseña los dos últimos tramos")
ok(html.count("<a ") == 1 and html.rstrip().endswith("</a>"), "un solo enlace, bien cerrado")

# Una ruta relativa no genera enlace: mejor texto suelto que un enlace roto
suelto = folder_link_html("dev CÁLCULOS")
ok("<a " not in suelto, f"ruta relativa sin enlace: {suelto}")

# Los caracteres que rompen una URL, escapados (una carpeta puede llamarse así)
raro = uri_carpeta(r"M:\pedidos\rev#1 ¿dudas? 50%")
ok("%23" in raro and "%3F" in raro and "%25" in raro, f"almohadilla, interrogante y %: {raro}")
ok("¿" in raro, "pero la interrogación de apertura no molesta y se queda")

print("FALLOS:", fallos)
