# -*- coding: utf-8 -*-
"""El menú lateral: que se pueda llegar abajo y que la rueda lo mueva.

    docflow_env\\Scripts\\python.exe tests\\test_menu_lateral.py
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import customtkinter as ctk

from gui.app import DocFlowLiteApp
from gui.widgets.sidebar import Sidebar
from gui.widgets.ui import RUEDA_PX

fallos = 0


def ok(cond, msg):
    global fallos
    if not cond:
        fallos += 1
        print("  FALLO:", msg)


root = ctk.CTk()
root.geometry("1000x560")          # una pantalla de portátil, de las justas
root.update_idletasks()

sb = Sidebar(root, DocFlowLiteApp.NAV_LAYOUT, on_select=lambda k: None,
             on_toggle_theme=lambda: None, on_logout=lambda: None,
             on_search=lambda: None, current_user_label="Jose Paredes")
sb.pack(side="left", fill="y")
root.update()

canvas = sb._nav._parent_canvas
barra = sb._nav._scrollbar

# ── Todos los grupos abiertos: no cabe, así que hay barra ────────────────────
for gid in list(sb._groups):
    sb._toggle_group(gid, expand=True)
root.update()
sb._ajusta_scroll()
root.update()

caja = canvas.bbox("all")
alto_contenido = caja[3] - caja[1]
ok(alto_contenido > canvas.winfo_height(),
   f"con todo abierto no debería caber: contenido {alto_contenido} vs ventana {canvas.winfo_height()}")
ok(bool(barra.grid_info()), "con todo abierto tiene que verse la barra de scroll")

ultimo = DocFlowLiteApp.NAV_LAYOUT[-1]["items"][-1]["key"]
fila = sb._items[ultimo]["row"]
fuera = (fila.winfo_rooty() - canvas.winfo_rooty()) + fila.winfo_height() > canvas.winfo_height()
ok(fuera, f"«{ultimo}» debería quedar fuera de la vista al abrir todo")

# ── Se puede llegar hasta él: al activarlo, el menú se desplaza ──────────────
sb.set_active(ultimo)
root.update()
sb._asegura_visible(ultimo)
root.update()
arriba = fila.winfo_rooty() - canvas.winfo_rooty()
ok(0 <= arriba and arriba + fila.winfo_height() <= canvas.winfo_height() + 2,
   f"tras activarlo debería verse entero: y={arriba}, alto ventana={canvas.winfo_height()}")

# ── La rueda: manda dónde está el ratón, no quién tiene el foco ──────────────
canvas.yview_moveto(0)
root.update()


def rueda(delta, encima):
    """Una muesca de rueda con el puntero dentro o fuera del menú."""
    destino = sb._items[ultimo]["btn"] if encima else root
    sb._nav.winfo_containing = lambda x, y, _d=destino: _d
    return sb._rueda(types.SimpleNamespace(delta=delta, x_root=0, y_root=0))


antes = canvas.canvasy(0)
corta = rueda(-120, encima=True)        # rueda hacia abajo, ratón en el menú
root.update()
bajado = canvas.canvasy(0) - antes
ok(corta == "break", "con el ratón en el menú, la rueda es nuestra (no la del resto)")
ok(bajado > 0, f"la rueda hacia abajo mueve el menú: {bajado} px")
ok(abs(bajado - RUEDA_PX) <= 2, f"una muesca son tres filas ({RUEDA_PX} px), no media: {bajado}")

antes = canvas.canvasy(0)
rueda(120, encima=True)                 # y hacia arriba vuelve
root.update()
ok(canvas.canvasy(0) < antes, "la rueda hacia arriba sube el menú")

# Con el ratón fuera, ni se toca el menú ni se le quita la rueda a nadie
canvas.yview_moveto(0.5)
root.update()
antes = canvas.canvasy(0)
corta = rueda(-120, encima=False)
root.update()
ok(corta is None, "fuera del menú la rueda sigue su camino")
ok(canvas.canvasy(0) == antes, "y el menú no se mueve")

# ── El pie sigue en su sitio, y la barra se quita cuando cabe ───────────────
visible = sb._nav._parent_frame
ok(sb.winfo_height() > visible.winfo_height(),
   f"tiene que quedar sitio para el pie: {sb.winfo_height()} vs {visible.winfo_height()}")

for gid in list(sb._groups):
    sb._toggle_group(gid, expand=False)
root.geometry("1000x900")
root.update()
sb._ajusta_scroll()
root.update()
caja = canvas.bbox("all")
ok((caja[3] - caja[1]) <= canvas.winfo_height() + 2, "plegado y en pantalla grande cabe")
ok(not barra.grid_info(), "si cabe todo, la barra sobra y no debe verse")

# Y sin nada que desplazar, la rueda tampoco se queda el evento
ok(rueda(-120, encima=True) is None, "si no hay scroll, la rueda pasa de largo")

root.destroy()
print("FALLOS:", fallos)
