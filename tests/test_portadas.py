# -*- coding: utf-8 -*-
"""Portadas: los campos del ERP, los patrones y las plantillas de Excel.

Se ejecuta a mano, sin pytest, con el intérprete de la app:

    docflow_env\\Scripts\\python.exe tests\\test_portadas.py
"""
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.services import plantilla_xlsx, portadas_lote as P

fallos = 0


def ok(cond, msg):
    global fallos
    if not cond:
        fallos += 1
        print("  FALLO:", msg)


# ── Campos de un documento ───────────────────────────────────────────────────
doc = {"Nº Pedido": "P-26/048-S00", "Cliente": "MOEVE", "Material": "Caudal",
       "Nº PO": "7011408252", "Nº Doc. Cliente": "V-3005785-2206-300-TKFE2017N-CAL-001",
       "Nº Doc. EIPSA": "26-048-CAL-0001", "Título": "Cálculos - TKFE 2017N",
       "Tipo Doc.": "Cálculos", "Nº Revisión": "1.0"}
v = P.valores_documento(doc)
ok(v["Tag"] == "TKFE 2017N", f"tag: {v['Tag']}")
ok(v["Nº Revisión"] == "1", f"revisión en limpio: {v['Nº Revisión']}")
ok(v["Rev. 2 cifras"] == "01", f"revisión a dos cifras: {v['Rev. 2 cifras']}")
ok(v["Fichero"] == "V-3005785-2206-300-TKFE2017N-CAL-001-R01.PDF", f"fichero: {v['Fichero']}")
ok(P.valores_documento({**doc, "Nº Revisión": "A"})["Nº Revisión"] == "A", "revisión en letra")
ok(P.valores_documento({**doc, "Nº Revisión": ""})["Nº Revisión"] == "", "sin revisión")

# El ERP manda la revisión como número: la 0 llega como 0.0, que es «falso»
cero = P.valores_documento({**doc, "Nº Revisión": 0.0})
ok(cero["Nº Revisión"] == "0", f"la revisión 0 no puede perderse: {cero['Nº Revisión']!r}")
ok(cero["Rev. 2 cifras"] == "00", f"la 0 a dos cifras: {cero['Rev. 2 cifras']!r}")
ok(cero["Fichero"].endswith("-R00.PDF"), f"fichero de la rev 0: {cero['Fichero']}")

# ── El TAG del documento ─────────────────────────────────────────────────────
# Los tags del pedido se leen del ERP; aquí se ponen a mano para no depender de
# él. El ERP los escribe con espacio y los clientes de mil maneras.
P._TAGS_CACHE["P-26/062-S00"] = sorted(
    [(tag, P._sin_separadores(tag)) for tag in ("OHFE 0014", "OUFO 0018", "TKFE 2017N")],
    key=lambda x: len(x[1]), reverse=True)


def tag_de(numero, titulo="", tipo="Cálculos"):
    return P.valores_documento({"Nº Pedido": "P-26/062-S00", "Nº Doc. Cliente": numero,
                                "Título": titulo, "Tipo Doc.": tipo})["Tag"]


ok(tag_de("V-2401HG04A-2206-300-OHFE-0014-CAL-001") == "OHFE 0014",
   f"tag con guion en el número: {tag_de('V-2401HG04A-2206-300-OHFE-0014-CAL-001')!r}")
ok(tag_de("V-3005785-2206-300-TKFE2017N-CAL-001") == "TKFE 2017N",
   "tag escrito del tirón por el cliente")
ok(tag_de("", "EQUIPMENT CALCULATION / DATA SHEET OHFE-0014") == "OHFE 0014",
   "tag que solo aparece en el título")
ok(tag_de("V-2401HG04A-2206-300-ITP-001", "QUALITY CONTROL PLAN", "PPI") == "",
   "un ITP no es de ningún tag")
ok(tag_de("V-2401HG04A-2206-300-DOS-001", "FINAL QUALITY DOSSIER", "Dossier") == "",
   "ni el dossier")

# Y la alternativa: el tag si lo hay, «ALL TAGS» si no
calc = P.valores_documento({"Nº Pedido": "P-26/062-S00", "Título": "",
                            "Nº Doc. Cliente": "V-2401HG04A-2206-300-OUFO-0018-DWG-001"})
itp = P.valores_documento({"Nº Pedido": "P-26/062-S00", "Título": "QUALITY CONTROL PLAN",
                           "Nº Doc. Cliente": "V-2401HG04A-2206-300-ITP-001"})
ok(P.aplicar("{Tag|ALL TAGS}", calc) == "OUFO 0018", "el plano lleva su tag")
ok(P.aplicar("{Tag|ALL TAGS}", itp) == "ALL TAGS", "el ITP, todos")
ok(P.aplicar("{Tag|ALL TAGS} - {Nº Doc. Cliente}", itp).startswith("ALL TAGS - "),
   "la alternativa convive con el resto del patrón")
ok(P.aplicar("{Inventado|POR DEFECTO}", itp) == "POR DEFECTO",
   "un campo que no existe también admite alternativa")

# ── Patrones ─────────────────────────────────────────────────────────────────
ok(P.aplicar("{Tag} ALL ITEMS", v) == "TKFE 2017N ALL ITEMS", "patrón con texto detrás")
ok(P.aplicar("3000005785-2206-3000", v) == "3000005785-2206-3000", "texto fijo intacto")
ok(P.aplicar("{nº doc. cliente}", v) == v["Nº Doc. Cliente"], "el campo no distingue mayúsculas")
ok(P.aplicar("{Inventado}", v) == "", "un campo que no existe se queda vacío")
ok(P.aplicar("", v) == "", "patrón vacío")
ok(P.aplicar("{Nº Doc. Cliente}-R{Nº Revisión}.PDF", cero).endswith("-R0.PDF"),
   "nombre de fichero al estilo WOOD (una cifra)")

# ── Plantilla de Excel: marcadores ───────────────────────────────────────────
tmp = Path(tempfile.mkdtemp())
try:
    plantilla = tmp / "portada.xlsx"
    shared = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="3">'
              '<si><t>N° DOCUMENTO:</t></si>'
              '<si><t>{{DOC CLIENTE}}</t></si>'
              '<si><r><t>{{TAG</t></r><r><t>}} ALL ITEMS</t></r></si>'
              '</sst>')
    hoja = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Rev. {{REV}}</t></is></c>'
            '</row></sheetData></worksheet>')
    with zipfile.ZipFile(plantilla, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/sharedStrings.xml", shared)
        z.writestr("xl/worksheets/sheet1.xml", hoja)
        z.writestr("xl/media/logo.png", b"\x89PNG-falso")

    marcas = plantilla_xlsx.marcadores(plantilla)
    ok({m.upper() for m in marcas} == {"DOC CLIENTE", "TAG", "REV"},
       f"marcadores encontrados: {marcas}")

    destino = plantilla_xlsx.rellenar(plantilla, tmp / "relleno.xlsx", marcas={
        "DOC CLIENTE": "V-3005785-2206-300-TKFE2017N-CAL-001",
        "TAG": "TKFE 2017N", "REV": "01"})
    with zipfile.ZipFile(destino) as z:
        texto = z.read("xl/sharedStrings.xml").decode("utf-8")
        celda = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        ok(z.read("xl/media/logo.png") == b"\x89PNG-falso", "el logo sigue ahí, byte a byte")
        ok(len(z.namelist()) == 4, f"no se pierde ninguna parte: {z.namelist()}")
    ok("V-3005785-2206-300-TKFE2017N-CAL-001" in texto, "el número del documento se escribió")
    ok("TKFE 2017N ALL ITEMS" in texto, "marcador partido en dos trozos")
    ok("{{" not in texto and "{{" not in celda, "no queda ningún marcador sin sustituir")
    ok("Rev. 01" in celda, f"texto dentro de la celda: {celda[-120:]}")
    ok("N° DOCUMENTO:" in texto, "las etiquetas de la plantilla no se tocan")

    otro = plantilla_xlsx.rellenar(plantilla, tmp / "parcial.xlsx", marcas={"REV": "02"})
    with zipfile.ZipFile(otro) as z:
        ok("{{DOC CLIENTE}}" in z.read("xl/sharedStrings.xml").decode("utf-8"),
           "lo que no se mapea se queda visible")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ── Plantilla de Excel: etiquetas «ETIQUETA : valor» ─────────────────────────
tmp = Path(tempfile.mkdtemp())
try:
    plantilla = tmp / "tabla.xlsx"
    shared = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="4">'
              '<si><t>CLIENT                    :</t></si><si><t>MOEVE - ONUBA</t></si>'
              '<si><t>VENDOR DOC. Nº      :</t></si><si><t>26-062-DL-0001</t></si>'
              '</sst>')
    hoja = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData>'
            '<row r="2"><c r="A2" t="s" s="5"><v>0</v></c><c r="B2" t="s" s="7"><v>1</v></c></row>'
            '<row r="3"><c r="A3" t="s" s="5"><v>2</v></c><c r="B3" t="s" s="7"><v>3</v></c></row>'
            '</sheetData></worksheet>')
    with zipfile.ZipFile(plantilla, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/sharedStrings.xml", shared)
        z.writestr("xl/worksheets/sheet1.xml", hoja)

    etiquetas = {e["etiqueta"]: e["valor"] for e in plantilla_xlsx.etiquetas(plantilla)}
    ok(set(etiquetas) == {"CLIENT", "VENDOR DOC. Nº"}, f"etiquetas leídas: {list(etiquetas)}")
    ok(etiquetas["CLIENT"] == "MOEVE - ONUBA", "el valor de ejemplo sale de la plantilla")

    destino = plantilla_xlsx.rellenar(plantilla, tmp / "relleno.xlsx",
                                      valores={"VENDOR DOC. Nº": "26-062-CAL-0002"})
    with zipfile.ZipFile(destino) as z:
        hoja_rell = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    ok("26-062-CAL-0002" in hoja_rell, "el valor nuevo se escribe en la celda de al lado")
    ok('s="7"' in hoja_rell, "la celda conserva su formato")
    ok("inlineStr" in hoja_rell, "se escribe dentro de la celda, no en la tabla común")
    with zipfile.ZipFile(destino) as z:
        comun = z.read("xl/sharedStrings.xml").decode("utf-8")
    ok("26-062-DL-0001" in comun, "la tabla común no se toca (la comparten otras hojas)")

    # Una etiqueta que no se mapea se queda con lo que traía
    quedan = {e["etiqueta"]: e["valor"] for e in plantilla_xlsx.etiquetas(destino)}
    ok(quedan.get("CLIENT") == "MOEVE - ONUBA",
       f"lo que no se mapea se queda como estaba: {quedan.get('CLIENT')!r}")
    ok(quedan.get("VENDOR DOC. Nº") == "26-062-CAL-0002",
       f"y lo mapeado se relee bien: {quedan.get('VENDOR DOC. Nº')!r}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ── Etiqueta y valor en la misma celda (la portada nueva de MOEVE) ──────────
tmp = Path(tempfile.mkdtemp())
try:
    plantilla = tmp / "junta.xlsx"
    shared = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="3">'
              '<si><t>PLANTA:\nBIOS</t></si>'
              '<si><t>Nº DOCUMENTO:\nV-2201BI01A0BG-2206-740-DL-001</t></si>'
              '<si><t>ITEM-TAG:\nBR10S 0001</t></si>'
              '</sst>')
    hoja = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetData>'
            '<row r="2"><c r="A2" t="s" s="4"><v>0</v></c></row>'
            '<row r="3"><c r="A3" t="s" s="4"><v>1</v></c>'
            '<c r="E3" t="s" s="4"><v>2</v></c></row>'
            '</sheetData></worksheet>')
    with zipfile.ZipFile(plantilla, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/sharedStrings.xml", shared)
        z.writestr("xl/worksheets/sheet1.xml", hoja)

    leidas = {e["etiqueta"]: e["valor"] for e in plantilla_xlsx.etiquetas(plantilla)}
    ok(set(leidas) == {"PLANTA", "Nº DOCUMENTO", "ITEM-TAG"}, f"etiquetas: {list(leidas)}")
    ok(leidas["ITEM-TAG"] == "BR10S 0001", f"valor tras el salto de línea: {leidas['ITEM-TAG']!r}")
    ok(leidas["Nº DOCUMENTO"] == "V-2201BI01A0BG-2206-740-DL-001", "dos etiquetas en la misma fila")

    destino = plantilla_xlsx.rellenar(plantilla, tmp / "relleno.xlsx", valores={
        "Nº DOCUMENTO": "V-2201BI01A0BG-2206-740-CAL-001", "ITEM-TAG": "ALL TAGS"})
    quedan = {e["etiqueta"]: e["valor"] for e in plantilla_xlsx.etiquetas(destino)}
    ok(quedan["Nº DOCUMENTO"] == "V-2201BI01A0BG-2206-740-CAL-001", f"escrito: {quedan}")
    ok(quedan["ITEM-TAG"] == "ALL TAGS", "y el otro de la misma fila")
    ok(quedan["PLANTA"] == "BIOS", "lo que no se mapea no se toca")
    with zipfile.ZipFile(destino) as z:
        hoja_rell = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    ok("Nº DOCUMENTO:" in hoja_rell, "la etiqueta sigue delante del valor, en su celda")
    ok('s="4"' in hoja_rell, "y la celda conserva su formato")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ── Rótulos que la sangría parte al exportar a PDF (FECHA en la de MOEVE) ────
tmp = Path(tempfile.mkdtemp())
try:
    plantilla = tmp / "sangrias.xlsx"
    estilos = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
               '<fonts count="1"><font><sz val="10"/><name val="Century Gothic"/></font></fonts>'
               '<cellXfs count="4">'
               '<xf numFmtId="0" fontId="0"/>'
               # 1: FECHA, a la derecha con sangría 8 en una columna de 25
               '<xf numFmtId="0" fontId="0" applyAlignment="1"><alignment horizontal="right" '
               'vertical="center" wrapText="1" indent="8"/></xf>'
               # 2: «ESTADO DEL DOCUMENTO», sangría 7 pero en tres columnas combinadas: cabe
               '<xf numFmtId="0" fontId="0" applyAlignment="1"><alignment horizontal="right" '
               'vertical="center" wrapText="1" indent="7"/></xf>'
               # 3: «A RELLENAR POR MOEVE», dos líneas entre palabras: normal
               '<xf numFmtId="0" fontId="0" applyAlignment="1"><alignment horizontal="left" '
               'vertical="center" wrapText="1" indent="1"/></xf>'
               '</cellXfs></styleSheet>')
    hoja = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<cols><col min="1" max="1" width="15.3"/><col min="2" max="2" width="14.1"/>'
            '<col min="3" max="3" width="17"/><col min="4" max="4" width="7.4"/>'
            '<col min="5" max="5" width="24.9"/></cols>'
            '<sheetData>'
            '<row r="4"><c r="A4" t="inlineStr" s="2"><is><t>ESTADO DEL DOCUMENTO</t></is></c>'
            '<c r="E4" t="inlineStr" s="1"><is><t>FECHA</t></is></c></row>'
            '<row r="9"><c r="A9" t="inlineStr" s="3"><is><t>A RELLENAR POR MOEVE</t></is></c></row>'
            '</sheetData><mergeCells count="1"><mergeCell ref="A4:C4"/></mergeCells></worksheet>')
    with zipfile.ZipFile(plantilla, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/styles.xml", estilos)
        z.writestr("xl/worksheets/sheet1.xml", hoja)

    destino = plantilla_xlsx.rellenar(plantilla, tmp / "relleno.xlsx", valores={})
    with zipfile.ZipFile(destino) as z:
        salida = z.read("xl/styles.xml").decode("utf-8")
    alineaciones = salida.split("<alignment")[1:]
    ok('horizontal="center"' in alineaciones[0] and "indent" not in alineaciones[0],
       f"FECHA pasa a centrado sin sangría: {alineaciones[0][:80]}")
    ok('indent="7"' in alineaciones[1], "la sangría que cabe (celda combinada) se respeta")
    ok('indent="1"' in alineaciones[2], "partir entre palabras no es romper un rótulo")
    ok(len(salida) - len(estilos) == len('horizontal="center"') - len('horizontal="right" indent="8"'),
       "styles.xml sale igual byte a byte salvo esa alineación")

    # Sin nada que arreglar, el fichero de estilos no se toca
    sin = plantilla_xlsx._sin_sangrias_que_parten(estilos.encode(), {})
    ok(sin == estilos.encode(), "sin celdas que lo usen, nada cambia")

    # Y el valor que ya pone lo mismo no se reescribe (perdería negritas y demás)
    with zipfile.ZipFile(plantilla, "a") as z:
        z.writestr("xl/sharedStrings.xml", '<?xml version="1.0" encoding="UTF-8"?>'
                   '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>')
    igual = plantilla_xlsx.rellenar(plantilla, tmp / "igual.xlsx",
                                    valores={"ESTADO DEL DOCUMENTO": "FECHA"})
    with zipfile.ZipFile(plantilla) as a, zipfile.ZipFile(igual) as b:
        ok(a.read("xl/worksheets/sheet1.xml") == b.read("xl/worksheets/sheet1.xml"),
           "si el valor ya es ese, la hoja sale intacta")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("FALLOS:", fallos)
