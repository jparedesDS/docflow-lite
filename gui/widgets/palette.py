"""Paleta de comandos (Ctrl+K) — salto rápido a secciones, pedidos y documentos.

Escribe un Nº de pedido (P-26/048), un Nº de documento (26-048-CAL-0002), parte
de un título/cliente o el nombre de una sección. ↑↓ para moverse, Enter abre el
resultado seleccionado, Esc cierra. Los datos salen del monitoring ya cacheado,
así que abrir la paleta es instantáneo.
"""

from __future__ import annotations

import customtkinter as ctk

from gui import theme
from gui.widgets import ui

_LIMIT = 30
_KIND_LABEL = {"section": "Sección", "pedido": "Pedido", "doc": "Documento"}
_KIND_COLOR = {"section": theme.ACCENT, "pedido": theme.BLUE, "doc": theme.GREEN}
_KIND_ORDER = {"section": 0, "pedido": 1, "doc": 2}


def _base_pedido(p) -> str:
    """'P-26/048-S00' → 'P-26/048' (quita el sufijo de suministro)."""
    p = str(p or "").strip()
    return p[:-4] if len(p) > 4 and p[-4:-2].upper() == "-S" and p[-2:].isdigit() else p


class CommandPalette(ctk.CTkToplevel):
    W, H = 680, 460

    def __init__(self, app):
        super().__init__(app, fg_color=theme.BG_CARD)
        self._app = app
        self._items: list[dict] = []
        self._results: list[dict] = []
        self._rows: list[ctk.CTkFrame] = []
        self._sel = 0
        self._after_id = None

        self.title("Buscar · DocFlow")
        self.transient(app)
        self.resizable(False, False)
        self._build()
        self._center()
        self._load_items()
        self._show(self._results_for(""))

        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Return>", lambda _e: self._activate())
        self.bind("<Up>", lambda _e: self._move(-1))
        self.bind("<Down>", lambda _e: self._move(1))
        self.after(60, self._focus)
        try:
            self.grab_set()
        except Exception:  # noqa: BLE001 — sin grab también funciona
            pass

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=theme.SPACE_5, pady=(theme.SPACE_5, theme.SPACE_2))
        ctk.CTkLabel(top, text="🔍", font=theme.font(16)).pack(side="left", padx=(0, theme.SPACE_2))
        self.entry = ctk.CTkEntry(
            top, placeholder_text="Pedido, documento, cliente o sección…",
            height=40, corner_radius=theme.RADIUS_MD, font=theme.font(14),
            fg_color=theme.BG_INPUT, border_color=theme.BORDER, text_color=theme.TEXT_MAIN,
        )
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<KeyRelease>", self._on_key)

        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list.pack(fill="both", expand=True, padx=theme.SPACE_3, pady=(0, theme.SPACE_2))

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=theme.SPACE_5, pady=(0, theme.SPACE_3))
        self.lbl_count = ctk.CTkLabel(foot, text="", font=theme.FONT_TINY, text_color=theme.TEXT_MUTED)
        self.lbl_count.pack(side="left")
        ctk.CTkLabel(foot, text="↑↓ moverse   ·   Enter abrir   ·   Esc cerrar",
                     font=theme.FONT_TINY, text_color=theme.TEXT_MUTED).pack(side="right")

    def _center(self) -> None:
        try:
            ax, ay = self._app.winfo_rootx(), self._app.winfo_rooty()
            aw = self._app.winfo_width()
            x = ax + max(0, (aw - self.W) // 2)
            y = ay + 110
        except Exception:  # noqa: BLE001
            x, y = 200, 150
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")

    def _focus(self) -> None:
        try:
            self.lift()
            self.entry.focus_set()
        except Exception:  # noqa: BLE001
            pass

    # ── Datos ─────────────────────────────────────────────────────────────────

    def _load_items(self) -> None:
        app = self._app
        allowed = getattr(app, "_nav_keys", set())
        entries = list(app.NAV_LAYOUT) + [{"type": "item", "key": "ajustes", "label": "Ajustes", "icon": "⚙"}]
        for entry in entries:
            for it in (entry["items"] if entry.get("type") == "group" else [entry]):
                if it["key"] not in allowed:
                    continue
                self._items.append({
                    "kind": "section", "key": it["key"], "icon": it.get("icon", "▸"),
                    "title": it["label"],
                    "sub": "Sección",
                    "search": it["label"].lower(),
                })

        try:
            from core.services import monitoring
            docs = monitoring.get_monitoring_data()
        except Exception:  # noqa: BLE001 — sin ERP la paleta sigue sirviendo para secciones
            docs = []

        # Un ítem por pedido BASE (P-26/048): Seguimiento trabaja por pedido y
        # agrupa los suministros (-S00, -S01…) dentro.
        seen: set[str] = set()
        for d in docs:
            ped = _base_pedido(d.get("Nº Pedido", ""))
            if not ped or ped in seen:
                continue
            seen.add(ped)
            cli = str(d.get("Cliente", "") or "").strip()
            mat = str(d.get("Material", "") or "").strip()
            self._items.append({
                "kind": "pedido", "pedido": ped, "icon": "▦", "title": ped,
                "sub": "  ·  ".join(x for x in (cli, mat) if x),
                "search": f"{ped} {cli} {mat}".lower(),
            })
        for d in docs:
            num = str(d.get("Nº Doc. EIPSA", "") or "").strip()
            if not num:
                continue
            tit = str(d.get("Título", "") or "").strip()
            ped = str(d.get("Nº Pedido", "") or "").strip()
            self._items.append({
                "kind": "doc", "doc": num, "icon": "◫", "title": num,
                "sub": "  ·  ".join(x for x in (tit, ped) if x),
                "search": f"{num} {tit} {ped}".lower(),
            })

    def _results_for(self, q: str) -> list[dict]:
        q = q.strip().lower()
        if not q:
            return [i for i in self._items if i["kind"] == "section"]
        tokens = q.split()
        hits = [i for i in self._items if all(t in i["search"] for t in tokens)]
        # Primero lo que EMPIEZA por lo escrito, luego por tipo (sección · pedido · doc)
        hits.sort(key=lambda i: (0 if i["title"].lower().startswith(q) else 1,
                                 _KIND_ORDER[i["kind"]], i["title"]))
        return hits[:_LIMIT]

    # ── Render ────────────────────────────────────────────────────────────────

    def _on_key(self, event) -> None:
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(120, lambda: self._show(self._results_for(self.entry.get())))

    def _show(self, results: list[dict]) -> None:
        for r in self._rows:
            r.destroy()
        self._rows = []
        self._results = results
        self._sel = 0
        if not results:
            ui.empty_state(self.list, "Sin resultados", hint="Prueba con el Nº de pedido o parte del título.", pady=30)
            self.lbl_count.configure(text="")
            return
        for idx, it in enumerate(results):
            self._rows.append(self._row(idx, it))
        self._paint()
        n = len(results)
        self.lbl_count.configure(text=f"{n} resultado{'s' if n != 1 else ''}" + ("  (máx. 30)" if n >= _LIMIT else ""))

    def _row(self, idx: int, it: dict) -> ctk.CTkFrame:
        row = ctk.CTkFrame(self.list, fg_color="transparent", corner_radius=theme.RADIUS_MD, cursor="hand2")
        row.pack(fill="x", pady=1)
        color = _KIND_COLOR[it["kind"]]
        ctk.CTkLabel(row, text=it["icon"], font=theme.font(15, "bold"), text_color=color,
                     width=30).pack(side="left", padx=(theme.SPACE_2, theme.SPACE_1), pady=theme.SPACE_2)
        txt = ctk.CTkFrame(row, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True, pady=theme.SPACE_1)
        ctk.CTkLabel(txt, text=it["title"], font=theme.FONT_BODY_BOLD, text_color=theme.TEXT_MAIN,
                     anchor="w").pack(anchor="w")
        if it.get("sub"):
            sub = it["sub"] if len(it["sub"]) <= 78 else it["sub"][:77] + "…"
            ctk.CTkLabel(txt, text=sub, font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                         anchor="w").pack(anchor="w")
        ui.badge(row, _KIND_LABEL[it["kind"]], color).pack(side="right", padx=theme.SPACE_2)
        for w in (row, txt, *row.winfo_children(), *txt.winfo_children()):
            w.bind("<Button-1>", lambda _e, i=idx: self._activate(i))
        return row

    def _paint(self) -> None:
        for i, r in enumerate(self._rows):
            r.configure(fg_color=theme.ACCENT_SOFT if i == self._sel else "transparent")

    def _move(self, delta: int) -> None:
        if not self._rows:
            return
        self._sel = max(0, min(len(self._rows) - 1, self._sel + delta))
        self._paint()

    # ── Acción ────────────────────────────────────────────────────────────────

    def _activate(self, idx: int | None = None) -> None:
        if idx is not None:
            self._sel = idx
        if not self._results:
            return
        it = self._results[self._sel]
        app = self._app
        self.destroy()
        # Después de cerrar (y soltar el grab) para que la navegación pinte bien
        if it["kind"] == "section":
            app.after(0, lambda: app.navigate(it["key"]))
        elif it["kind"] == "pedido":
            app.after(0, lambda: app.open_pedido(it["pedido"]))
        else:
            app.after(0, lambda: app.open_documento(it["doc"]))
