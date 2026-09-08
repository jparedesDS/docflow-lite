"""Ayuda contextual por sección — «?» en la cabecera y tecla F1.

Cada entrada explica, en lenguaje llano y en tres bloques, lo que un usuario
nuevo necesita para usar la sección sin leer ningún manual:
  · qué es (una frase)
  · cómo se usa (3-4 pasos)
  · atajos y trucos
"""

from __future__ import annotations

import customtkinter as ctk

from gui import theme

HELP: dict[str, dict] = {
    "home": {
        "titulo": "Inicio",
        "que": "Tu panel del día: los tres números que importan, qué hacer ahora y accesos directos.",
        "pasos": [
            "«Hoy»: urgente (críticos +15 días), por responder (devoluciones) y pendientes. Clic en una tarjeta abre Documentos ya filtrado.",
            "«Qué hacer ahora»: cada línea es una acción concreta con su botón (Reclamar, Ver, Agenda…).",
            "«Accesos rápidos»: pulsa cualquier tarjeta para ir a esa sección. Los números se actualizan solos.",
        ],
        "atajos": ["H · volver a Inicio", "Ctrl+K · buscar un pedido, documento o sección"],
    },
    "documentos": {
        "titulo": "Documentos",
        "que": "Todos los documentos de todos los pedidos, con su estado actual frente al cliente.",
        "pasos": [
            "Escribe en «Buscar» un Nº de documento, título o cliente.",
            "Pulsa una tarjeta de arriba (Aprobados, Devoluciones, Críticos…) para filtrar por estado; vuelve a pulsarla para quitar el filtro.",
            "Doble clic en una fila abre la ficha: revisiones, fechas y acciones.",
            "Botón «Filtros» para acotar por pedido, cliente o responsable.",
        ],
        "atajos": ["O · abrir Documentos", "Ctrl+K · saltar a un documento por su número",
                   "↻ · traer los documentos del ERP y recargar"],
    },
    "pedidos": {
        "titulo": "Seguimiento",
        "que": "El estado de un pedido de un vistazo: documentación, fabricación, equipos y qué requiere acción.",
        "pasos": [
            "Escribe el Nº de pedido o el cliente y elígelo en la lista.",
            "«Estado del pedido»: veredicto, avance documental, fabricación (fases y órdenes de trabajo) y plazo.",
            "«Equipos & Tags»: cada equipo con su plano, su cálculo y su estado de fabricación; doble clic abre la ficha.",
            "«Informe del pedido →» genera un informe web completo para compartir.",
        ],
        "atajos": ["Ctrl+K · escribe P-26/048 y Enter", "Las revisiones superadas están ocultas: marca «Incluir superados» si las necesitas"],
    },
    "compras": {
        "titulo": "Compras",
        "que": "Material pedido a proveedor que todavía no ha llegado, y a qué pedido afecta.",
        "pasos": [
            "La lista sale ordenada por retraso: primero lo que ya debería estar aquí.",
            "Rojo = la fecha prometida ya pasó. Ámbar = llega en los próximos 30 días.",
            "Doble clic abre el pedido afectado en Seguimiento; con el botón derecho copias proveedor o material.",
            "«Solo lo que va con retraso» deja únicamente lo que hay que reclamar.",
        ],
        "atajos": ["C · abrir Compras",
                   "El enlace con nuestro pedido lo pone Compras en las notas del pedido a proveedor"],
    },
    "calidad": {
        "titulo": "Calidad",
        "que": "No conformidades del ERP y equipos de medida con su calibración.",
        "pasos": [
            "«No conformidades»: doble clic abre la ficha completa con descripción, causa y acción correctiva.",
            "Ámbar = sin acción correctiva cerrada. Rojo = además la detectó el cliente.",
            "«Equipos de medida»: calibres, máquinas y manómetros; los vencidos salen arriba en rojo.",
            "Los equipos dados de baja se muestran en gris y no cuentan como vencidos.",
        ],
        "atajos": ["Q · abrir Calidad", "Desde una NC puedes saltar a su pedido en Seguimiento"],
    },
    "almacen": {
        "titulo": "Almacén",
        "que": "Cuánto espera el material terminado, desde que se avisa al cliente hasta que sale.",
        "pasos": [
            "«En almacén ahora»: lo avisado y aún sin enviar, lo más viejo arriba. Es la lista a la que reclamar.",
            "Verde hasta 7 días, ámbar hasta 30, rojo por encima.",
            "«Histórico de envíos»: cuánto tardó en salir lo ya enviado y el reparto de tiempos.",
            "Doble clic en un pedido lo abre en Seguimiento; «⤓ Excel» exporta la pestaña activa.",
        ],
        "atajos": ["M · abrir Almacén",
                   "Las fechas salen del ERP: «Aviso de entrega» y «Fecha de envío» del pedido",
                   "Solo hay datos desde 2025, que es cuando se empezó a rellenar el aviso"],
    },
    "devoluciones": {
        "titulo": "Devoluciones",
        "que": "Correos en los que el cliente devuelve documentación revisada (TR, GAIA, ACONEX, SENDOC, AYESA…).",
        "pasos": [
            "«Recargar» trae los correos del buzón.",
            "Doble clic en un correo: la app lo interpreta y muestra los documentos y su estado.",
            "Revisa, corrige un estado si hace falta y pulsa «Enviar notificación».",
            "«+ Devolución manual» si el correo no es de un portal reconocido: escribe el pedido y se autocompleta.",
            "«⤓ Descargar devolución» (Técnicas Reunidas y AYESA): baja el zip del portal y lo guarda con el "
            "correo en 00 TRANS Y RES \\ NNN (fecha) del pedido; además copia cada PDF devuelto a su carpeta "
            "2-Tecnico \\ dev. <Tipo> \\ rev<N> AP|COM (la crea si no existe). Con la descarga automática activa se hace solo.",
            "La columna «Descarga» marca «✓ guardada» cuando la devolución ya está en su carpeta; en la preview el botón "
            "pasa a «📂 Abrir carpetas» (abre 00 TRANS Y RES \\ NNN y las dev. donde quedaron los PDF) para comprobarla "
            "antes de enviar la notificación (que indica dónde está guardada).",
            "Solo se listan transmittals de verdad: respuestas (RE:/FW:), acuses de lectura y avisos de los portales quedan fuera.",
        ],
        "atajos": ["D · abrir Devoluciones", "El pedido, cliente y PO se completan solos desde el ERP",
                   "El acceso a eGesDoc y la descarga automática se configuran en Ajustes ▸ Portales"],
    },
    "reclamaciones": {
        "titulo": "Reclamaciones",
        "que": "Documentos enviados al cliente hace más de 15 días sin respuesta: los que toca reclamar.",
        "pasos": [
            "La lista se calcula sola al abrir; ajusta los días mínimos si quieres ser más o menos estricto.",
            "Marca los pedidos y pulsa «Enviar seleccionadas» (o «Preview» para ver el correo antes).",
            "Los destinatarios salen de la Comm. Matrix del pedido; edítala con el botón «Comm. Matrix».",
        ],
        "atajos": ["R · abrir Reclamaciones", "Desde la ficha de un documento también puedes generar su reclamación"],
    },
    "inbox": {
        "titulo": "Correo",
        "que": "El buzón de documentación, con resumen y clasificación por IA cuando está configurada.",
        "pasos": [
            "«Recargar» lee los correos recientes.",
            "Selecciona uno para leerlo; márcalo como leído o no leído.",
            "Con la clave de IA en Ajustes, cada correo trae un resumen automático.",
        ],
        "atajos": ["I · abrir la bandeja"],
    },
    "ofertas": {
        "titulo": "Ofertas",
        "que": "Ofertas recibidas en los buzones comerciales y control de su entrada por portal.",
        "pasos": [
            "Elige el rango de días y pulsa «Actualizar».",
            "Abre una oferta para ver el correo, marcarla como leída o registrar su gestión.",
            "«Excel» exporta la lista para el seguimiento comercial.",
        ],
        "atajos": ["Los buzones y el seguimiento de comerciales se configuran en Ajustes ▸ Ofertas"],
    },
    "docusign": {
        "titulo": "DocuSign",
        "que": "Sobres de firma electrónica: quién ha firmado, qué falta y descarga del PDF firmado.",
        "pasos": [
            "«Actualizar» trae los sobres de tu cuenta.",
            "Selecciona un sobre para ver firmantes y estado.",
            "«Descargar PDF» guarda el documento firmado.",
        ],
        "atajos": ["Las credenciales de DocuSign se guardan en Ajustes ▸ DocuSign"],
    },
    "apertura": {
        "titulo": "Nuevo pedido",
        "que": "Crea en un clic la estructura de carpetas de un pedido nuevo: plantilla, Planning y VDDL.",
        "pasos": [
            "Escribe el Nº de pedido (P-26/048): cliente y material se completan solos desde el ERP.",
            "«Localizar pedido» comprueba si ya existe la carpeta.",
            "«Procesar pedido» crea las carpetas y documentos; «Abrir carpeta» para verlo.",
        ],
        "atajos": ["N · abrir Apertura"],
    },
    "agenda": {
        "titulo": "Agenda",
        "que": "Tus tareas, notas y reuniones, en un solo sitio.",
        "pasos": [
            "«+ Nueva tarea» crea una tarea; márcala con el check cuando esté hecha.",
            "«Sincronizar con Documentos» crea tareas a partir de los documentos pendientes.",
            "Las notas y reuniones tienen su propia pestaña.",
        ],
        "atajos": ["A · abrir la Agenda"],
    },
    "informes": {
        "titulo": "Analítica",
        "que": "Cómo va la documentación en conjunto: rendimiento por cliente y equipo, y previsión.",
        "pasos": [
            "«Resumen»: distribución por estado, tiempos de respuesta y mapa de calor por cliente.",
            "«Equipo»: carga y ritmo de cada responsable.",
            "«Predicción & Scorecard»: fechas estimadas de cierre y puntuación por cliente.",
        ],
        "atajos": ["Para un informe compartible usa Centro de Reportes ▸ Informe interactivo"],
    },
    "reportes": {
        "titulo": "Centro de Reportes",
        "que": "Genera Excels e informes web, envía resúmenes por email o Teams y programa envíos automáticos.",
        "pasos": [
            "«Informes»: descarga el Monitoring Report en Excel o genera el informe web (semanal, mensual, ejecutivo o por pedido, con botón para PDF).",
            "«Resúmenes por email»: envía ahora el resumen ejecutivo o el personal, por email o Teams.",
            "«Programados»: deja los envíos automáticos (día, hora y destinatarios).",
        ],
        "atajos": ["P · abrir el Centro de Reportes", "Los Excel y la conexión al ERP se gestionan en Ajustes ▸ Fuentes de datos"],
    },
    "ajustes": {
        "titulo": "Ajustes",
        "que": "Conexiones, fuentes de datos, credenciales y usuarios. Solo administradores.",
        "pasos": [
            "Cada pestaña tiene su botón «Guardar»; los cambios de conexión se aplican al reiniciar.",
            "Las contraseñas se guardan cifradas (nunca en texto plano).",
            "«Fuentes de datos»: de dónde se leen los Excel y el botón para regenerar documentos y pedidos desde el ERP.",
            "«Portales»: usuario y contraseña de eGesDoc (Técnicas Reunidas) y la descarga automática de "
            "devoluciones (eGesDoc y AYESA).",
        ],
        "atajos": ["«↻ Reiniciar app» aplica los cambios de conexión"],
    },
}


class HelpDialog(ctk.CTkToplevel):
    """Ventana de ayuda de una sección: qué es · cómo se usa · atajos."""

    def __init__(self, master, key: str):
        super().__init__(master, fg_color=theme.BG_CARD)
        info = HELP.get(key) or {"titulo": key.capitalize(), "que": "", "pasos": [], "atajos": []}
        self.title(f"Ayuda · {info['titulo']}")
        self.resizable(False, False)
        self.transient(master)
        self._build(info)
        self._center(master)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(40, self.lift)
        try:
            self.grab_set()
        except Exception:  # noqa: BLE001
            pass

    def _build(self, info: dict) -> None:
        pad = theme.SPACE_5
        ctk.CTkLabel(self, text=info["titulo"], font=theme.FONT_HEADING, text_color=theme.TEXT_MAIN,
                     anchor="w").pack(anchor="w", padx=pad, pady=(pad, 0))
        if info.get("que"):
            ctk.CTkLabel(self, text=info["que"], font=theme.FONT_BODY, text_color=theme.TEXT_SUB,
                         anchor="w", justify="left", wraplength=520).pack(anchor="w", padx=pad, pady=(theme.SPACE_1, 0))

        if info.get("pasos"):
            self._section("Cómo se usa")
            for i, paso in enumerate(info["pasos"], 1):
                row = ctk.CTkFrame(self, fg_color="transparent")
                row.pack(fill="x", padx=pad, pady=1)
                ctk.CTkLabel(row, text=str(i), font=theme.FONT_SMALL_BOLD, text_color=theme.TEXT_ON_ACCENT,
                             fg_color=theme.ACCENT, corner_radius=10, width=20, height=20).pack(side="left", anchor="n", pady=2)
                ctk.CTkLabel(row, text=paso, font=theme.FONT_SMALL, text_color=theme.TEXT_MAIN,
                             anchor="w", justify="left", wraplength=480).pack(side="left", padx=(theme.SPACE_2, 0))

        if info.get("atajos"):
            self._section("Atajos y trucos")
            for a in info["atajos"]:
                ctk.CTkLabel(self, text=f"•  {a}", font=theme.FONT_SMALL, text_color=theme.TEXT_SUB,
                             anchor="w", justify="left", wraplength=500).pack(anchor="w", padx=pad + 4, pady=1)

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=pad, pady=(theme.SPACE_4, pad))
        ctk.CTkLabel(foot, text="F1 abre esta ayuda en cualquier sección", font=theme.FONT_TINY,
                     text_color=theme.TEXT_MUTED).pack(side="left")
        from gui.widgets import ui
        ui.button(foot, "Entendido", "primary", size="sm", command=self.destroy).pack(side="right")

    def _section(self, text: str) -> None:
        from gui.widgets import ui
        ui.section_header(self, text).pack(fill="x", padx=theme.SPACE_5, pady=(theme.SPACE_4, theme.SPACE_1))

    def _center(self, master) -> None:
        try:
            self.update_idletasks()
            w, h = max(self.winfo_reqwidth(), 560), self.winfo_reqheight()
            x = master.winfo_rootx() + (master.winfo_width() - w) // 2
            y = master.winfo_rooty() + 100
            self.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")
        except Exception:  # noqa: BLE001
            pass


def open_help(master, key: str) -> HelpDialog:
    return HelpDialog(master, key)
