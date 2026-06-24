"""Vista Apertura de pedidos — formulario + creación automática de carpetas, Planning y VDDL."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

import re

from core.services import apertura as apertura_service
from core.services import comm_matrix as comm_matrix_service
from gui import theme
from gui.widgets.scrollframe import ScrollFrame


# Email parser tolerante: coma, punto y coma, espacio, salto de línea
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _split_emails(text: str) -> list[str]:
    """Extrae emails únicos de un texto (preserva orden de aparición)."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for em in _EMAIL_RE.findall(text):
        k = em.lower()
        if k not in seen:
            seen.add(k)
            out.append(em)
    return out

logger = logging.getLogger(__name__)


def _open_in_explorer(path: Path) -> None:
    """Abre la ruta en el explorador de archivos del sistema."""
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif os.name == "posix":
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        logger.warning("No se pudo abrir %s: %s", path, exc)


def _today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _today_plus_iso(days: int) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def _parse_iso(s: str) -> datetime:
    return datetime.strptime(s.strip(), "%Y-%m-%d")


def _year_from_pedido(raw: str) -> int | None:
    """Deduce el año del código del pedido: 'P-26-009' → 2026."""
    m = apertura_service._PEDIDO_FLEX_RE.match((raw or "").strip())
    return 2000 + int(m.group(1)) if m else None


class AperturaView(ctk.CTkFrame):
    """Formulario para abrir un pedido nuevo."""

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG_PAGE, **kwargs)
        self._busy = False
        self._last_result: apertura_service.OrderResult | None = None
        self._build_layout()

    # ── Layout ─────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_6, pady=(theme.SPACE_5, theme.SPACE_1))
        ctk.CTkLabel(
            header, text="Apertura de pedidos", font=theme.FONT_TITLE,
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Genera carpetas, copia plantilla 00 DOCUMENTACIÓN, Planning y VDDL automáticamente.",
            font=theme.FONT_SUBTITLE, text_color=theme.TEXT_SUB, anchor="w",
        ).pack(anchor="w", pady=(theme.SPACE_1, 0))

        # Wrapper scrollable
        wrapper = ScrollFrame(self)
        wrapper.pack(fill="both", expand=True,
                     padx=theme.SPACE_5, pady=(theme.SPACE_3, theme.SPACE_4))

        # ─── Card: Datos del pedido ───────────────────────────────────────
        card = self._card(wrapper, "Datos del pedido")

        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=theme.SPACE_4, pady=(0, theme.SPACE_3))
        for c in range(4):
            grid.grid_columnconfigure(c, weight=1, uniform="apertura")

        # Fila 0
        self.var_pedido = ctk.StringVar(value="P-26-")
        self._field(grid, "Pedido (P-XX-XXX) *", self.var_pedido, row=0, col=0,
                    placeholder="P-26-009")

        self.var_suffix = ctk.StringVar(value="S00")
        self._field(grid, "Revisión", self.var_suffix, row=0, col=1,
                    placeholder="S00")

        self.var_sref = ctk.StringVar()
        self._field(grid, "S.REF (PO cliente)", self.var_sref, row=0, col=2, colspan=2,
                    placeholder="1078010640  ·  el año se deduce del código (P-26-… → 2026)")

        # Fila 1 (cliente + material a 2 cols — opcionales, se auto-rellenan)
        self.var_cliente = ctk.StringVar()
        self._field(grid, "Cliente (auto)", self.var_cliente, row=1, col=0, colspan=2,
                    placeholder="se rellena al localizar el pedido")

        self.var_material = ctk.StringVar()
        self._field(grid, "Material (auto)", self.var_material, row=1, col=2, colspan=2,
                    placeholder="se rellena al localizar el pedido")

        # Fila 2 — fechas
        self.var_f_entrada = ctk.StringVar(value=_today_iso())
        self._field(grid, "Fecha entrada (YYYY-MM-DD) *", self.var_f_entrada,
                    row=2, col=0, colspan=2, placeholder="2026-05-28")

        self.var_f_prevista = ctk.StringVar(value=_today_plus_iso(180))
        self._field(grid, "Fecha prevista entrega *", self.var_f_prevista,
                    row=2, col=2, colspan=2, placeholder="2026-11-28")

        # ─── Botonera (Localizar / Procesar) — justo encima de Resultado ──
        btn_row = ctk.CTkFrame(wrapper, fg_color="transparent")
        btn_row.pack(fill="x", padx=theme.SPACE_4, pady=(theme.SPACE_2, theme.SPACE_2))

        self.btn_locate = ctk.CTkButton(
            btn_row, text="🔍  Localizar pedido", command=self._on_locate,
            **theme.button_kwargs("secondary"),
        )
        self.btn_locate.pack(side="left", padx=(0, theme.SPACE_2))

        self.btn_create = ctk.CTkButton(
            btn_row, text="✦  Procesar pedido", command=self._on_create,
            **theme.button_kwargs("primary"),
        )
        self.btn_create.pack(side="left", padx=(0, theme.SPACE_2))

        ctk.CTkButton(
            btn_row, text="Limpiar formulario", command=self._on_clear,
            **theme.button_kwargs("ghost"),
        ).pack(side="left", padx=(0, theme.SPACE_2))

        self.btn_open = ctk.CTkButton(
            btn_row, text="Abrir carpeta del pedido", command=self._on_open,
            state="disabled",
            **theme.button_kwargs("secondary"),
        )
        self.btn_open.pack(side="left")

        # ─── Resultado / log ──────────────────────────────────────────────
        result_card = self._card(wrapper, "Resultado")
        self.txt_result = ctk.CTkTextbox(
            result_card, height=160, font=theme.FONT_MONO,
            fg_color=theme.BG_INPUT, text_color=theme.TEXT_MAIN,
            border_width=1, border_color=theme.BORDER, corner_radius=theme.RADIUS_MD,
        )
        self.txt_result.pack(fill="both", expand=True,
                             padx=theme.SPACE_4, pady=(0, theme.SPACE_4))
        self.txt_result.insert("1.0",
            "1) Mete el código del pedido (p.ej. P-26-050) y pulsa «Localizar pedido»\n"
            "   para verificar que existe la carpeta y que se rellenan Cliente/Material.\n"
            "2) Pulsa «Procesar pedido» para crear «00 DOCUMENTACIÓN» dentro de\n"
            "   «2-Tecnico», copiar la plantilla, generar Planning y VDDL.")
        self.txt_result.configure(state="disabled")

        # ─── Card: Acciones a ejecutar ────────────────────────────────────
        actions = self._card(wrapper, "Acciones a ejecutar")

        self.var_copy_template = ctk.BooleanVar(value=True)
        self.var_do_planning = ctk.BooleanVar(value=True)
        self.var_do_vddl = ctk.BooleanVar(value=True)
        self.var_overwrite = ctk.BooleanVar(value=False)

        ck_box = ctk.CTkFrame(actions, fg_color="transparent")
        ck_box.pack(fill="x", padx=theme.SPACE_4, pady=(0, theme.SPACE_3))

        self._checkbox(ck_box, "Copiar plantilla 00 DOCUMENTACIÓN", self.var_copy_template)
        self._checkbox(ck_box, "Generar Planning (PLAN ING + GRAF ING)", self.var_do_planning)
        self._checkbox(ck_box, "Generar VDDL inicial", self.var_do_vddl)
        self._checkbox(ck_box, "Sobrescribir archivos existentes en la plantilla",
                       self.var_overwrite)

        self.var_create_if_missing = ctk.BooleanVar(value=False)
        self._checkbox(ck_box,
                       "Crear carpeta del pedido si no existe (requiere Cliente y Material)",
                       self.var_create_if_missing)

        self.var_do_subfolders = ctk.BooleanVar(value=True)
        self._checkbox(ck_box, "Crear subcarpetas env. * en 2-Tecnico (selección abajo)",
                       self.var_do_subfolders)

        self.var_do_comm_matrix = ctk.BooleanVar(value=True)
        self._checkbox(ck_box, "Guardar Communication Matrix (TO/CC para reclamaciones)",
                       self.var_do_comm_matrix)

        # ─── Card: Subcarpetas env. * + idioma VDDL ───────────────────────
        sub_card = self._card(
            wrapper,
            "Subcarpetas de 2-Tecnico  ·  estas mismas serán las filas del VDDL",
        )

        # Selector idioma + atajos
        top_bar = ctk.CTkFrame(sub_card, fg_color="transparent")
        top_bar.pack(fill="x", padx=theme.SPACE_4, pady=(0, theme.SPACE_2))

        ctk.CTkLabel(
            top_bar, text="Idioma del VDDL:", font=theme.FONT_SMALL_BOLD,
            text_color=theme.TEXT_SUB,
        ).pack(side="left", padx=(0, theme.SPACE_2))

        self.var_vddl_lang = ctk.StringVar(value="es")
        for code, label in [("es", "Español"), ("en", "English")]:
            ctk.CTkRadioButton(
                top_bar, text=label, variable=self.var_vddl_lang, value=code,
                font=theme.FONT_BODY, text_color=theme.TEXT_MAIN,
                fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                border_color=theme.BORDER_STRONG,
                command=self._refresh_subfolder_labels,
            ).pack(side="left", padx=(0, theme.SPACE_3))

        # Spacer + botones Todas / Ninguna
        ctk.CTkButton(
            top_bar, text="Todas", width=70,
            command=lambda: self._set_all_subfolders(True),
            **theme.button_kwargs("ghost"),
        ).pack(side="right", padx=(theme.SPACE_1, 0))
        ctk.CTkButton(
            top_bar, text="Ninguna", width=70,
            command=lambda: self._set_all_subfolders(False),
            **theme.button_kwargs("ghost"),
        ).pack(side="right", padx=(theme.SPACE_1, 0))

        # Grid de checkboxes (3 columnas × ~8 filas)
        ck_grid = ctk.CTkFrame(sub_card, fg_color="transparent")
        ck_grid.pack(fill="x", padx=theme.SPACE_4, pady=(0, theme.SPACE_3))
        for c in range(3):
            ck_grid.grid_columnconfigure(c, weight=1, uniform="subf")

        self.var_subfolders: dict[str, ctk.BooleanVar] = {}
        self._subfolder_checkboxes: dict[str, ctk.CTkCheckBox] = {}

        entries = apertura_service.SUBFOLDER_CATALOG
        ncols = 3
        for i, entry in enumerate(entries):
            r = i // ncols
            c = i % ncols
            folder = entry["folder"]
            var = ctk.BooleanVar(value=True)
            ck = ctk.CTkCheckBox(
                ck_grid, text=self._subfolder_label(entry, "es"),
                variable=var,
                font=theme.FONT_BODY, text_color=theme.TEXT_MAIN,
                fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                border_color=theme.BORDER_STRONG,
                checkbox_width=18, checkbox_height=18,
            )
            ck.grid(row=r, column=c, sticky="w",
                    padx=theme.SPACE_1, pady=2)
            self.var_subfolders[folder] = var
            self._subfolder_checkboxes[folder] = ck

        # ─── Card: Communication Matrix (reclamaciones) ──────────────────
        cm_card = self._card(
            wrapper,
            "Communication Matrix  ·  destinatarios para reclamaciones",
        )
        ctk.CTkLabel(
            cm_card,
            text=(
                "Estos emails se guardan asociados al pedido y se usarán de forma "
                "canónica cuando envíes reclamaciones desde la sección Reclamaciones.\n"
                "Acepta separadores: coma, punto y coma, espacio o salto de línea."
            ),
            font=theme.FONT_SMALL, text_color=theme.TEXT_SUB, justify="left",
            anchor="w", wraplength=900,
        ).pack(anchor="w", fill="x", padx=theme.SPACE_4, pady=(0, theme.SPACE_2))

        cm_grid = ctk.CTkFrame(cm_card, fg_color="transparent")
        cm_grid.pack(fill="x", padx=theme.SPACE_4, pady=(0, theme.SPACE_2))
        cm_grid.grid_columnconfigure(0, weight=1, uniform="cm")
        cm_grid.grid_columnconfigure(1, weight=1, uniform="cm")

        # TO
        to_box = ctk.CTkFrame(cm_grid, fg_color="transparent")
        to_box.grid(row=0, column=0, sticky="ew", padx=(0, theme.SPACE_2))
        ctk.CTkLabel(
            to_box, text="TO:", font=theme.FONT_LABEL,
            text_color=theme.TEXT_SUB, anchor="w",
        ).pack(fill="x")
        self.txt_cm_to = ctk.CTkTextbox(
            to_box, height=80, font=theme.FONT_MONO,
            fg_color=theme.BG_INPUT, text_color=theme.TEXT_MAIN,
            border_color=theme.BORDER, border_width=1,
            corner_radius=theme.RADIUS_SM,
        )
        self.txt_cm_to.pack(fill="x", pady=(2, 0))

        # CC
        cc_box = ctk.CTkFrame(cm_grid, fg_color="transparent")
        cc_box.grid(row=0, column=1, sticky="ew", padx=(theme.SPACE_2, 0))
        ctk.CTkLabel(
            cc_box, text="CC:", font=theme.FONT_LABEL,
            text_color=theme.TEXT_SUB, anchor="w",
        ).pack(fill="x")
        self.txt_cm_cc = ctk.CTkTextbox(
            cc_box, height=80, font=theme.FONT_MONO,
            fg_color=theme.BG_INPUT, text_color=theme.TEXT_MAIN,
            border_color=theme.BORDER, border_width=1,
            corner_radius=theme.RADIUS_SM,
        )
        self.txt_cm_cc.pack(fill="x", pady=(2, 0))

        # Estado actual (live counter)
        self.lbl_cm_status = ctk.CTkLabel(
            cm_card, text="—  ningún email detectado",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w",
        )
        self.lbl_cm_status.pack(anchor="w", padx=theme.SPACE_4,
                                pady=(0, theme.SPACE_3))

        # Live update del contador al editar
        self.txt_cm_to.bind("<KeyRelease>", lambda _e: self._refresh_cm_status())
        self.txt_cm_cc.bind("<KeyRelease>", lambda _e: self._refresh_cm_status())

        # ─── Rutas (se configuran en Ajustes ▸ Fuentes de datos) ──────────
        # Sin UI aquí: las rutas se editan/persisten en Ajustes; aquí solo se
        # leen para localizar y procesar el pedido.
        from core import preferences as _pref
        self.var_base_dir = ctk.StringVar(
            value=str(_pref.get("apertura_base_dir") or apertura_service.DEFAULT_BASE_DIR))
        self.var_template_dir = ctk.StringVar(
            value=str(_pref.get("apertura_template_dir") or apertura_service.DEFAULT_TEMPLATE_DIR))
        self.var_planning_tpl = ctk.StringVar(
            value=str(_pref.get("apertura_planning_tpl") or apertura_service.DEFAULT_PLANNING_TEMPLATE))
        self.var_erp_tpl = ctk.StringVar(
            value=str(_pref.get("apertura_erp_tpl") or apertura_service.DEFAULT_ERP_TEMPLATE))

    # ── Helpers de UI ──────────────────────────────────────────────────────

    def _card(self, parent, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent, fg_color=theme.BG_CARD,
            border_color=theme.BORDER, border_width=1,
            corner_radius=theme.RADIUS_LG,
        )
        card.pack(fill="x", padx=theme.SPACE_4, pady=(theme.SPACE_2, theme.SPACE_3))
        ctk.CTkLabel(
            card, text=title, font=theme.FONT_SECTION,
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w", padx=theme.SPACE_4, pady=(theme.SPACE_3, theme.SPACE_2))
        return card

    def _field(self, parent, label: str, var: ctk.StringVar, *,
               row: int, col: int, colspan: int = 1,
               placeholder: str = "") -> ctk.CTkEntry:
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=col, columnspan=colspan, sticky="ew",
                 padx=theme.SPACE_1, pady=theme.SPACE_1)
        ctk.CTkLabel(
            box, text=label, font=theme.FONT_LABEL,
            text_color=theme.TEXT_SUB, anchor="w",
        ).pack(fill="x")
        entry = ctk.CTkEntry(
            box, textvariable=var, placeholder_text=placeholder,
            height=theme.HEIGHT_INPUT, font=theme.FONT_BODY,
            fg_color=theme.BG_INPUT, text_color=theme.TEXT_MAIN,
            border_color=theme.BORDER, border_width=1,
            corner_radius=theme.RADIUS_SM,
        )
        entry.pack(fill="x", pady=(2, 0))
        return entry

    def _checkbox(self, parent, label: str, var: ctk.BooleanVar) -> None:
        ck = ctk.CTkCheckBox(
            parent, text=label, variable=var,
            font=theme.FONT_BODY,
            text_color=theme.TEXT_MAIN,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            border_color=theme.BORDER_STRONG,
        )
        ck.pack(anchor="w", pady=2)

    # ── Helpers subcarpetas ────────────────────────────────────────────────

    @staticmethod
    def _subfolder_label(entry: dict, lang: str) -> str:
        """'env. Cálculos  →  Cálculos' (ES) o '→ Calculations' (EN)."""
        title = entry.get("en") if lang == "en" else entry.get("es")
        title = title or entry["folder"]
        return f"{entry['folder']}  →  {title}"

    def _refresh_subfolder_labels(self) -> None:
        """Re-renderiza los textos de los checkboxes al cambiar idioma."""
        lang = self.var_vddl_lang.get()
        for entry in apertura_service.SUBFOLDER_CATALOG:
            ck = self._subfolder_checkboxes.get(entry["folder"])
            if ck is not None:
                ck.configure(text=self._subfolder_label(entry, lang))

    def _set_all_subfolders(self, value: bool) -> None:
        for var in self.var_subfolders.values():
            var.set(value)

    def _selected_subfolders(self) -> list[str]:
        return [f for f, v in self.var_subfolders.items() if v.get()]

    # ── Helpers Communication Matrix ───────────────────────────────────────

    def _refresh_cm_status(self) -> None:
        """Actualiza el contador 'N TO · M CC detectados'."""
        tos = _split_emails(self.txt_cm_to.get("1.0", "end"))
        ccs = _split_emails(self.txt_cm_cc.get("1.0", "end"))
        if not tos and not ccs:
            self.lbl_cm_status.configure(
                text="—  ningún email detectado", text_color=theme.TEXT_MUTED,
            )
        else:
            self.lbl_cm_status.configure(
                text=f"✓  {len(tos)} TO  ·  {len(ccs)} CC  detectados (únicos)",
                text_color=theme.GREEN,
            )

    def _set_cm_textboxes(self, to: list[str], cc: list[str]) -> None:
        self.txt_cm_to.delete("1.0", "end")
        if to:
            self.txt_cm_to.insert("1.0", ", ".join(to))
        self.txt_cm_cc.delete("1.0", "end")
        if cc:
            self.txt_cm_cc.insert("1.0", ", ".join(cc))
        self._refresh_cm_status()

    def _try_load_matrix_for(self, n_ref_short: str) -> dict | None:
        """Pide a comm_matrix los contactos del pedido (ya en formato P-XX/YYY)."""
        try:
            return comm_matrix_service.get_contacts(n_ref_short)
        except Exception:
            logger.exception("Fallo leyendo comm_matrix para %s", n_ref_short)
            return None

    # ── Acciones ───────────────────────────────────────────────────────────

    def _on_clear(self) -> None:
        self.var_pedido.set("P-26-")
        self.var_suffix.set("S00")
        self.var_sref.set("")
        self.var_cliente.set("")
        self.var_material.set("")
        self.var_f_entrada.set(_today_iso())
        self.var_f_prevista.set(_today_plus_iso(180))
        self._set_cm_textboxes([], [])
        self._last_result = None
        self.btn_open.configure(state="disabled")
        self._set_result_text("Formulario limpiado.")

    def _on_open(self) -> None:
        if self._last_result is None:
            return
        _open_in_explorer(self._last_result.pedido_dir)

    # ── Localizar carpeta existente ───────────────────────────────────────

    def _on_locate(self) -> None:
        """Busca la carpeta del pedido y rellena Cliente/Material auto."""
        pedido_raw = self.var_pedido.get().strip()
        try:
            folder_id, suf = apertura_service.parse_pedido(pedido_raw)
        except ValueError as exc:
            messagebox.showerror("Pedido inválido", str(exc), parent=self)
            return
        # El año va implícito en el código del pedido (P-26-… → 2026)
        año = _year_from_pedido(pedido_raw) or datetime.now().year

        base_raw = self.var_base_dir.get().strip() or str(apertura_service.DEFAULT_BASE_DIR)
        from pathlib import Path as _P
        base = _P(base_raw)

        if not base.exists():
            self._set_result_text(
                f"❌ La base de pedidos no existe:\n   {base}\n"
                "Comprueba que la unidad M:\\ está conectada."
            )
            return

        pedido_dir = apertura_service.find_existing_pedido_dir(folder_id, año, base_dir=base)
        if pedido_dir is None:
            self._set_result_text(
                f"❌ No se encontró carpeta para {folder_id} en\n"
                f"   {base / f'Año {año}' / f'{año} Pedidos'}\n\n"
                "Opciones:\n"
                "  • Verifica que el pedido esté creado en disco.\n"
                "  • Activa «Crear carpeta del pedido si no existe» y rellena "
                "Cliente y Material."
            )
            return

        meta = apertura_service.parse_folder_meta(pedido_dir.name) or {}
        if meta.get("cliente"):
            self.var_cliente.set(meta["cliente"])
        if meta.get("material"):
            self.var_material.set(meta["material"])
        if meta.get("suffix"):
            self.var_suffix.set(meta["suffix"])

        tecnico = apertura_service.find_tecnico_dir(pedido_dir)
        tecnico_msg = (
            f"   ✅ {tecnico.name}" if tecnico
            else "   ⚠ no existe — se creará «2-Tecnico» al procesar"
        )

        # Pre-cargar Communication Matrix si ya hay datos guardados
        # Key en matrix = "P-XX/YYY" (sin sufijo S00)
        m = apertura_service._PEDIDO_FOLDER_RE.match(folder_id)
        n_ref_short = f"P-{m.group(1)}/{m.group(2)}" if m else folder_id
        existing = self._try_load_matrix_for(n_ref_short)
        if existing:
            self._set_cm_textboxes(existing.get("to") or [], existing.get("cc") or [])
            cm_msg = (
                f"   📒 Communication Matrix encontrada: "
                f"{len(existing.get('to') or [])} TO · "
                f"{len(existing.get('cc') or [])} CC (cargados)"
            )
        else:
            cm_msg = (
                "   📒 Communication Matrix: vacía — añade TO/CC y se guardará al procesar"
            )

        self._set_result_text(
            f"✅ Pedido localizado.\n\n"
            f"📁 {pedido_dir}\n\n"
            f"   Cliente:  {meta.get('cliente', '—')}\n"
            f"   Material: {meta.get('material', '—')}\n"
            f"   Revisión: {meta.get('suffix', '—')}\n\n"
            f"Subcarpeta técnica:\n{tecnico_msg}\n\n"
            f"{cm_msg}\n\n"
            "Pulsa «Procesar pedido» para crear 00 DOCUMENTACIÓN dentro y\n"
            "copiar plantilla + Planning + VDDL."
        )

    # ── Procesar pedido ────────────────────────────────────────────────────

    def _on_create(self) -> None:
        if self._busy:
            return
        from core import session
        from gui.widgets import ui
        if not session.can_manage("apertura"):
            ui.toast(self, "Solo lectura", "No tienes permiso para procesar pedidos.", kind="warn")
            return

        # ── Validaciones ────────────────────────────────────────────────
        try:
            pedido = self.var_pedido.get().strip().upper()
            suffix = (self.var_suffix.get().strip() or "S00").upper()
            sref = self.var_sref.get().strip()
            cliente = self.var_cliente.get().strip()
            material = self.var_material.get().strip()
            # El año se deduce del código del pedido (P-26-… → 2026)
            año = _year_from_pedido(pedido)
            f_entrada = _parse_iso(self.var_f_entrada.get())
            f_prevista = _parse_iso(self.var_f_prevista.get())
            create_if_missing = bool(self.var_create_if_missing.get())
        except ValueError as exc:
            messagebox.showerror(
                "Datos inválidos",
                f"Revisa los campos.\n\nDetalle: {exc}\n\n"
                "Las fechas deben tener formato YYYY-MM-DD.",
                parent=self,
            )
            return

        if not pedido:
            messagebox.showerror(
                "Pedido obligatorio",
                "Introduce un código de pedido (p.ej. P-26-050).",
                parent=self,
            )
            return

        if create_if_missing and (not cliente or not material):
            messagebox.showerror(
                "Datos incompletos",
                "Para «Crear carpeta del pedido si no existe» necesitas "
                "Cliente y Material.\n\nAlternativa: desactiva esa opción y pulsa "
                "«Localizar pedido» primero.",
                parent=self,
            )
            return

        # Confirmación
        if cliente or material:
            folder_preview = f"{pedido} - {cliente or '?'} - {material or '?'}"
        else:
            folder_preview = f"{pedido} (carpeta se localizará automáticamente)"
        n_subs = len(self._selected_subfolders())
        lang_label = {"es": "Español", "en": "English"}.get(
            self.var_vddl_lang.get(), self.var_vddl_lang.get()
        )
        # Parse contactos para la confirmación + guardado posterior
        cm_to = _split_emails(self.txt_cm_to.get("1.0", "end"))
        cm_cc = _split_emails(self.txt_cm_cc.get("1.0", "end"))
        do_cm = bool(self.var_do_comm_matrix.get()) and (cm_to or cm_cc)

        if not messagebox.askyesno(
            "Confirmar procesamiento",
            "Se va a procesar el siguiente pedido:\n\n"
            f"  📁 {folder_preview}\n"
            f"  📅 {f_entrada:%Y-%m-%d} → {f_prevista:%Y-%m-%d}\n\n"
            "Acciones:\n"
            f"  • Localizar + crear 00 DOCUMENTACIÓN\n"
            f"  • Copia plantilla: {'sí' if self.var_copy_template.get() else 'no'}\n"
            f"  • Planning: {'sí' if self.var_do_planning.get() else 'no'}\n"
            f"  • Subcarpetas en 2-Tecnico: "
            f"{f'{n_subs} marcadas' if self.var_do_subfolders.get() else 'no'}\n"
            f"  • VDDL ({lang_label}): "
            f"{f'sí — {n_subs} filas' if self.var_do_vddl.get() else 'no'}\n"
            f"  • Communication Matrix: "
            f"{f'sí — {len(cm_to)} TO · {len(cm_cc)} CC' if do_cm else 'no'}\n"
            f"  • Crear carpeta si no existe: {'sí' if create_if_missing else 'no'}\n\n"
            "¿Continuar?",
            parent=self,
        ):
            return

        self._busy = True
        self.btn_create.configure(state="disabled", text="Procesando…")
        self._set_result_text(f"⏳ Procesando pedido {pedido}…")

        kwargs = dict(
            pedido=pedido,
            cliente=cliente,
            material=material,
            fecha_entrada=f_entrada,
            fecha_prevista=f_prevista,
            sref=sref,
            año=año,
            suffix=suffix,
            base_dir=self.var_base_dir.get().strip() or apertura_service.DEFAULT_BASE_DIR,
            template_dir=self.var_template_dir.get().strip() or apertura_service.DEFAULT_TEMPLATE_DIR,
            planning_template=self.var_planning_tpl.get().strip() or apertura_service.DEFAULT_PLANNING_TEMPLATE,
            erp_template=self.var_erp_tpl.get().strip() or apertura_service.DEFAULT_ERP_TEMPLATE,
            copy_template=self.var_copy_template.get(),
            do_planning=self.var_do_planning.get(),
            do_vddl=self.var_do_vddl.get(),
            do_subfolders=self.var_do_subfolders.get(),
            overwrite_template=self.var_overwrite.get(),
            create_if_missing=create_if_missing,
            subfolders=self._selected_subfolders(),
            vddl_lang=self.var_vddl_lang.get(),
        )

        cm_payload = {
            "enabled": do_cm,
            "to": cm_to,
            "cc": cm_cc,
        }

        thread = threading.Thread(
            target=self._run_create, args=(kwargs, cm_payload), daemon=True,
        )
        thread.start()

    def _run_create(self, kwargs: dict, cm_payload: dict) -> None:
        try:
            result = apertura_service.create_order(**kwargs)
            cm_saved = None
            cm_error = None
            if cm_payload.get("enabled"):
                try:
                    # Usar n_ref_short ("P-XX/YYY") como key — formato matrix
                    # spec ya validó el pedido; reusamos parse para extraer
                    pedido = kwargs["pedido"]
                    folder_id, _ = apertura_service.parse_pedido(pedido)
                    m = apertura_service._PEDIDO_FOLDER_RE.match(folder_id)
                    if m:
                        n_ref_short = f"P-{m.group(1)}/{m.group(2)}"
                    else:
                        n_ref_short = folder_id
                    comm_matrix_service.set_contacts(
                        n_ref_short, cm_payload["to"], cm_payload["cc"],
                    )
                    cm_saved = {
                        "key": n_ref_short,
                        "to": cm_payload["to"],
                        "cc": cm_payload["cc"],
                    }
                except Exception as exc:
                    logger.exception("Fallo guardando Communication Matrix")
                    cm_error = str(exc)
            self.after(
                0,
                lambda r=result, s=cm_saved, ce=cm_error:
                    self._on_create_done(r, None, s, ce),
            )
        except Exception as exc:
            logger.exception("Error creando pedido")
            err = exc  # bind antes de salir del except (Python borra `exc`)
            self.after(
                0,
                lambda e=err: self._on_create_done(None, e, None, None),
            )

    def _on_create_done(
        self,
        result: apertura_service.OrderResult | None,
        error: Exception | None,
        cm_saved: dict | None = None,
        cm_error: str | None = None,
    ) -> None:
        self._busy = False
        self.btn_create.configure(state="normal", text="✦  Procesar pedido")

        if error is not None:
            self._set_result_text(f"❌ Error: {error}")
            messagebox.showerror(
                "Error creando pedido",
                f"No se pudo crear el pedido.\n\nDetalle:\n{error}",
                parent=self,
            )
            return

        assert result is not None
        self._last_result = result
        self.btn_open.configure(state="normal")

        lang_lbl = {"es": "Español", "en": "English"}.get(result.vddl_lang, result.vddl_lang)
        lines = [
            "✅ Pedido procesado correctamente.",
            "",
            f"📁 Pedido:           {result.pedido_dir}",
            f"📁 2-Tecnico:        {result.tecnico_dir}",
            f"📁 00 DOCUMENTACIÓN: {result.documentacion_dir}",
            f"📋 Plantilla copiada: {'sí' if result.template_copied else 'no'}",
        ]
        if result.subfolders_created:
            lines.append(
                f"📂 Subcarpetas env.: {len(result.subfolders_created)} creadas/garantizadas"
            )
            # Mostrar las primeras 5 para no saturar
            for name in result.subfolders_created[:5]:
                lines.append(f"     • {name}")
            if len(result.subfolders_created) > 5:
                lines.append(f"     • … y {len(result.subfolders_created) - 5} más")
        if result.planning_file:
            lines.append(f"📊 Planning:         {result.planning_file.name}")
        if result.vddl_file:
            lines.append(f"📑 VDDL ({lang_lbl}):    {result.vddl_file.name}")
        if cm_saved:
            lines.append(
                f"📒 Comm. Matrix:     {cm_saved['key']}  "
                f"·  {len(cm_saved['to'])} TO  ·  {len(cm_saved['cc'])} CC"
            )
        if cm_error:
            lines.append(f"⚠ Comm. Matrix: NO guardada — {cm_error}")

        if result.warnings:
            lines.append("")
            lines.append("⚠ Avisos:")
            for w in result.warnings:
                lines.append(f"   • {w}")

        self._set_result_text("\n".join(lines))

        if result.warnings:
            messagebox.showwarning(
                "Pedido creado con avisos",
                "El pedido se creó pero hubo avisos:\n\n"
                + "\n".join(f"• {w}" for w in result.warnings),
                parent=self,
            )

    def _set_result_text(self, text: str) -> None:
        self.txt_result.configure(state="normal")
        self.txt_result.delete("1.0", "end")
        self.txt_result.insert("1.0", text)
        self.txt_result.configure(state="disabled")
