"""Sidebar de navegación — ítems sueltos + grupos colapsables (acordeón).

Estructura recibida en `layout` (lista ordenada):
  · {"type": "item",  "key", "label", "icon"}
  · {"type": "group", "id", "label", "items": [ {key,label,icon}, … ]}

Comportamiento:
  · Cada grupo tiene cabecera con chevron; click pliega/despliega su cuerpo.
  · El grupo de la sección activa se auto-expande (set_active).
  · El estado plegado se recuerda en preferences ("sidebar_collapsed").

Footer: identidad del usuario, cerrar sesión, toggle de tema y crédito.
"""

import webbrowser

import customtkinter as ctk

from gui import theme

PORTFOLIO_URL = "https://jparedesds.github.io/"

_CHEVRON_OPEN = "▾"
_CHEVRON_CLOSED = "▸"


class Sidebar(ctk.CTkFrame):
    WIDTH = 232

    def __init__(
        self, master, layout: list[dict], on_select,
        on_toggle_theme=None, on_logout=None,
        current_user_label: str = "",
        **kwargs,
    ):
        super().__init__(
            master, width=self.WIDTH, corner_radius=0,
            fg_color=theme.BG_SIDEBAR, **kwargs,
        )
        self.pack_propagate(False)
        self.grid_propagate(False)

        self._on_select = on_select
        self._on_toggle_theme = on_toggle_theme
        self._on_logout = on_logout
        self._items: dict[str, dict] = {}      # key → {row, bar, btn}
        self._groups: dict[str, dict] = {}      # gid → {header, body, collapsed}
        self._key_group: dict[str, str] = {}    # key → gid
        self._active_key: str | None = None
        self._collapsed = self._load_collapsed()

        # ── Brand header ──────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=theme.SPACE_5, pady=(theme.SPACE_5, theme.SPACE_2))
        ctk.CTkLabel(
            header, text="◆  DocFlow", font=theme.font(17, "bold"),
            text_color=theme.TEXT_MAIN, anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header, text="Lite", font=theme.font(10, "bold"),
            text_color=theme.ACCENT, anchor="w",
        ).pack(anchor="w")

        sep = ctk.CTkFrame(self, fg_color=theme.BORDER, height=1)
        sep.pack(fill="x", padx=theme.SPACE_4, pady=(theme.SPACE_3, theme.SPACE_2))

        # ── Navegación (ítems sueltos + grupos) ───────────────────────────
        for entry in layout:
            if entry.get("type") == "group":
                self._build_group(entry)
            else:
                self._build_nav_item(self, entry)

        # ── Footer ─────────────────────────────────────────────────────────
        self._build_footer(current_user_label)

    # ── Persistencia del estado plegado ──────────────────────────────────────

    def _load_collapsed(self) -> set:
        try:
            from core import preferences
            v = preferences.get("sidebar_collapsed")
            return set(v) if isinstance(v, list) else set()
        except Exception:
            return set()

    def _persist_collapsed(self) -> None:
        try:
            from core import preferences
            collapsed = [gid for gid, g in self._groups.items() if g["collapsed"]]
            preferences.set_value("sidebar_collapsed", sorted(collapsed))
        except Exception:
            pass

    # ── Construcción ──────────────────────────────────────────────────────────

    def _build_group(self, entry: dict) -> None:
        gid = entry["id"]
        collapsed = gid in self._collapsed

        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(fill="x", pady=(theme.SPACE_2, 0))

        chevron = _CHEVRON_CLOSED if collapsed else _CHEVRON_OPEN
        header = ctk.CTkButton(
            wrap, text=f"{chevron}   {entry['label']}", anchor="w",
            font=theme.font(10, "bold"),
            height=theme.HEIGHT_BUTTON_SM, corner_radius=theme.RADIUS_SM,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_MUTED,
            command=lambda g=gid: self._toggle_group(g),
        )
        header.pack(fill="x", padx=(theme.SPACE_3, theme.SPACE_2))

        body = ctk.CTkFrame(wrap, fg_color="transparent")
        if not collapsed:
            body.pack(fill="x")

        self._groups[gid] = {"header": header, "body": body, "collapsed": collapsed,
                             "label": entry["label"]}

        for item in entry.get("items", []):
            self._build_nav_item(body, item, indent=theme.SPACE_4)
            self._key_group[item["key"]] = gid

    def _build_nav_item(self, parent, item: dict, indent: int = 0) -> None:
        key = item["key"]

        row = ctk.CTkFrame(parent, fg_color="transparent", height=theme.HEIGHT_BUTTON + 2)
        row.pack(fill="x", padx=(indent, theme.SPACE_2), pady=1)
        row.pack_propagate(False)

        bar = ctk.CTkFrame(row, width=3, fg_color="transparent", corner_radius=0)
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)

        btn = ctk.CTkButton(
            row, text=f"  {item.get('icon', '')}   {item['label']}", anchor="w",
            font=theme.FONT_BUTTON, height=theme.HEIGHT_BUTTON,
            corner_radius=theme.RADIUS_MD,
            fg_color="transparent", hover_color=theme.BG_INPUT,
            text_color=theme.TEXT_SUB,
            command=lambda k=key: self._handle_click(k),
        )
        btn.pack(side="left", fill="both", expand=True, padx=(theme.SPACE_1, 0))

        self._items[key] = {"row": row, "bar": bar, "btn": btn}

    def _build_footer(self, current_user_label: str) -> None:
        footer_box = ctk.CTkFrame(self, fg_color="transparent")
        footer_box.pack(side="bottom", fill="x", padx=theme.SPACE_3, pady=theme.SPACE_4)

        sep_footer = ctk.CTkFrame(footer_box, fg_color=theme.BORDER, height=1)
        sep_footer.pack(fill="x", padx=theme.SPACE_2, pady=(0, theme.SPACE_3))

        if current_user_label:
            user_row = ctk.CTkFrame(footer_box, fg_color="transparent")
            user_row.pack(fill="x", padx=theme.SPACE_2, pady=(0, theme.SPACE_2))
            ctk.CTkLabel(
                user_row, text="●", font=theme.font(11, "bold"),
                text_color=theme.GREEN, width=14,
            ).pack(side="left")
            ctk.CTkLabel(
                user_row, text=current_user_label, font=theme.font(11, "bold"),
                text_color=theme.TEXT_MAIN, anchor="w",
            ).pack(side="left", fill="x", expand=True)

            if self._on_logout is not None:
                ctk.CTkButton(
                    footer_box, text="Cerrar sesión", anchor="w", font=theme.font(11),
                    height=theme.HEIGHT_BUTTON_SM, corner_radius=theme.RADIUS_MD,
                    fg_color="transparent", hover_color=theme.BG_INPUT,
                    text_color=theme.TEXT_SUB, border_width=1, border_color=theme.BORDER,
                    command=self._on_logout,
                ).pack(fill="x", padx=theme.SPACE_2, pady=(0, theme.SPACE_2))

        if self._on_toggle_theme is not None:
            is_dark = theme.current_mode() == "dark"
            toggle_text = "☀  Modo claro" if is_dark else "🌙  Modo oscuro"
            ctk.CTkButton(
                footer_box, text=toggle_text, anchor="w", font=theme.font(11),
                height=theme.HEIGHT_BUTTON_SM, corner_radius=theme.RADIUS_MD,
                fg_color="transparent", hover_color=theme.BG_INPUT,
                text_color=theme.TEXT_SUB, border_width=1, border_color=theme.BORDER,
                command=self._on_toggle_theme,
            ).pack(fill="x", padx=theme.SPACE_2, pady=(0, theme.SPACE_3))

        credit_row = ctk.CTkFrame(footer_box, fg_color="transparent")
        credit_row.pack(anchor="w", padx=theme.SPACE_3, pady=(theme.SPACE_1, 0))
        ctk.CTkLabel(
            credit_row, text="© 2026  ", font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
        ).pack(side="left")
        link = ctk.CTkLabel(
            credit_row, text="jparedesDS", font=theme.font(10, "bold"),
            text_color=theme.ACCENT, cursor="hand2",
        )
        link.pack(side="left")
        link.bind("<Button-1>", lambda _e: webbrowser.open(PORTFOLIO_URL))
        link.bind("<Enter>", lambda _e: link.configure(text_color=theme.ACCENT_HOVER))
        link.bind("<Leave>", lambda _e: link.configure(text_color=theme.ACCENT))

    # ── Plegado de grupos ─────────────────────────────────────────────────────

    def _toggle_group(self, gid: str, expand: bool | None = None) -> None:
        g = self._groups.get(gid)
        if not g:
            return
        collapse = (not g["collapsed"]) if expand is None else (not expand)
        g["collapsed"] = collapse
        chevron = _CHEVRON_CLOSED if collapse else _CHEVRON_OPEN
        g["header"].configure(text=f"{chevron}   {g['label']}")
        if collapse:
            g["body"].pack_forget()
        else:
            g["body"].pack(fill="x")  # único hijo tras la cabecera → conserva el orden
        self._persist_collapsed()

    # ── Selección ──────────────────────────────────────────────────────────────

    def _handle_click(self, key: str) -> None:
        self.set_active(key)
        self._on_select(key)

    def set_active(self, key: str) -> None:
        # Asegurar visible el grupo que contiene la sección activa
        gid = self._key_group.get(key)
        if gid and self._groups.get(gid, {}).get("collapsed"):
            self._toggle_group(gid, expand=True)

        if self._active_key == key:
            return
        self._active_key = key
        for k, item in self._items.items():
            if k == key:
                item["bar"].configure(fg_color=theme.ACCENT)
                item["btn"].configure(
                    fg_color=theme.ACCENT_SOFT, text_color=theme.TEXT_MAIN,
                    hover_color=theme.ACCENT_SOFT,
                )
            else:
                item["bar"].configure(fg_color="transparent")
                item["btn"].configure(
                    fg_color="transparent", text_color=theme.TEXT_SUB,
                    hover_color=theme.BG_INPUT,
                )
