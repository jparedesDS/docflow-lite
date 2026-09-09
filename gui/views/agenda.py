"""Vista Agenda — tareas, notas y reuniones en una sola pantalla."""

import logging
import threading
from datetime import datetime

import customtkinter as ctk
from tkinter import messagebox

from core.services import agenda as agenda_service
from core.services import monitoring as monitoring_service
from gui import theme
from gui.widgets import ui
from gui.widgets.scrollframe import ScrollFrame

logger = logging.getLogger(__name__)

DEFAULT_OWNER = agenda_service.DEFAULT_OWNER

PRIORITY_COLORS = {"alta": theme.RED, "media": theme.AMBER, "baja": theme.GREEN}
ESTADO_COLORS = {"pendiente": theme.AMBER, "en_progreso": theme.BLUE, "completada": theme.GREEN}
NOTE_COLORS = [
    ("default", theme.BG_CARD,    "Default"),
    ("blue",    theme.NOTE_BLUE,  "Azul"),
    ("green",   theme.NOTE_GREEN, "Verde"),
    ("amber",   theme.NOTE_AMBER, "Ámbar"),
    ("rose",    theme.NOTE_ROSE,  "Rosa"),
]
NOTE_COLOR_MAP = {k: c for k, c, _ in NOTE_COLORS}


class AgendaView(ctk.CTkFrame):
    """Todo el día en una pantalla: tareas agrupadas por cuándo tocan, y al
    lado las notas y las próximas reuniones. Antes eran tres pestañas y había
    que ir a mirar cada una."""

    # Grupos de tareas, en orden de urgencia: (clave, título, color)
    GRUPOS = [
        ("vencidas", "Vencidas", theme.RED),
        ("hoy", "Hoy", theme.AMBER),
        ("semana", "Esta semana", theme.BLUE),
        ("despues", "Más adelante", theme.TEXT_SUB),
        ("sin_fecha", "Sin fecha", theme.TEXT_MUTED),
    ]
    # Por debajo de este ancho, las dos columnas se apilan
    _TWO_COL_MIN = 1180

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._tareas: list[dict] = []
        self._notas: list[dict] = []
        self._reuniones: list[dict] = []
        self._ver_hechas = False
        self._build_layout()
        self.after(50, self._reload_all)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        hdr = ui.page_header(self, "Agenda",
                             f"Tus tareas, notas y reuniones en un solo sitio · {DEFAULT_OWNER}",
                             help_key="agenda")
        ui.button(hdr.actions, "↻  Sincronizar con Documentos", "outline", size="sm",
                  command=self._sync_tareas).pack(side="right", padx=(theme.SPACE_2, 0))

        body = ScrollFrame(self)
        body.pack(fill="both", expand=True, padx=theme.SPACE_6, pady=(0, theme.SPACE_4))
        self._body = body

        # Cifras del día
        self._stats_host = ctk.CTkFrame(body, fg_color="transparent")
        self._stats_host.pack(fill="x", pady=(0, theme.SPACE_3))

        # Botonera de creación
        bar = ctk.CTkFrame(body, fg_color="transparent")
        bar.pack(fill="x", pady=(0, theme.SPACE_3))
        ui.button(bar, "+  Tarea", "primary",
                  command=lambda: TareaEditor(self, on_save=self._reload_all)).pack(side="left")
        ui.button(bar, "+  Nota", "secondary",
                  command=lambda: NotaEditor(self, on_save=self._reload_all)).pack(
            side="left", padx=(theme.SPACE_2, 0))
        ui.button(bar, "+  Reunión", "secondary",
                  command=lambda: ReunionEditor(self, on_save=self._reload_all)).pack(
            side="left", padx=(theme.SPACE_2, 0))
        self.var_hechas = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(bar, text="Ver completadas", variable=self.var_hechas,
                        font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                        checkbox_width=18, checkbox_height=18,
                        command=self._toggle_hechas).pack(side="left", padx=(theme.SPACE_4, 0))
        self.lbl_count = ctk.CTkLabel(bar, text="", font=theme.FONT_SMALL,
                                      text_color=theme.TEXT_MUTED)
        self.lbl_count.pack(side="right")

        # Cuerpo a dos columnas: tareas a la izquierda, notas y reuniones a la derecha
        cols = ctk.CTkFrame(body, fg_color="transparent")
        cols.pack(fill="both", expand=True)
        cols.grid_columnconfigure(0, weight=62, uniform="ag")
        cols.grid_columnconfigure(1, weight=38, uniform="ag")
        self._cols_host = cols
        self.col_tareas = ctk.CTkFrame(cols, fg_color="transparent")
        self.col_lado = ctk.CTkFrame(cols, fg_color="transparent")
        self._dos_cols = None
        self._apply_columns()
        cols.bind("<Configure>", lambda e: self._apply_columns(e.width))

    def _apply_columns(self, ancho: int | None = None) -> None:
        if ancho is None:
            ancho = self._cols_host.winfo_width()
        dos = ancho >= self._TWO_COL_MIN
        if self._dos_cols is dos:
            return
        self._dos_cols = dos
        # columnspan siempre explícito: grid() conserva el anterior
        if dos:
            self.col_tareas.grid(row=0, column=0, columnspan=1, sticky="nsew",
                                 padx=(0, theme.SPACE_3), pady=0)
            self.col_lado.grid(row=0, column=1, columnspan=1, sticky="nsew", pady=0)
        else:
            self.col_tareas.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=0, pady=0)
            self.col_lado.grid(row=1, column=0, columnspan=2, sticky="nsew",
                               padx=0, pady=(theme.SPACE_3, 0))

    def _toggle_hechas(self) -> None:
        self._ver_hechas = bool(self.var_hechas.get())
        self._render_all()

    # ── Carga ─────────────────────────────────────────────────────────────────

    def _reload_all(self) -> None:
        try:
            self._tareas = agenda_service.get_tareas(DEFAULT_OWNER)
        except Exception:
            logger.exception("Error cargando tareas")
            self._tareas = []
        try:
            self._notas = agenda_service.get_all("notas")
        except Exception:
            logger.exception("Error cargando notas")
            self._notas = []
        try:
            self._reuniones = agenda_service.get_all("reuniones")
        except Exception:
            logger.exception("Error cargando reuniones")
            self._reuniones = []
        self._render_all()

    # Alias para los editores y acciones que recargaban una sola colección
    _reload_tareas = _reload_all
    _reload_notas = _reload_all
    _reload_reuniones = _reload_all

    # ── Pintado ───────────────────────────────────────────────────────────────

    def _render_all(self) -> None:
        grupos = self._agrupar(self._tareas)
        self._render_stats(grupos)
        for w in self.col_tareas.winfo_children():
            w.destroy()
        for w in self.col_lado.winfo_children():
            w.destroy()
        self._render_tareas(grupos)
        self._render_notas()
        self._render_reuniones()

    @staticmethod
    def _agrupar(tareas: list[dict]) -> dict:
        """Reparte las tareas por cuándo tocan: vencidas, hoy, semana, después…"""
        out: dict[str, list] = {k: [] for k, _, _ in AgendaView.GRUPOS}
        out["hechas"] = []
        hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        for t in tareas:
            if t.get("estado") == "completada":
                out["hechas"].append(t)
                continue
            d = _parse_fecha(t.get("fecha_limite"))
            if d is None:
                out["sin_fecha"].append(t)
                continue
            dias = (d - hoy).days
            if dias < 0:
                out["vencidas"].append(t)
            elif dias == 0:
                out["hoy"].append(t)
            elif dias <= 7:
                out["semana"].append(t)
            else:
                out["despues"].append(t)
        for k in out:
            out[k].sort(key=_tarea_sort_key)
        return out

    def _render_stats(self, grupos: dict) -> None:
        for w in self._stats_host.winfo_children():
            w.destroy()
        pendientes = sum(len(grupos[k]) for k, _, _ in self.GRUPOS)
        venc, hoy = len(grupos["vencidas"]), len(grupos["hoy"])
        ui.stat_strip(self._stats_host, [
            (str(pendientes), "por hacer", theme.TEXT_MAIN, ""),
            (str(venc), "vencidas", theme.RED if venc else theme.TEXT_MUTED,
             "pasadas de fecha" if venc else ""),
            (str(hoy), "para hoy", theme.AMBER if hoy else theme.TEXT_MUTED, ""),
            (str(len(grupos["semana"])), "esta semana", theme.BLUE, ""),
            (str(len(grupos["hechas"])), "completadas", theme.GREEN, ""),
            (str(len(self._notas)), "notas", theme.TEXT_SUB, ""),
            (str(len(self._reuniones)), "reuniones", theme.TEXT_SUB, ""),
        ])
        self.lbl_count.configure(
            text=f"{pendientes} por hacer · {len(grupos['hechas'])} completadas")

    def _render_tareas(self, grupos: dict) -> None:
        parent = self.col_tareas
        pendientes = sum(len(grupos[k]) for k, _, _ in self.GRUPOS)
        if not pendientes and not grupos["hechas"]:
            ui.empty_state(parent, "Sin tareas",
                           hint="Crea una con «+ Tarea» o trae las tuyas de Documentos "
                                "con «Sincronizar».", icon="✓", pady=40)
            return
        if not pendientes:
            ui.empty_state(parent, "Todo hecho",
                           hint=f"No queda nada pendiente · {len(grupos['hechas'])} completadas.",
                           icon="✓", pady=30)

        for clave, titulo, color in self.GRUPOS:
            items = grupos[clave]
            if not items:
                continue
            self._grupo_header(parent, titulo, len(items), color)
            for t in items:
                self._render_tarea_card(parent, t)

        hechas = grupos["hechas"]
        if hechas:
            self._grupo_header(parent, "Completadas", len(hechas), theme.GREEN)
            if self._ver_hechas:
                for t in hechas:
                    self._render_tarea_card(parent, t)
            else:
                ctk.CTkLabel(parent, text="Ocultas — marca «Ver completadas» para verlas.",
                             font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
                             anchor="w").pack(fill="x", pady=(0, theme.SPACE_3))

    @staticmethod
    def _grupo_header(parent, titulo: str, n: int, color: str) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(theme.SPACE_3, theme.SPACE_2))
        ctk.CTkFrame(row, fg_color=color, width=4, height=18,
                     corner_radius=2).pack(side="left", padx=(0, theme.SPACE_2))
        ctk.CTkLabel(row, text=titulo.upper(), font=theme.FONT_SECTION,
                     text_color=theme.TEXT_MAIN).pack(side="left")
        ui.badge(row, str(n), color).pack(side="left", padx=(theme.SPACE_2, 0))

    # ════════════════════════════════════════════════════════════════════════
    #  TAREAS
    # ════════════════════════════════════════════════════════════════════════

    def _render_tarea_card(self, parent, t: dict) -> None:
        is_done = t.get("estado") == "completada"
        prio = (t.get("prioridad") or "media").lower()
        prio_color = PRIORITY_COLORS.get(prio, theme.TEXT_MUTED)

        card = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=theme.RADIUS_MD,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x", pady=2)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=theme.SPACE_3, pady=theme.SPACE_2)

        var_done = ctk.BooleanVar(value=is_done)
        ctk.CTkCheckBox(
            row, text="", variable=var_done, width=20, checkbox_width=18, checkbox_height=18,
            fg_color=theme.GREEN, hover_color=theme.GREEN, border_width=2,
            command=lambda: self._toggle_tarea_done(t, var_done.get()),
        ).pack(side="left", padx=(0, theme.SPACE_2))

        # Punto de prioridad
        ctk.CTkLabel(row, text="●", font=theme.font(14, "bold"),
                     text_color=prio_color, width=14).pack(side="left", padx=(0, theme.SPACE_2))

        # Lo de la derecha va PRIMERO: si se empaqueta después del título con
        # expand=True, éste se queda todo el ancho y le pasa por encima.
        ui.icon_button(row, "🗑", danger=True,
                       command=lambda: self._delete_tarea(t)).pack(side="right", padx=1)
        ui.icon_button(row, "✏",
                       command=lambda: TareaEditor(self, tarea=t, on_save=self._reload_all)
                       ).pack(side="right", padx=1)

        fecha = t.get("fecha_limite") or ""
        if fecha:
            d_label, d_color = _fecha_status(fecha, is_done)
            ctk.CTkLabel(row, text=d_label, font=theme.FONT_SMALL_BOLD,
                         text_color=d_color).pack(side="right", padx=(theme.SPACE_3, theme.SPACE_3))

        titulo = t.get("titulo", "(sin título)")
        ctk.CTkLabel(
            row, text=titulo if len(titulo) <= 68 else titulo[:67] + "…",
            font=theme.font(13, "bold" if not is_done else "normal"),
            text_color=theme.TEXT_MUTED if is_done else theme.TEXT_MAIN,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        # Pie: de dónde sale la tarea (y la descripción si la escribió alguien)
        pie = []
        if t.get("auto_generated"):
            pie.append("⚙ de Documentos")
        desc = (t.get("descripcion") or "").strip()
        if desc and not is_done:
            pie.append(desc if len(desc) <= 150 else desc[:150] + "…")
        if pie:
            ctk.CTkLabel(
                card, text="  ·  ".join(pie), font=theme.FONT_SMALL,
                text_color=theme.TEXT_MUTED, anchor="w", justify="left", wraplength=780,
            ).pack(anchor="w", padx=(theme.SPACE_6 + theme.SPACE_4, theme.SPACE_3),
                   pady=(0, theme.SPACE_2))

    def _toggle_tarea_done(self, t: dict, done: bool) -> None:
        nuevo = "completada" if done else "pendiente"
        try:
            agenda_service.update("tareas", t["id"], {"estado": nuevo})
            self._reload_tareas()
        except Exception as exc:
            logger.exception("Error toggling tarea")
            messagebox.showerror("Error", str(exc))

    def _delete_tarea(self, t: dict) -> None:
        if not messagebox.askyesno("Borrar tarea", f"¿Borrar '{t.get('titulo', '')}'?"):
            return
        try:
            agenda_service.delete("tareas", t["id"])
            self._reload_tareas()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _sync_tareas(self) -> None:
        def worker():
            try:
                docs = monitoring_service.get_monitoring_data()
                pending = [
                    d for d in docs
                    if str(d.get("Repsonsable", "") or "").strip() == DEFAULT_OWNER
                    and (d.get("Estado", "") or "").strip().lower() in agenda_service.ESTADOS_PENDIENTES
                ]
                res = agenda_service.sync_tareas(DEFAULT_OWNER, pending)
                self.after(0, lambda: self._sync_done(res))
            except Exception as exc:
                logger.exception("Error en sync_tareas")
                err = str(exc)
                self.after(0, lambda: messagebox.showerror("Error sync", err))

        threading.Thread(target=worker, daemon=True).start()

    def _sync_done(self, res: dict) -> None:
        messagebox.showinfo(
            "Sincronización completada",
            f"✓ Creadas: {res['created']}\n"
            f"✓ Actualizadas: {res['updated']}\n"
            f"✓ Marcadas completadas: {res['completed']}",
        )
        self._reload_tareas()

    # ════════════════════════════════════════════════════════════════════════
    #  NOTAS
    # ════════════════════════════════════════════════════════════════════════

    def _render_notas(self) -> None:
        parent = self.col_lado
        notas = sorted(self._notas, key=lambda n: n.get("updatedAt", ""), reverse=True)
        self._grupo_header(parent, "Notas", len(notas), theme.ACCENT)
        if not notas:
            ctk.CTkLabel(parent, text="Sin notas. Crea una con «+ Nota».",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
                         anchor="w").pack(fill="x", pady=(0, theme.SPACE_2))
            return
        for n in notas:
            self._render_nota_card(parent, n)

    def _render_nota_card(self, parent, n: dict) -> None:
        color_key = n.get("color") or "default"
        bg = NOTE_COLOR_MAP.get(color_key, theme.BG_CARD)

        card = ctk.CTkFrame(parent, fg_color=bg, corner_radius=theme.RADIUS_MD,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x", pady=2)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_2, 2))
        ui.icon_button(row, "🗑", danger=True,
                       command=lambda: self._delete_nota(n)).pack(side="right", padx=1)
        ui.icon_button(row, "✏",
                       command=lambda: NotaEditor(self, nota=n, on_save=self._reload_all)
                       ).pack(side="right", padx=1)
        ctk.CTkLabel(row, text=n.get("titulo", "(sin título)"), font=theme.font(13, "bold"),
                     text_color=theme.TEXT_MAIN, anchor="w").pack(side="left", fill="x", expand=True)

        contenido = (n.get("contenido") or "").strip()
        if contenido:
            short = contenido if len(contenido) <= 220 else contenido[:220] + "…"
            ctk.CTkLabel(card, text=short, font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                         anchor="w", justify="left", wraplength=430).pack(
                anchor="w", padx=theme.SPACE_3, pady=(0, theme.SPACE_2))

    def _delete_nota(self, n: dict) -> None:
        if not messagebox.askyesno("Borrar nota", f"¿Borrar '{n.get('titulo', '')}'?"):
            return
        try:
            agenda_service.delete("notas", n["id"])
            self._reload_all()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    # ════════════════════════════════════════════════════════════════════════
    #  REUNIONES
    # ════════════════════════════════════════════════════════════════════════

    def _render_reuniones(self) -> None:
        parent = self.col_lado
        hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        reuniones = sorted(self._reuniones, key=lambda r: _parse_fecha(r.get("fecha")) or datetime.max)
        proximas = [r for r in reuniones if (_parse_fecha(r.get("fecha")) or datetime.max) >= hoy]
        pasadas = [r for r in reuniones if r not in proximas]

        self._grupo_header(parent, "Reuniones", len(reuniones), theme.ACCENT)
        if not reuniones:
            ctk.CTkLabel(parent, text="Sin reuniones. Crea una con «+ Reunión».",
                         font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
                         anchor="w").pack(fill="x", pady=(0, theme.SPACE_2))
            return
        for r in proximas:
            self._render_reunion_card(parent, r)
        if pasadas:
            ctk.CTkLabel(parent, text=f"— {len(pasadas)} ya celebrada(s) —",
                         font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                         anchor="w").pack(fill="x", pady=(theme.SPACE_2, 2))
            for r in pasadas[-3:]:
                self._render_reunion_card(parent, r, pasada=True)

    def _render_reunion_card(self, parent, r: dict, pasada: bool = False) -> None:
        card = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=theme.RADIUS_MD,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x", pady=2)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_2, 2))
        ui.icon_button(row, "🗑", danger=True,
                       command=lambda: self._delete_reunion(r)).pack(side="right", padx=1)
        ui.icon_button(row, "✏",
                       command=lambda: ReunionEditor(self, reunion=r, on_save=self._reload_all)
                       ).pack(side="right", padx=1)
        ctk.CTkLabel(row, text=r.get("titulo", "(sin título)"), font=theme.font(13, "bold"),
                     text_color=theme.TEXT_MUTED if pasada else theme.TEXT_MAIN,
                     anchor="w").pack(side="left", fill="x", expand=True)

        if r.get("fecha"):
            d = _parse_fecha(r.get("fecha"))
            texto = d.strftime("%d-%m-%Y") if d else str(r.get("fecha"))
            color = theme.TEXT_MUTED
            if d and not pasada:
                dias = (d - datetime.now().replace(hour=0, minute=0, second=0,
                                                   microsecond=0)).days
                texto += " · hoy" if dias == 0 else (f" · en {dias} días" if dias <= 7 else "")
                color = theme.AMBER if dias <= 1 else theme.TEXT_SUB
            ctk.CTkLabel(card, text=f"📅  {texto}", font=theme.FONT_SMALL_BOLD,
                         text_color=color, anchor="w").pack(
                anchor="w", padx=theme.SPACE_3, pady=(0, 2))

        meta = []
        if r.get("ubicacion"):
            meta.append(f"📍 {r['ubicacion']}")
        if r.get("asistentes"):
            asist = r["asistentes"]
            if isinstance(asist, list):
                asist = ", ".join(asist)
            meta.append(f"👥 {asist if len(asist) <= 50 else asist[:50] + '…'}")
        desc = (r.get("descripcion") or "").strip()
        if desc:
            meta.append(desc if len(desc) <= 140 else desc[:140] + "…")
        if meta:
            ctk.CTkLabel(card, text="\n".join(meta), font=theme.FONT_SMALL,
                         text_color=theme.TEXT_MUTED, anchor="w", justify="left",
                         wraplength=430).pack(anchor="w", padx=theme.SPACE_3,
                                              pady=(0, theme.SPACE_2))

    def _delete_reunion(self, r: dict) -> None:
        if not messagebox.askyesno("Borrar reunión", f"¿Borrar '{r.get('titulo', '')}'?"):
            return
        try:
            agenda_service.delete("reuniones", r["id"])
            self._reload_all()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))


# ════════════════════════════════════════════════════════════════════════════
#  EDITORES (Toplevel)
# ════════════════════════════════════════════════════════════════════════════

class _BaseEditor(ctk.CTkToplevel):
    def __init__(self, master, title: str, width: int = 540, height: int = 540):
        super().__init__(master, fg_color=theme.BG_PAGE)
        self.title(title)
        self.geometry(f"{width}x{height}")
        self.minsize(420, 420)
        self.transient(master)
        self.grab_set()

    def _field(self, parent, label: str) -> ctk.CTkBaseClass:
        ctk.CTkLabel(
            parent, text=label, font=theme.font(10, "bold"),
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w", padx=20, pady=(8, 2))
        ent = ctk.CTkEntry(
            parent, height=34, corner_radius=8,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        ent.pack(fill="x", padx=20, pady=(0, 6))
        return ent

    def _textarea(self, parent, label: str, height: int = 90) -> ctk.CTkTextbox:
        ctk.CTkLabel(
            parent, text=label, font=theme.font(10, "bold"),
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(anchor="w", padx=20, pady=(8, 2))
        txt = ctk.CTkTextbox(
            parent, height=height, corner_radius=8,
            fg_color=theme.BG_INPUT, border_color=theme.BORDER, border_width=1,
            text_color=theme.TEXT_MAIN, font=theme.FONT_BODY,
        )
        txt.pack(fill="x", padx=20, pady=(0, 6))
        return txt

    def _footer(self, parent, on_save) -> None:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=20, pady=14, side="bottom")
        ui.button(f, "Cancelar", "secondary", command=self.destroy).pack(side="right", padx=(8, 0))
        ui.button(f, "Guardar", "primary", command=on_save).pack(side="right")


class TareaEditor(_BaseEditor):
    def __init__(self, master, tarea: dict | None = None, on_save=None):
        super().__init__(master, "Tarea — " + ("Editar" if tarea else "Nueva"), width=560, height=560)
        self._tarea = tarea
        self._on_save = on_save

        self.ent_titulo = self._field(self, "Título *")
        self.txt_desc = self._textarea(self, "Descripción", height=90)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(8, 4))

        ctk.CTkLabel(row, text="Prioridad", font=theme.font(10, "bold"),
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
        self.cmb_prio = ctk.CTkOptionMenu(
            row, values=["baja", "media", "alta"], width=140, height=34, corner_radius=8,
            fg_color=theme.BG_INPUT, button_color=theme.BG_INPUT,
            button_hover_color=theme.BG_CARD, text_color=theme.TEXT_MAIN,
            font=theme.FONT_BODY, dropdown_font=theme.FONT_BODY,
        )
        self.cmb_prio.pack(anchor="w", pady=(2, 0))

        self.ent_fecha = self._field(self, "Fecha límite (YYYY-MM-DD)")

        ctk.CTkLabel(self, text="Estado", font=theme.font(10, "bold"),
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w", padx=20, pady=(8, 2))
        self.cmb_estado = ctk.CTkOptionMenu(
            self, values=["pendiente", "en_progreso", "completada"], width=180, height=34, corner_radius=8,
            fg_color=theme.BG_INPUT, button_color=theme.BG_INPUT,
            button_hover_color=theme.BG_CARD, text_color=theme.TEXT_MAIN,
            font=theme.FONT_BODY, dropdown_font=theme.FONT_BODY,
        )
        self.cmb_estado.pack(anchor="w", padx=20)

        if tarea:
            self.ent_titulo.insert(0, tarea.get("titulo", ""))
            self.txt_desc.insert("1.0", tarea.get("descripcion", "") or "")
            self.cmb_prio.set(tarea.get("prioridad") or "media")
            self.ent_fecha.insert(0, tarea.get("fecha_limite", "") or "")
            self.cmb_estado.set(tarea.get("estado") or "pendiente")
        else:
            self.cmb_prio.set("media")
            self.cmb_estado.set("pendiente")

        self._footer(self, self._save)

    def _save(self) -> None:
        titulo = self.ent_titulo.get().strip()
        if not titulo:
            messagebox.showwarning("Título requerido", "El título no puede estar vacío.")
            return
        payload = {
            "titulo": titulo,
            "descripcion": self.txt_desc.get("1.0", "end").strip(),
            "prioridad": self.cmb_prio.get(),
            "fecha_limite": self.ent_fecha.get().strip(),
            "estado": self.cmb_estado.get(),
        }
        try:
            if self._tarea:
                agenda_service.update("tareas", self._tarea["id"], payload)
            else:
                agenda_service.create_tarea(DEFAULT_OWNER, payload)
        except Exception as exc:
            logger.exception("Error guardando tarea")
            messagebox.showerror("Error", str(exc))
            return
        if self._on_save:
            self._on_save()
        self.destroy()


class NotaEditor(_BaseEditor):
    def __init__(self, master, nota: dict | None = None, on_save=None):
        super().__init__(master, "Nota — " + ("Editar" if nota else "Nueva"), width=560, height=520)
        self._nota = nota
        self._on_save = on_save

        self.ent_titulo = self._field(self, "Título *")
        self.txt_contenido = self._textarea(self, "Contenido", height=200)

        ctk.CTkLabel(self, text="Color", font=theme.font(10, "bold"),
                     text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w", padx=20, pady=(8, 2))
        self.cmb_color = ctk.CTkOptionMenu(
            self, values=[label for _, _, label in NOTE_COLORS], width=180, height=34, corner_radius=8,
            fg_color=theme.BG_INPUT, button_color=theme.BG_INPUT,
            button_hover_color=theme.BG_CARD, text_color=theme.TEXT_MAIN,
            font=theme.FONT_BODY, dropdown_font=theme.FONT_BODY,
        )
        self.cmb_color.pack(anchor="w", padx=20)

        if nota:
            self.ent_titulo.insert(0, nota.get("titulo", ""))
            self.txt_contenido.insert("1.0", nota.get("contenido", "") or "")
            color_label = next((lab for k, _, lab in NOTE_COLORS if k == nota.get("color", "default")), "Default")
            self.cmb_color.set(color_label)
        else:
            self.cmb_color.set("Default")

        self._footer(self, self._save)

    def _save(self) -> None:
        titulo = self.ent_titulo.get().strip()
        if not titulo:
            messagebox.showwarning("Título requerido", "El título no puede estar vacío.")
            return
        color_label = self.cmb_color.get()
        color_key = next((k for k, _, lab in NOTE_COLORS if lab == color_label), "default")
        payload = {
            "titulo": titulo,
            "contenido": self.txt_contenido.get("1.0", "end").strip(),
            "color": color_key,
        }
        try:
            if self._nota:
                agenda_service.update("notas", self._nota["id"], payload)
            else:
                agenda_service.create("notas", payload)
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
            return
        if self._on_save:
            self._on_save()
        self.destroy()


class ReunionEditor(_BaseEditor):
    def __init__(self, master, reunion: dict | None = None, on_save=None):
        super().__init__(master, "Reunión — " + ("Editar" if reunion else "Nueva"), width=560, height=580)
        self._reunion = reunion
        self._on_save = on_save

        self.ent_titulo = self._field(self, "Título *")
        self.ent_fecha = self._field(self, "Fecha (YYYY-MM-DD HH:MM)")
        self.ent_ubicacion = self._field(self, "Ubicación")
        self.ent_asistentes = self._field(self, "Asistentes (separados por coma)")
        self.txt_desc = self._textarea(self, "Descripción", height=120)

        if reunion:
            self.ent_titulo.insert(0, reunion.get("titulo", ""))
            self.ent_fecha.insert(0, reunion.get("fecha", "") or "")
            self.ent_ubicacion.insert(0, reunion.get("ubicacion", "") or "")
            asist = reunion.get("asistentes", "")
            if isinstance(asist, list):
                asist = ", ".join(asist)
            self.ent_asistentes.insert(0, asist)
            self.txt_desc.insert("1.0", reunion.get("descripcion", "") or "")

        self._footer(self, self._save)

    def _save(self) -> None:
        titulo = self.ent_titulo.get().strip()
        if not titulo:
            messagebox.showwarning("Título requerido", "El título no puede estar vacío.")
            return
        asist_raw = self.ent_asistentes.get().strip()
        asist = [s.strip() for s in asist_raw.split(",") if s.strip()] if asist_raw else []
        payload = {
            "titulo": titulo,
            "fecha": self.ent_fecha.get().strip(),
            "ubicacion": self.ent_ubicacion.get().strip(),
            "asistentes": asist,
            "descripcion": self.txt_desc.get("1.0", "end").strip(),
        }
        try:
            if self._reunion:
                agenda_service.update("reuniones", self._reunion["id"], payload)
            else:
                agenda_service.create("reuniones", payload)
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
            return
        if self._on_save:
            self._on_save()
        self.destroy()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_fecha(fecha) -> datetime | None:
    """Texto de fecha → datetime. None si no se entiende.

    Las tareas se guardan en dd-mm-aaaa (así las escribe el editor y así las
    genera la sincronización), pero antes solo se probaba aaaa-mm-dd: ninguna
    fecha se interpretaba, así que nada salía como vencido y el orden por fecha
    no ordenaba nada. Se aceptan los dos.
    """
    txt = str(fecha or "").strip()[:10]
    if not txt:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(txt, fmt)
        except ValueError:
            continue
    return None


def _tarea_sort_key(t: dict):
    """Pendientes primero (vencidas arriba), luego completadas al final."""
    estado = t.get("estado", "pendiente")
    done = estado == "completada"
    d = _parse_fecha(t.get("fecha_limite")) or datetime.max
    prio_order = {"alta": 0, "media": 1, "baja": 2}.get(t.get("prioridad", "media"), 1)
    return (done, d, prio_order)


def _fecha_status(fecha: str, is_done: bool) -> tuple[str, str]:
    """Devuelve (label_legible, color) según proximidad de la fecha."""
    d = _parse_fecha(fecha)
    if d is None:
        return (str(fecha or ""), theme.TEXT_MUTED)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    diff = (d - today).days
    label = d.strftime("%d-%m-%Y")
    if is_done:
        return (label, theme.TEXT_MUTED)
    if diff < 0:
        return (f"{label}  ·  {-diff} d de retraso", theme.RED)
    if diff == 0:
        return (f"{label}  ·  hoy", theme.AMBER)
    if diff <= 7:
        return (f"{label}  ·  en {diff} d", theme.AMBER)
    return (label, theme.TEXT_SUB)
