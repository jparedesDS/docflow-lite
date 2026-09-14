"""Vista Portadas — generar las portadas de los documentos de un pedido.

Tres pasos, y los dos primeros solo la primera vez de cada cliente:

  1. Se eligen las plantillas que manda el cliente (uno o varios .docx, que se
     encadenan en un solo PDF).
  2. Se empareja cada hueco de la plantilla con lo que va dentro: campos del
     ERP entre llaves mezclados con el texto fijo que haga falta
     («{Tag} ALL ITEMS»).
  3. Se marcan los documentos y se genera: cada portada va a la carpeta `env.`
     de su documento, como `PORTADA <nº del cliente>.pdf`.

Lo de los pasos 1 y 2 se guarda por cliente, así que el siguiente pedido de ese
cliente empieza directamente en el 3.
"""

import logging
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from core.services import monitoring as monitoring_service
from core.services import portadas_lote
from gui import theme
from gui.widgets import ui

logger = logging.getLogger(__name__)


class PortadasView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._docs: list[dict] = []          # documentos del pedido elegido
        self._marcas: list[ctk.BooleanVar] = []
        self._pedidos: list[str] = []
        self._cliente = ""
        self._perfil = {"plantillas": [], "mapa": {}}
        self._build()
        self.after(80, self._cargar_pedidos)

    # ── Construcción ──────────────────────────────────────────────────────────

    def _build(self) -> None:
        cab = ui.page_header(
            self, "Portadas", "Rellena la plantilla del cliente con los datos de cada documento",
            icon="🖹", help_key="portadas")

        self.btn_generar = ui.button(cab.actions, "Generar portadas", "primary",
                                     command=self._generar, state="disabled")
        self.btn_generar.pack(side="right")
        self.btn_campos = ui.button(cab.actions, "Campos…", "outline", command=self._abrir_campos,
                                    state="disabled")
        self.btn_campos.pack(side="right", padx=(0, theme.SPACE_2))
        self.btn_plantillas = ui.button(cab.actions, "Plantillas…", "outline",
                                        command=self._elegir_plantillas, state="disabled")
        self.btn_plantillas.pack(side="right", padx=(0, theme.SPACE_2))

        barra = ctk.CTkFrame(self, fg_color="transparent")
        barra.pack(fill="x", padx=theme.SPACE_6, pady=(0, theme.SPACE_3))
        ctk.CTkLabel(barra, text="Pedido", font=theme.FONT_SMALL_BOLD,
                     text_color=theme.TEXT_SUB).pack(side="left", padx=(0, theme.SPACE_2))
        self.cmb_pedido = ctk.CTkComboBox(barra, values=["—"], width=260, state="readonly",
                                          command=lambda _v: self._cargar_docs())
        self.cmb_pedido.pack(side="left")
        self.lbl_perfil = ctk.CTkLabel(barra, text="", font=theme.FONT_SMALL,
                                       text_color=theme.TEXT_MUTED, anchor="w")
        self.lbl_perfil.pack(side="left", padx=(theme.SPACE_4, 0), fill="x", expand=True)

        self.cuerpo = ctk.CTkScrollableFrame(self, fg_color=theme.BG_CARD,
                                             corner_radius=theme.RADIUS_MD)
        self.cuerpo.pack(fill="both", expand=True, padx=theme.SPACE_6, pady=(0, theme.SPACE_5))

    # ── Datos ─────────────────────────────────────────────────────────────────

    def _cargar_pedidos(self) -> None:
        def trabajo():
            docs = monitoring_service.get_monitoring_data()
            pedidos = sorted({str(d.get("Nº Pedido", "")).strip()
                              for d in docs if str(d.get("Nº Pedido", "")).strip()}, reverse=True)
            self.after(0, lambda: self._pinta_pedidos(pedidos))
        threading.Thread(target=trabajo, daemon=True).start()

    def _pinta_pedidos(self, pedidos: list[str]) -> None:
        self._pedidos = pedidos
        self.cmb_pedido.configure(values=pedidos or ["—"])
        if pedidos:
            self.cmb_pedido.set(pedidos[0])
            self._cargar_docs()

    def _cargar_docs(self) -> None:
        pedido = self.cmb_pedido.get()

        def trabajo():
            todos = monitoring_service.get_monitoring_data()
            docs = [d for d in todos if str(d.get("Nº Pedido", "")).strip() == pedido]
            self.after(0, lambda: self._pinta_docs(docs))
        threading.Thread(target=trabajo, daemon=True).start()

    def _pinta_docs(self, docs: list[dict]) -> None:
        self._docs = docs
        self._cliente = str(docs[0].get("Cliente", "")).strip() if docs else ""
        self._perfil = portadas_lote.perfil(self._cliente) if self._cliente else {"plantillas": [], "mapa": {}}
        for w in self.cuerpo.winfo_children():
            w.destroy()
        self._marcas = []

        listo = bool(self._cliente)
        for b in (self.btn_plantillas, self.btn_campos):
            b.configure(state="normal" if listo else "disabled")
        self._refresca_perfil()

        if not docs:
            ui.empty_state(self.cuerpo, "Este pedido no tiene documentos",
                           "Elige otro pedido arriba.", icon="○")
            return

        cab = ctk.CTkFrame(self.cuerpo, fg_color="transparent")
        cab.pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_2, theme.SPACE_1))
        self.var_todos = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(cab, text="", variable=self.var_todos, width=24,
                        command=self._marcar_todos).pack(side="left")
        for texto, ancho in (("Documento", 300), ("Título", 320), ("Rev.", 50), ("Carpeta", 220)):
            ctk.CTkLabel(cab, text=texto, font=theme.FONT_SMALL_BOLD, width=ancho, anchor="w",
                         text_color=theme.TEXT_SUB).pack(side="left", padx=(0, theme.SPACE_2))

        for doc in docs:
            self._fila(doc)
        self._refresca_generar()

    def _fila(self, doc: dict) -> None:
        fila = ctk.CTkFrame(self.cuerpo, fg_color="transparent")
        fila.pack(fill="x", padx=theme.SPACE_3, pady=1)
        var = ctk.BooleanVar(value=True)
        self._marcas.append(var)
        ctk.CTkCheckBox(fila, text="", variable=var, width=24).pack(side="left")

        destino = portadas_lote.destino_portada(doc)
        carpeta = destino.parent.name if destino else "— sin carpeta env. —"
        color = theme.TEXT_MUTED if destino else theme.AMBER
        campos = (
            (str(doc.get("Nº Doc. Cliente", "") or "—"), 300, theme.TEXT_MAIN),
            (str(doc.get("Título", "") or ""), 320, theme.TEXT_SUB),
            (str(doc.get("Nº Revisión", "") or ""), 50, theme.TEXT_SUB),
            (carpeta, 220, color),
        )
        for texto, ancho, col in campos:
            ctk.CTkLabel(fila, text=texto, font=theme.FONT_SMALL, width=ancho, anchor="w",
                         text_color=col).pack(side="left", padx=(0, theme.SPACE_2))

    def _marcar_todos(self) -> None:
        for v in self._marcas:
            v.set(self.var_todos.get())

    def _refresca_perfil(self) -> None:
        n_plantillas = len(self._perfil.get("plantillas") or [])
        n_mapa = len([v for v in (self._perfil.get("mapa") or {}).values() if v])
        if not self._cliente:
            texto = ""
        elif not n_plantillas:
            texto = f"{self._cliente}: sin plantilla — empieza por «Plantillas…»"
        else:
            nombres = ", ".join(Path(p).name for p in self._perfil["plantillas"])
            texto = f"{self._cliente}: {nombres} · {n_mapa} campo(s) emparejado(s)"
        self.lbl_perfil.configure(text=texto)
        self._refresca_generar()

    def _refresca_generar(self) -> None:
        listo = bool(self._perfil.get("plantillas")) and bool(self._docs)
        self.btn_generar.configure(state="normal" if listo else "disabled")

    # ── Plantillas y campos ───────────────────────────────────────────────────

    def _elegir_plantillas(self) -> None:
        rutas = filedialog.askopenfilenames(
            parent=self, title=f"Plantillas de portada de {self._cliente}",
            filetypes=[("Documentos de Word", "*.docx"), ("Todos", "*.*")])
        if not rutas:
            return
        self._perfil["plantillas"] = list(rutas)
        portadas_lote.guardar_perfil(self._cliente, self._perfil["plantillas"],
                                     self._perfil.get("mapa") or {})
        self._refresca_perfil()
        self._abrir_campos()

    def _abrir_campos(self) -> None:
        if not self._perfil.get("plantillas"):
            ui.toast(self, "Falta la plantilla",
                     "Elige primero el Word que manda el cliente.", kind="warning")
            return
        ejemplo = self._docs[0] if self._docs else {}
        VentanaCampos(self, self._cliente, self._perfil, ejemplo, self._tras_campos)

    def _tras_campos(self, mapa: dict) -> None:
        self._perfil["mapa"] = mapa
        portadas_lote.guardar_perfil(self._cliente, self._perfil["plantillas"], mapa)
        self._refresca_perfil()

    # ── Generar ───────────────────────────────────────────────────────────────

    def _generar(self) -> None:
        elegidos = [d for d, v in zip(self._docs, self._marcas) if v.get()]
        if not elegidos:
            ui.toast(self, "Nada que hacer", "No has marcado ningún documento.", kind="warning")
            return
        if not ui.confirm(self, "Generar portadas",
                          f"Se van a generar {len(elegidos)} portada(s) de {self._cliente}.\n"
                          "Cada una se guarda en la carpeta env. de su documento.\n\n"
                          "¿Seguimos?"):
            return
        self.btn_generar.configure(state="disabled", text="Generando…")

        def trabajo():
            try:
                res = portadas_lote.generar_lote(
                    elegidos, self._perfil["plantillas"], self._perfil.get("mapa") or {},
                    progreso=lambda i, n, c: self.after(
                        0, lambda: self.btn_generar.configure(text=f"Generando… {i}/{n}")))
            except Exception as exc:  # noqa: BLE001 — el aviso va a la interfaz
                logger.exception("Generar portadas")
                aviso = str(exc)      # `exc` no vive fuera del except: se copia
                self.after(0, lambda: self._fin_generar([], aviso))
                return
            self.after(0, lambda: self._fin_generar(res, ""))
        threading.Thread(target=trabajo, daemon=True).start()

    def _fin_generar(self, resultados: list[dict], error: str) -> None:
        self.btn_generar.configure(state="normal", text="Generar portadas")
        if error:
            ui.toast(self, "No se pudieron generar", error, kind="error")
            return
        bien = [r for r in resultados if not r["error"]]
        mal = [r for r in resultados if r["error"]]
        if mal:
            detalle = "\n".join(
                f"· {r['doc'].get('Nº Doc. Cliente', '?')}: {r['error']}" for r in mal[:6])
            logger.warning("Portadas sin generar:\n%s", detalle)
            ui.toast(self, f"{len(bien)} portada(s) generada(s)",
                     f"{len(mal)} se han quedado fuera (mira el registro).", kind="warning")
        else:
            ui.toast(self, "Portadas generadas",
                     f"{len(bien)} en las carpetas env. de sus documentos.", kind="success")


class VentanaCampos(ctk.CTkToplevel):
    """Emparejar cada hueco de la plantilla con lo que va dentro.

    Una vez por cliente: los huecos salen de la propia plantilla y el valor es
    texto normal con campos del ERP entre llaves, que se ven al lado con lo que
    valdrían para el primer documento del pedido.
    """

    def __init__(self, master, cliente: str, perfil: dict, ejemplo: dict, al_guardar):
        super().__init__(master)
        self.title(f"Campos de la portada · {cliente}")
        self.geometry("860x620")
        self.configure(fg_color=theme.BG_PAGE)
        self.transient(master.winfo_toplevel())
        self._al_guardar = al_guardar
        self._valores = portadas_lote.valores_documento(ejemplo) if ejemplo else {}
        self._entradas: dict[str, ctk.CTkEntry] = {}
        self._previas: dict[str, ctk.CTkLabel] = {}
        self._build(perfil)
        self.after(120, self.lift)

    def _build(self, perfil: dict) -> None:
        cab = ui.page_header(
            self, "Campos de la portada",
            "Escribe lo que va en cada hueco. Los campos del ERP van entre llaves.",
            icon="🖹", pad_bottom=theme.SPACE_2)
        ui.button(cab.actions, "Guardar", "primary", command=self._guardar).pack(side="right")

        ayuda = ctk.CTkFrame(self, fg_color=theme.BG_CARD, corner_radius=theme.RADIUS_MD)
        ayuda.pack(fill="x", padx=theme.SPACE_6, pady=(0, theme.SPACE_3))
        texto = "  ·  ".join(f"{{{k}}}" for k, _ in portadas_lote.CAMPOS)
        ctk.CTkLabel(ayuda, text="Campos disponibles: " + texto, font=theme.FONT_SMALL,
                     text_color=theme.TEXT_SUB, wraplength=780, justify="left"
                     ).pack(anchor="w", padx=theme.SPACE_3, pady=theme.SPACE_2)

        cuerpo = ctk.CTkScrollableFrame(self, fg_color=theme.BG_CARD,
                                        corner_radius=theme.RADIUS_MD)
        cuerpo.pack(fill="both", expand=True, padx=theme.SPACE_6, pady=(0, theme.SPACE_5))

        huecos = portadas_lote.huecos(perfil.get("plantillas") or [])
        if not huecos:
            ui.empty_state(cuerpo, "La plantilla no tiene huecos que rellenar",
                           "Si no es una tabla «ETIQUETA : valor», escribe {{MARCADORES}} "
                           "en el Word donde vaya cada dato.", icon="○")
            return
        mapa = perfil.get("mapa") or {}
        for h in huecos:
            self._fila(cuerpo, h, mapa.get(h["clave"], ""))

    def _fila(self, padre, hueco: dict, patron: str) -> None:
        fila = ctk.CTkFrame(padre, fg_color="transparent")
        fila.pack(fill="x", padx=theme.SPACE_3, pady=3)

        marca = "{{ }}" if hueco["tipo"] == "marca" else ""
        etiqueta = ctk.CTkLabel(fila, text=f"{hueco['clave']} {marca}".strip(),
                                font=theme.FONT_SMALL_BOLD, width=230, anchor="w",
                                text_color=theme.TEXT_MAIN)
        etiqueta.pack(side="left", padx=(0, theme.SPACE_2))
        if hueco.get("ejemplo"):
            ui.tooltip(etiqueta, f"En la plantilla pone: {hueco['ejemplo']}")

        entrada = ctk.CTkEntry(fila, width=300, height=theme.HEIGHT_INPUT)
        entrada.insert(0, patron)
        entrada.pack(side="left", padx=(0, theme.SPACE_2))
        self._entradas[hueco["clave"]] = entrada

        previa = ctk.CTkLabel(fila, text="", font=theme.FONT_SMALL, anchor="w",
                              text_color=theme.TEXT_MUTED, width=240)
        previa.pack(side="left", fill="x", expand=True)
        self._previas[hueco["clave"]] = previa
        entrada.bind("<KeyRelease>", lambda _e, c=hueco["clave"]: self._previsualiza(c))
        self._previsualiza(hueco["clave"])

    def _previsualiza(self, clave: str) -> None:
        patron = self._entradas[clave].get()
        texto = portadas_lote.aplicar(patron, self._valores) if patron else ""
        self._previas[clave].configure(text=f"→ {texto}" if texto else "")

    def _guardar(self) -> None:
        mapa = {k: e.get().strip() for k, e in self._entradas.items()}
        self._al_guardar({k: v for k, v in mapa.items() if v})
        self.destroy()
