"""Vista Agenda — Notas, Reuniones y Tareas en 3 tabs internos."""

import logging
import threading
from datetime import datetime

import customtkinter as ctk
from tkinter import messagebox

from core.services import agenda as agenda_service
from core.services import monitoring as monitoring_service
from gui import theme

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
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._tareas_filter = "todas"
        self._build_layout()
        self._reload_tareas()
        self._reload_notas()
        self._reload_reuniones()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_5, theme.SPACE_1))
        ctk.CTkLabel(
            header, text="Agenda", font=theme.FONT_TITLE,
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header, text=f"Notas, reuniones y tareas · owner {DEFAULT_OWNER}",
            font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w",
        ).pack(anchor="w", pady=(theme.SPACE_1, 0))

        # Tabs
        self.tabs = ctk.CTkTabview(
            self, fg_color=theme.BG_PAGE,
            segmented_button_fg_color=theme.BG_CARD,
            segmented_button_selected_color=theme.ACCENT,
            segmented_button_selected_hover_color=theme.ACCENT_HOVER,
            segmented_button_unselected_color=theme.BG_CARD,
            segmented_button_unselected_hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN,
        )
        self.tabs.pack(fill="both", expand=True,
                        padx=theme.SPACE_5, pady=(theme.SPACE_3, theme.SPACE_4))

        self.tab_tareas = self.tabs.add("Tareas")
        self.tab_notas = self.tabs.add("Notas")
        self.tab_reuniones = self.tabs.add("Reuniones")

        self._build_tareas_tab(self.tab_tareas)
        self._build_notas_tab(self.tab_notas)
        self._build_reuniones_tab(self.tab_reuniones)

    # ════════════════════════════════════════════════════════════════════════
    #  TAREAS
    # ════════════════════════════════════════════════════════════════════════

    def _build_tareas_tab(self, parent) -> None:
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", pady=(8, 8))

        ctk.CTkButton(
            toolbar, text="+ Nueva tarea", font=theme.FONT_BUTTON,
            height=34, corner_radius=8,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=lambda: TareaEditor(self, on_save=self._reload_tareas),
        ).pack(side="left")

        ctk.CTkButton(
            toolbar, text="↻ Sincronizar con Documentos", font=theme.FONT_BUTTON,
            height=34, corner_radius=8,
            fg_color=theme.BG_CARD, hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self._sync_tareas,
        ).pack(side="left", padx=(8, 0))

        ctk.CTkLabel(
            toolbar, text="Filtro:", font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        ).pack(side="left", padx=(16, 6))

        self.cmb_filter = ctk.CTkOptionMenu(
            toolbar, values=["Todas", "Pendientes", "En progreso", "Completadas"],
            width=140, height=34, corner_radius=8,
            fg_color=theme.BG_INPUT, button_color=theme.BG_INPUT,
            button_hover_color=theme.BG_CARD, text_color=theme.TEXT_MAIN,
            font=theme.FONT_BODY, dropdown_font=theme.FONT_BODY,
            command=lambda _: self._on_filter_tareas(),
        )
        self.cmb_filter.pack(side="left")

        self.lbl_tareas_count = ctk.CTkLabel(
            toolbar, text="", font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        )
        self.lbl_tareas_count.pack(side="right")

        self.tareas_scroll = ctk.CTkScrollableFrame(
            parent, fg_color="transparent",
        )
        self.tareas_scroll.pack(fill="both", expand=True, pady=(4, 0))

    def _on_filter_tareas(self) -> None:
        label = self.cmb_filter.get()
        self._tareas_filter = {
            "Pendientes": "pendiente",
            "En progreso": "en_progreso",
            "Completadas": "completada",
        }.get(label, "todas")
        self._render_tareas()

    def _reload_tareas(self) -> None:
        try:
            self._tareas = agenda_service.get_tareas(DEFAULT_OWNER)
        except Exception as exc:
            logger.exception("Error cargando tareas")
            messagebox.showerror("Error", str(exc))
            self._tareas = []
        self._render_tareas()

    def _render_tareas(self) -> None:
        for w in self.tareas_scroll.winfo_children():
            w.destroy()

        tareas = self._tareas
        if self._tareas_filter != "todas":
            tareas = [t for t in tareas if t.get("estado") == self._tareas_filter]

        tareas = sorted(tareas, key=_tarea_sort_key)

        self.lbl_tareas_count.configure(text=f"{len(tareas)} tareas")

        if not tareas:
            ctk.CTkLabel(
                self.tareas_scroll, text="Sin tareas en este filtro",
                font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
            ).pack(pady=30)
            return

        for t in tareas:
            self._render_tarea_card(t)

    def _render_tarea_card(self, t: dict) -> None:
        is_done = t.get("estado") == "completada"
        prio = (t.get("prioridad") or "media").lower()
        prio_color = PRIORITY_COLORS.get(prio, theme.TEXT_MUTED)

        card = ctk.CTkFrame(
            self.tareas_scroll, fg_color=theme.BG_CARD, corner_radius=8,
            border_width=0,
        )
        card.pack(fill="x", pady=2)

        # Línea principal (todo en una fila)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=6)

        # Checkbox compacto
        var_done = ctk.BooleanVar(value=is_done)
        ctk.CTkCheckBox(
            row, text="", variable=var_done, width=18, checkbox_width=16, checkbox_height=16,
            fg_color=theme.GREEN, hover_color=theme.GREEN, border_width=2,
            command=lambda: self._toggle_tarea_done(t, var_done.get()),
        ).pack(side="left", padx=(0, 8))

        # Dot de prioridad (en lugar de badge grande)
        ctk.CTkLabel(
            row, text="●", font=theme.font(14, "bold"),
            text_color=prio_color, width=14,
        ).pack(side="left", padx=(0, 6))

        # Título + (autogen) inline
        title_text = t.get("titulo", "(sin título)")
        if t.get("auto_generated"):
            title_text = f"⚙ {title_text}"
        ctk.CTkLabel(
            row, text=title_text,
            font=theme.font(12, "bold" if not is_done else "normal"),
            text_color=theme.TEXT_MUTED if is_done else theme.TEXT_MAIN,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        # Fecha límite compacta
        fecha = t.get("fecha_limite") or ""
        if fecha:
            d_label, d_color = _fecha_status(fecha, is_done)
            ctk.CTkLabel(
                row, text=d_label, font=theme.font(10),
                text_color=d_color,
            ).pack(side="left", padx=(8, 0))

        # Botones (más pequeños)
        ctk.CTkButton(
            row, text="🗑", width=24, height=22, corner_radius=4,
            fg_color="transparent", hover_color=theme.DELETE_HOVER,
            text_color=theme.TEXT_MUTED, font=theme.font(11),
            command=lambda: self._delete_tarea(t),
        ).pack(side="right", padx=1)
        ctk.CTkButton(
            row, text="✏", width=24, height=22, corner_radius=4,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MUTED, font=theme.font(11),
            command=lambda: TareaEditor(self, tarea=t, on_save=self._reload_tareas),
        ).pack(side="right", padx=1)

        # Descripción inline (truncada, solo si existe y no está completada)
        desc = (t.get("descripcion") or "").strip()
        if desc and not is_done:
            short = desc if len(desc) <= 140 else desc[:140] + "…"
            ctk.CTkLabel(
                card, text=short, font=theme.font(10),
                text_color=theme.TEXT_MUTED, anchor="w", justify="left",
                wraplength=900,
            ).pack(anchor="w", padx=(40, 10), pady=(0, 6))

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

    def _build_notas_tab(self, parent) -> None:
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", pady=(8, 8))

        ctk.CTkButton(
            toolbar, text="+ Nueva nota", font=theme.FONT_BUTTON,
            height=34, corner_radius=8,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=lambda: NotaEditor(self, on_save=self._reload_notas),
        ).pack(side="left")

        self.lbl_notas_count = ctk.CTkLabel(
            toolbar, text="", font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        )
        self.lbl_notas_count.pack(side="right")

        self.notas_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.notas_scroll.pack(fill="both", expand=True, pady=(4, 0))

    def _reload_notas(self) -> None:
        try:
            self._notas = agenda_service.get_all("notas")
        except Exception as exc:
            logger.exception("Error cargando notas")
            self._notas = []
        self._render_notas()

    def _render_notas(self) -> None:
        for w in self.notas_scroll.winfo_children():
            w.destroy()

        notas = sorted(self._notas, key=lambda n: n.get("updatedAt", ""), reverse=True)
        self.lbl_notas_count.configure(text=f"{len(notas)} notas")

        if not notas:
            ctk.CTkLabel(
                self.notas_scroll, text="Sin notas aún. Crea una con +Nueva nota.",
                font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
            ).pack(pady=30)
            return

        for n in notas:
            self._render_nota_card(n)

    def _render_nota_card(self, n: dict) -> None:
        color_key = n.get("color") or "default"
        bg = NOTE_COLOR_MAP.get(color_key, theme.BG_CARD)

        card = ctk.CTkFrame(
            self.notas_scroll, fg_color=bg, corner_radius=8,
            border_width=0,
        )
        card.pack(fill="x", pady=2)

        # Línea de título con acciones
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(6, 2))

        ctk.CTkLabel(
            row, text=n.get("titulo", "(sin título)"),
            font=theme.font(12, "bold"),
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            row, text="🗑", width=24, height=22, corner_radius=4,
            fg_color="transparent", hover_color=theme.DELETE_HOVER,
            text_color=theme.TEXT_MUTED, font=theme.font(11),
            command=lambda: self._delete_nota(n),
        ).pack(side="right", padx=1)
        ctk.CTkButton(
            row, text="✏", width=24, height=22, corner_radius=4,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MUTED, font=theme.font(11),
            command=lambda: NotaEditor(self, nota=n, on_save=self._reload_notas),
        ).pack(side="right", padx=1)

        # Contenido truncado en 2 líneas aprox
        contenido = (n.get("contenido") or "").strip()
        if contenido:
            short = contenido if len(contenido) <= 220 else contenido[:220] + "…"
            ctk.CTkLabel(
                card, text=short, font=theme.font(11),
                text_color=theme.TEXT_SUB, anchor="w", justify="left", wraplength=900,
            ).pack(anchor="w", padx=12, pady=(0, 6))

    def _delete_nota(self, n: dict) -> None:
        if not messagebox.askyesno("Borrar nota", f"¿Borrar '{n.get('titulo', '')}'?"):
            return
        try:
            agenda_service.delete("notas", n["id"])
            self._reload_notas()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    # ════════════════════════════════════════════════════════════════════════
    #  REUNIONES
    # ════════════════════════════════════════════════════════════════════════

    def _build_reuniones_tab(self, parent) -> None:
        toolbar = ctk.CTkFrame(parent, fg_color="transparent")
        toolbar.pack(fill="x", pady=(8, 8))

        ctk.CTkButton(
            toolbar, text="+ Nueva reunión", font=theme.FONT_BUTTON,
            height=34, corner_radius=8,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=lambda: ReunionEditor(self, on_save=self._reload_reuniones),
        ).pack(side="left")

        self.lbl_reuniones_count = ctk.CTkLabel(
            toolbar, text="", font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        )
        self.lbl_reuniones_count.pack(side="right")

        self.reuniones_scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.reuniones_scroll.pack(fill="both", expand=True, pady=(4, 0))

    def _reload_reuniones(self) -> None:
        try:
            self._reuniones = agenda_service.get_all("reuniones")
        except Exception as exc:
            logger.exception("Error cargando reuniones")
            self._reuniones = []
        self._render_reuniones()

    def _render_reuniones(self) -> None:
        for w in self.reuniones_scroll.winfo_children():
            w.destroy()

        reuniones = sorted(self._reuniones, key=lambda r: r.get("fecha", ""), reverse=False)
        self.lbl_reuniones_count.configure(text=f"{len(reuniones)} reuniones")

        if not reuniones:
            ctk.CTkLabel(
                self.reuniones_scroll, text="Sin reuniones aún.",
                font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
            ).pack(pady=30)
            return

        for r in reuniones:
            self._render_reunion_card(r)

    def _render_reunion_card(self, r: dict) -> None:
        card = ctk.CTkFrame(
            self.reuniones_scroll, fg_color=theme.BG_CARD, corner_radius=8,
            border_width=0,
        )
        card.pack(fill="x", pady=2)

        # Línea de título + meta + acciones
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(6, 2))

        ctk.CTkLabel(
            row, text=r.get("titulo", "(sin título)"),
            font=theme.font(12, "bold"),
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(side="left", fill="x", expand=True)

        ctk.CTkButton(
            row, text="🗑", width=24, height=22, corner_radius=4,
            fg_color="transparent", hover_color=theme.DELETE_HOVER,
            text_color=theme.TEXT_MUTED, font=theme.font(11),
            command=lambda: self._delete_reunion(r),
        ).pack(side="right", padx=1)
        ctk.CTkButton(
            row, text="✏", width=24, height=22, corner_radius=4,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MUTED, font=theme.font(11),
            command=lambda: ReunionEditor(self, reunion=r, on_save=self._reload_reuniones),
        ).pack(side="right", padx=1)

        # Meta inline (fecha + lugar + asistentes en una sola línea compacta)
        meta_parts = []
        if r.get("fecha"):
            meta_parts.append(f"📅 {r.get('fecha', '')}")
        if r.get("ubicacion"):
            meta_parts.append(f"📍 {r.get('ubicacion', '')}")
        if r.get("asistentes"):
            asist = r["asistentes"]
            if isinstance(asist, list):
                asist = ", ".join(asist)
            asist_short = asist if len(asist) <= 50 else asist[:50] + "…"
            meta_parts.append(f"👥 {asist_short}")
        if meta_parts:
            ctk.CTkLabel(
                card, text="   ·   ".join(meta_parts),
                font=theme.font(10),
                text_color=theme.TEXT_SUB, anchor="w",
            ).pack(anchor="w", padx=12, pady=(0, 2))

        desc = (r.get("descripcion") or "").strip()
        if desc:
            short = desc if len(desc) <= 180 else desc[:180] + "…"
            ctk.CTkLabel(
                card, text=short, font=theme.font(10),
                text_color=theme.TEXT_MUTED, anchor="w", justify="left", wraplength=900,
            ).pack(anchor="w", padx=12, pady=(0, 6))

    def _delete_reunion(self, r: dict) -> None:
        if not messagebox.askyesno("Borrar reunión", f"¿Borrar '{r.get('titulo', '')}'?"):
            return
        try:
            agenda_service.delete("reuniones", r["id"])
            self._reload_reuniones()
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
        ctk.CTkButton(
            f, text="Cancelar", font=theme.FONT_BUTTON,
            height=34, corner_radius=8,
            fg_color=theme.BG_CARD, hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MAIN, border_width=1, border_color=theme.BORDER,
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            f, text="Guardar", font=theme.FONT_BUTTON,
            height=34, corner_radius=8,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=on_save,
        ).pack(side="right")


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

def _tarea_sort_key(t: dict):
    """Pendientes primero (vencidas arriba), luego completadas al final."""
    estado = t.get("estado", "pendiente")
    done = estado == "completada"
    fecha = t.get("fecha_limite") or ""
    try:
        d = datetime.strptime(fecha[:10], "%Y-%m-%d") if fecha else datetime.max
    except ValueError:
        d = datetime.max
    prio_order = {"alta": 0, "media": 1, "baja": 2}.get(t.get("prioridad", "media"), 1)
    return (done, d, prio_order)


def _fecha_status(fecha: str, is_done: bool) -> tuple[str, str]:
    """Devuelve (label_legible, color) según proximidad de la fecha."""
    try:
        d = datetime.strptime(fecha[:10], "%Y-%m-%d")
    except ValueError:
        return (fecha, theme.TEXT_MUTED)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    diff = (d - today).days
    label = d.strftime("%d %b %Y")
    if is_done:
        return (label, theme.TEXT_MUTED)
    if diff < 0:
        return (f"{label} (vencida hace {-diff} días)", theme.RED)
    if diff == 0:
        return (f"{label} (hoy)", theme.AMBER)
    if diff <= 3:
        return (f"{label} (en {diff} días)", theme.AMBER)
    return (label, theme.TEXT_SUB)
