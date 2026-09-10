"""Gráficos a medida sobre Canvas de tk: líneas, barras, donut, burbujas y sparkline.

Sin dependencias (nada de matplotlib): son unas cuantas primitivas de Canvas, que
además pesan mucho menos que incrustar una figura y se repintan al vuelo cuando
cambia el tamaño de la ventana.

Todo hereda de `ChartCard`, que pone la tarjeta (fondo, borde, título) y llama a
`_pintar(w, h)` cuando hay que repintar, con un pequeño retardo para no repintar
cien veces mientras se arrastra el borde de la ventana.

Los colores salen del tema, así que funcionan en claro y en oscuro. Donde hace
falta transparencia (el relleno bajo una línea) se mezcla contra el fondo con
`ui.blend`, porque el Canvas de tk no tiene alfa.

    charts.LineChart(parent, series=[{"label": "Enviados", "color": theme.BLUE,
                                      "values": [...]}], x_labels=[...])
"""

from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from gui import theme
from gui.widgets import ui

# Márgenes internos del área de dibujo (deja sitio a los rótulos de los ejes).
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 52, 16, 14, 26


def _nice_max(value: float) -> float:
    """Techo 'redondo' para el eje Y: 1-2-5 × 10ⁿ justo por encima del máximo."""
    if value <= 0:
        return 1.0
    exp = 0
    v = float(value)
    while v >= 10:
        v /= 10
        exp += 1
    while v < 1:
        v *= 10
        exp -= 1
    step = next(s for s in (1, 2, 2.5, 5, 10) if v <= s)
    return step * (10 ** exp)


def fmt_num(v: float) -> str:
    """Número corto para ejes y etiquetas: 1.234.567 → 1,2 M."""
    a = abs(v)
    if a >= 1_000_000:
        return f"{v / 1_000_000:.1f}".replace(".", ",").rstrip("0").rstrip(",") + " M"
    if a >= 1_000:
        return f"{v / 1_000:.1f}".replace(".", ",").rstrip("0").rstrip(",") + "k"
    if isinstance(v, float) and v != int(v):
        return f"{v:.1f}".replace(".", ",")
    return str(int(v))


def fmt_eur(v: float) -> str:
    return fmt_num(v) + " €"


class ChartCard(ctk.CTkFrame):
    """Tarjeta con título y un Canvas que se repinta al redimensionar."""

    def __init__(self, master, title: str = "", subtitle: str = "", height: int = 230,
                 legend: list | None = None, **kwargs):
        super().__init__(master, fg_color=theme.BG_CARD, corner_radius=12,
                         border_width=1, border_color=theme.BORDER, **kwargs)
        self._after = None

        if title:
            head = ctk.CTkFrame(self, fg_color="transparent")
            head.pack(fill="x", padx=theme.SPACE_3, pady=(theme.SPACE_3, 0))
            box = ctk.CTkFrame(head, fg_color="transparent")
            box.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(box, text=title, font=theme.FONT_SECTION,
                         text_color=theme.TEXT_MAIN, anchor="w").pack(anchor="w")
            if subtitle:
                ctk.CTkLabel(box, text=subtitle, font=theme.FONT_TINY,
                             text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")
            if legend:
                leg = ctk.CTkFrame(head, fg_color="transparent")
                leg.pack(side="right")
                for label, color in legend:
                    chip = ctk.CTkFrame(leg, fg_color="transparent")
                    chip.pack(side="left", padx=(theme.SPACE_2, 0))
                    ctk.CTkFrame(chip, fg_color=color, width=10, height=10,
                                 corner_radius=3).pack(side="left")
                    ctk.CTkLabel(chip, text=label, font=theme.FONT_TINY,
                                 text_color=theme.TEXT_SUB).pack(side="left", padx=(4, 0))

        self.canvas = tk.Canvas(self, bg=theme.BG_CARD, highlightthickness=0, bd=0,
                                height=height)
        self.canvas.pack(fill="both", expand=True, padx=theme.SPACE_2,
                         pady=(theme.SPACE_2, theme.SPACE_3))
        self.canvas.bind("<Configure>", self._schedule)

    def _schedule(self, _e=None) -> None:
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except Exception:  # noqa: BLE001
                pass
        self._after = self.after(30, self._repaint)

    def _repaint(self) -> None:
        self._after = None
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w < 40 or h < 30:
            return
        self.canvas.delete("all")
        try:
            self._pintar(w, h)
        except Exception:  # noqa: BLE001 — un gráfico roto no puede tumbar la vista
            self.canvas.create_text(w / 2, h / 2, text="—", fill=theme.TEXT_MUTED,
                                    font=theme.font(11))

    def _pintar(self, w: int, h: int) -> None:      # pragma: no cover - lo hacen las hijas
        raise NotImplementedError

    # ── Ayudas comunes de ejes ───────────────────────────────────────────────

    def _ejes(self, w, h, vmax, *, pad_l=_PAD_L, pad_t=_PAD_T, pad_b=_PAD_B,
              unit="") -> tuple:
        """Rejilla horizontal + rótulos del eje Y. Devuelve (x0, y0, x1, y1)."""
        x0, x1 = pad_l, w - _PAD_R
        y0, y1 = pad_t, h - pad_b
        for i in range(5):
            v = vmax * i / 4
            y = y1 - (y1 - y0) * i / 4
            self.canvas.create_line(x0, y, x1, y, fill=theme.BORDER)
            self.canvas.create_text(x0 - 6, y, text=fmt_num(v) + unit, anchor="e",
                                    fill=theme.TEXT_MUTED, font=theme.font(9))
        return x0, y0, x1, y1

    def _rotulos_x(self, labels, x0, x1, y, step_hint: int = 1) -> None:
        """Rótulos del eje X, salteados si no caben.

        Se van poniendo desde el final hacia atrás: así el último mes —que es el
        que se mira— siempre sale, y el hueco entre rótulos es constante. Yendo
        de izquierda a derecha, el último caía pegado al penúltimo y se
        superponían («ago 26ep 26»).
        """
        n = len(labels)
        if not n:
            return
        every = max(1, step_hint)
        for i in range(n - 1, -1, -every):
            x = x0 + (x1 - x0) * (i / max(1, n - 1))
            self.canvas.create_text(min(x, x1 - 2), y, text=str(labels[i]), anchor="n",
                                    fill=theme.TEXT_MUTED, font=theme.font(9))

    def _vacio(self, w, h, texto="Sin datos") -> None:
        self.canvas.create_text(w / 2, h / 2, text=texto, fill=theme.TEXT_MUTED,
                                font=theme.font(11))


class LineChart(ChartCard):
    """Una o varias series en el tiempo, con relleno opcional bajo la línea."""

    def __init__(self, master, series: list, x_labels: list, *, unit: str = "",
                 area: bool = True, dots: bool | None = None, **kwargs):
        self._series = [s for s in series if s.get("values")]
        self._x = list(x_labels)
        self._unit = unit
        self._area = area
        self._dots = dots
        kwargs.setdefault("legend", [(s["label"], s["color"]) for s in self._series]
                          if len(self._series) > 1 else None)
        super().__init__(master, **kwargs)
        self._schedule()

    def _pintar(self, w, h) -> None:
        if not self._series or not self._x:
            return self._vacio(w, h)
        vmax = _nice_max(max((max(s["values"]) for s in self._series), default=0))
        x0, y0, x1, y1 = self._ejes(w, h, vmax, unit=self._unit)
        n = len(self._x)
        dots = self._dots if self._dots is not None else n <= 18

        def punto(i, v):
            x = x0 + (x1 - x0) * (i / max(1, n - 1))
            return x, y1 - (y1 - y0) * (v / vmax if vmax else 0)

        for s in self._series:
            vals = s["values"][:n]
            pts = [punto(i, v) for i, v in enumerate(vals)]
            if len(pts) < 2:
                continue
            if self._area and len(self._series) <= 2:
                poly = [c for p in pts for c in p] + [pts[-1][0], y1, pts[0][0], y1]
                self.canvas.create_polygon(
                    poly, fill=ui.blend(s["color"], theme.BG_CARD, 0.16), outline="")
            self.canvas.create_line([c for p in pts for c in p],
                                    fill=s["color"], width=2, smooth=False,
                                    capstyle="round", joinstyle="round")
            if dots:
                for x, y in pts:
                    self.canvas.create_oval(x - 3, y - 3, x + 3, y + 3,
                                            fill=s["color"], outline=theme.BG_CARD)
            # El último valor, escrito: es el que se mira. Va a la IZQUIERDA del
            # punto, que el punto está pegado al borde y por fuera se cortaba.
            lx, ly = pts[-1]
            self.canvas.create_text(lx - 7, ly - 9, anchor="e",
                                    text=fmt_num(vals[-1]) + self._unit,
                                    fill=s["color"], font=theme.font(10, "bold"))

        self._rotulos_x(self._x, x0, x1, y1 + 6, step_hint=max(1, n // 12))


class BarChart(ChartCard):
    """Barras verticales, opcionalmente con una segunda serie de comparación."""

    def __init__(self, master, labels: list, series: list, *, unit: str = "", **kwargs):
        self._labels = list(labels)
        self._series = series
        self._unit = unit
        kwargs.setdefault("legend", [(s["label"], s["color"]) for s in series]
                          if len(series) > 1 else None)
        super().__init__(master, **kwargs)
        self._schedule()

    def _pintar(self, w, h) -> None:
        if not self._labels or not self._series:
            return self._vacio(w, h)
        vmax = _nice_max(max((max(s["values"]) for s in self._series), default=0))
        x0, y0, x1, y1 = self._ejes(w, h, vmax, unit=self._unit)
        n = len(self._labels)
        slot = (x1 - x0) / max(1, n)
        ns = len(self._series)
        bw = max(3.0, min(38.0, slot * 0.7 / ns))
        for i in range(n):
            centro = x0 + slot * (i + 0.5)
            for j, s in enumerate(self._series):
                v = s["values"][i] if i < len(s["values"]) else 0
                alto = (y1 - y0) * (v / vmax if vmax else 0)
                bx = centro - (bw * ns) / 2 + bw * j
                self.canvas.create_rectangle(bx, y1 - alto, bx + bw - 1, y1,
                                             fill=s["color"], outline="")
                if v and ns == 1 and slot > 26:
                    self.canvas.create_text(centro, y1 - alto - 8, text=fmt_num(v),
                                            fill=theme.TEXT_SUB, font=theme.font(9))
        for i, lb in enumerate(self._labels):
            if n > 16 and i % 2:
                continue
            self.canvas.create_text(x0 + slot * (i + 0.5), y1 + 6, text=str(lb),
                                    anchor="n", fill=theme.TEXT_MUTED, font=theme.font(9))


class StackedBars(ChartCard):
    """Barras apiladas: cada barra es un 100% repartido entre categorías."""

    def __init__(self, master, labels: list, series: list, *, totals: list | None = None,
                 **kwargs):
        self._labels = list(labels)
        self._series = series
        self._totals = totals
        kwargs.setdefault("legend", [(s["label"], s["color"]) for s in series])
        super().__init__(master, **kwargs)
        self._schedule()

    def _pintar(self, w, h) -> None:
        if not self._labels:
            return self._vacio(w, h)
        x0, x1 = _PAD_L - 34, w - _PAD_R
        y0, y1 = _PAD_T, h - _PAD_B
        n = len(self._labels)
        slot = (x1 - x0) / max(1, n)
        bw = max(6.0, min(46.0, slot * 0.66))
        for i in range(n):
            total = sum(s["values"][i] for s in self._series if i < len(s["values"])) or 1
            centro = x0 + slot * (i + 0.5)
            y = y1
            for s in self._series:
                v = s["values"][i] if i < len(s["values"]) else 0
                if v <= 0:
                    continue
                alto = (y1 - y0) * (v / total)
                self.canvas.create_rectangle(centro - bw / 2, y - alto, centro + bw / 2, y,
                                             fill=s["color"], outline="")
                if alto > 13 and bw > 22:
                    self.canvas.create_text(centro, y - alto / 2, text=str(int(v)),
                                            fill=theme.TEXT_ON_ACCENT, font=theme.font(9, "bold"))
                y -= alto
            etiqueta = str(self._labels[i])
            if self._totals:
                etiqueta += f"  ({fmt_num(self._totals[i])})"
            self.canvas.create_text(centro, y1 + 6, text=etiqueta, anchor="n",
                                    fill=theme.TEXT_MUTED, font=theme.font(9))


class Donut(ChartCard):
    """Anillo de reparto con el total en el centro."""

    def __init__(self, master, slices: list, *, center_label: str = "", **kwargs):
        self._slices = [s for s in slices if s.get("value", 0) > 0]
        self._center = center_label
        super().__init__(master, **kwargs)
        self._schedule()

    def _pintar(self, w, h) -> None:
        if not self._slices:
            return self._vacio(w, h)
        total = sum(s["value"] for s in self._slices)
        r = min(w * 0.42, h * 0.42)
        cx, cy = w * 0.32 if w > 380 else w / 2, h / 2
        grosor = max(12, r * 0.34)
        inicio = 90.0
        for s in self._slices:
            extent = -360.0 * s["value"] / total
            if abs(extent) < 0.35:            # arcos invisibles: se ven como línea
                extent = -0.35
            self.canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=inicio,
                                   extent=extent, style="arc", outline=s["color"],
                                   width=grosor)
            inicio += extent
        self.canvas.create_text(cx, cy - 7, text=fmt_num(total),
                                fill=theme.TEXT_MAIN, font=theme.font(19, "bold"))
        if self._center:
            self.canvas.create_text(cx, cy + 12, text=self._center.upper(),
                                    fill=theme.TEXT_MUTED, font=theme.font(9))
        # Leyenda a la derecha, con valor y porcentaje
        if w > 380:
            lx = cx + r + 22
            paso = min(21, (h - 20) / max(1, len(self._slices)))
            ly = cy - paso * (len(self._slices) - 1) / 2
            for s in self._slices:
                self.canvas.create_rectangle(lx, ly - 4, lx + 9, ly + 5,
                                             fill=s["color"], outline="")
                pct = round(100 * s["value"] / total)
                self.canvas.create_text(lx + 16, ly, anchor="w",
                                        text=f"{s['label']}  {fmt_num(s['value'])} · {pct}%",
                                        fill=theme.TEXT_SUB, font=theme.font(10))
                ly += paso


class Bubble(ChartCard):
    """Dispersión con tamaño variable: dos ejes y el volumen en el radio."""

    def __init__(self, master, points: list, *, x_label: str = "", y_label: str = "",
                 xmax: float | None = None, ymax: float | None = None,
                 diagonal: bool = False, **kwargs):
        self._points = points
        self._xl, self._yl = x_label, y_label
        self._xmax, self._ymax = xmax, ymax
        self._diagonal = diagonal      # línea «lo que tocaría»: debajo = va tarde
        super().__init__(master, **kwargs)
        self._schedule()

    def _pintar(self, w, h) -> None:
        if not self._points:
            return self._vacio(w, h)
        xmax = self._xmax or _nice_max(max(p["x"] for p in self._points))
        ymax = self._ymax or _nice_max(max(p["y"] for p in self._points))
        rmax = max((p.get("r", 1) for p in self._points), default=1) or 1
        # Aire arriba y abajo para los rótulos de los ejes, que si no se montan
        # encima de las marcas de la rejilla.
        x0, y0, x1, y1 = self._ejes(w, h, ymax, pad_t=26, pad_b=42)

        self.canvas.create_text(x0, y0 - 12, text=self._yl, anchor="w",
                                fill=theme.TEXT_MUTED, font=theme.font(9))
        self.canvas.create_text(x1, y1 + 26, text=self._xl, anchor="e",
                                fill=theme.TEXT_MUTED, font=theme.font(9))
        for i in range(1, 5):
            x = x0 + (x1 - x0) * i / 4
            self.canvas.create_line(x, y0, x, y1, fill=theme.BORDER)
            self.canvas.create_text(x, y1 + 6, text=fmt_num(xmax * i / 4), anchor="n",
                                    fill=theme.TEXT_MUTED, font=theme.font(9))

        if self._diagonal:
            self.canvas.create_line(x0, y1, x1, y0, fill=theme.BORDER_STRONG,
                                    width=1, dash=(4, 4))
            self.canvas.create_text(x1 - 4, y0 + 4, text="al día", anchor="ne",
                                    fill=theme.TEXT_MUTED, font=theme.font(9))

        # Solo se rotulan las burbujas gordas: con todas, en la zona densa no se
        # lee ninguna.
        con_nombre = {id(p) for p in sorted(self._points, key=lambda p: -p.get("r", 0))[:10]}
        for p in self._points:
            px = x0 + (x1 - x0) * min(1.0, p["x"] / xmax)
            py = y1 - (y1 - y0) * min(1.0, p["y"] / ymax)
            r = 5 + 16 * (p.get("r", 1) / rmax) ** 0.5
            col = p.get("color", theme.ACCENT)
            self.canvas.create_oval(px - r, py - r, px + r, py + r,
                                    fill=ui.blend(col, theme.BG_CARD, 0.45), outline=col)
            if p.get("label") and id(p) in con_nombre:
                self.canvas.create_text(px, py - r - 7, text=str(p["label"])[:16],
                                        fill=theme.TEXT_SUB, font=theme.font(9))


class Sparkline(tk.Canvas):
    """Línea diminuta para meter dentro de una tarjeta KPI."""

    def __init__(self, master, values: list, color: str, width: int = 110, height: int = 30):
        super().__init__(master, bg=theme.BG_CARD, highlightthickness=0, bd=0,
                         width=width, height=height)
        vals = [float(v) for v in values if v is not None]
        if len(vals) < 2:
            return
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1
        pts = []
        for i, v in enumerate(vals):
            x = 2 + (width - 4) * i / (len(vals) - 1)
            y = height - 3 - (height - 6) * (v - lo) / span
            pts += [x, y]
        self.create_polygon(pts + [width - 2, height, 2, height],
                            fill=ui.blend(color, theme.BG_CARD, 0.18), outline="")
        self.create_line(pts, fill=color, width=2, capstyle="round", joinstyle="round")
        self.create_oval(pts[-2] - 2.5, pts[-1] - 2.5, pts[-2] + 2.5, pts[-1] + 2.5,
                         fill=color, outline="")


def trend_card(parent, label: str, value: str, color: str, sub: str = "",
               spark: list | None = None, delta: float | None = None,
               subir_es_bueno: bool = True):
    """Tarjeta KPI con sparkline y variación respecto al periodo anterior.

    `subir_es_bueno=False` para lo que empeora al crecer (días de respuesta,
    devoluciones…): la flecha sigue apuntando arriba, pero en rojo.
    """
    box = ctk.CTkFrame(parent, fg_color=theme.BG_CARD, corner_radius=12,
                       border_width=1, border_color=theme.BORDER, height=112)
    box.pack_propagate(False)
    ctk.CTkLabel(box, text=str(label).upper(), font=theme.FONT_LABEL,
                 text_color=theme.TEXT_MUTED, anchor="w").pack(
        anchor="w", padx=theme.SPACE_3, pady=(theme.SPACE_3, 0))

    fila = ctk.CTkFrame(box, fg_color="transparent")
    fila.pack(fill="x", padx=theme.SPACE_3)
    ctk.CTkLabel(fila, text=str(value), font=theme.font(24, "bold"),
                 text_color=color, anchor="w").pack(side="left")
    if delta is not None:
        signo = "▲" if delta >= 0 else "▼"
        mejora = (delta >= 0) == subir_es_bueno
        dcol = theme.GREEN if mejora else theme.RED
        ctk.CTkLabel(fila, text=f" {signo} {abs(delta):.0f}%".replace(".", ","),
                     font=theme.FONT_SMALL_BOLD, text_color=dcol).pack(side="left", pady=(6, 0))
    if spark and len([v for v in spark if v is not None]) > 1:
        Sparkline(fila, spark, color).pack(side="right", pady=(6, 0))
    ctk.CTkLabel(box, text=sub or " ", font=theme.FONT_TINY, text_color=theme.TEXT_MUTED,
                 anchor="w").pack(anchor="w", padx=theme.SPACE_3, pady=(0, theme.SPACE_2))
    return box
