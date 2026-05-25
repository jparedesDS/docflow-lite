# DocFlow Lite

Aplicación de escritorio para Document Control en proyectos de ingeniería. Versión standalone (sin servidor) del sistema **DocFlow**, optimizada para uso individual con persistencia local.

> Hecho con ❤️ por [jparedesDS](https://jparedesds.github.io/) · © 2026 · Todos los derechos reservados

---

## ✨ Características

### 🏠 Dashboard
Saludo personalizado, KPIs en vivo (docs totales, pendientes, críticos, reclamables, tareas, inbox), accesos rápidos a todas las secciones.

### 📋 Agenda
Tareas, notas y reuniones en tres pestañas. Sincronización automática de tareas con los documentos pendientes asignados a ti.

### ✦ Bandeja AI
Lectura del buzón IMAP con filtros (todos / leídos / no leídos), preview del cuerpo del correo. Soporta clasificación con Claude (Anthropic) cuando hay API key configurada.

### ◫ Documentos
Vista de monitoring con KPIs filtrables, 12 columnas con scroll horizontal, ordenación, paginación 30/p y detalle por documento. Replica funcional del Documents.js del DocFlow web.

### ✉ Devoluciones
Parser de correos para 6 plataformas (**TR, GAIA, ACONEX, SENDOC, PRODOC, DOCUMENT SPACE**). Edición manual de Estado por documento mediante menú emergente. Preview del email antes de enviar. Envío por SMTP con guardado opcional en carpeta de pedido.

### ⚠ Reclamaciones
Sistema de escalation en 3 niveles (Recordatorio · Formal · Urgente). Selección por documento con checkbox toggleable (`☑/☐`). Persistencia de destinatarios por pedido. Envío masivo. Preview del email antes de enviar.

### 📊 Centro de Reportes
- **Excels**: Monitoring Report multi-hoja con STATUS GLOBAL + gráfico · Export simple
- **Resúmenes por email**: Ejecutivo (con IA) · Personal por DC (con selector de usuario)
- **Programados**: APScheduler en background con CRUD JSON local

### 🎨 Light / Dark mode
Persistencia en `state/preferences.json`, toggle desde la sidebar, reinicio limpio.

---

## 🚀 Instalación rápida

### Requisitos
- **Python 3.10+** (Windows / macOS / Linux)
- Acceso IMAP/SMTP para Devoluciones y Reclamaciones
- *(Opcional)* `ANTHROPIC_API_KEY` para Bandeja AI y resúmenes con IA

### Pasos

```bash
git clone https://github.com/jparedesDS/docflow-lite.git
cd docflow-lite

# Crear entorno virtual
python -m venv .venv

# Activar (Windows PowerShell)
.\.venv\Scripts\Activate.ps1
# Activar (macOS/Linux)
source .venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar credenciales
cp .env.example .env
# Editar .env y rellenar IMAP_PASS y SMTP_PASS

# Copiar tus Excels al directorio data/
cp /ruta/a/data_erp.xlsx data/
cp /ruta/a/consulta_erp.xlsx data/

# Arrancar
python app.py
```

---

## ⌨️ Atajos de teclado

| Tecla | Sección |
|:-----:|:--------|
| `H` | Inicio |
| `A` | Agenda |
| `I` | Bandeja AI |
| `O` | D**o**cumentos |
| `D` | Devoluciones |
| `R` | Reclamaciones |
| `P` | Centro de Re**p**ortes |
| `Esc` | Cerrar modal / volver |

> Los atajos respetan el foco: no se disparan cuando estás escribiendo en un campo de texto.

---

## 📂 Estructura del proyecto

```
docflow-lite/
├── app.py                         # Entry point: lanza GUI + scheduler
├── requirements.txt
├── .env.example
├── core/
│   ├── config.py                  # IMAP/SMTP + paths + USERS
│   ├── preferences.py             # Tema persistido
│   ├── paths.py                   # Resolución de rutas (dev + .exe)
│   ├── parsers/                   # 6 parsers de correo
│   │   ├── tr_parser.py
│   │   ├── gaia_parser.py
│   │   ├── aconex_parser.py
│   │   ├── sendoc_parser.py
│   │   ├── prodoc_parser.py
│   │   ├── docspace_parser.py
│   │   └── base_parser.py
│   ├── services/
│   │   ├── imap.py · smtp.py
│   │   ├── monitoring.py          # Cruza data_erp + consulta_erp
│   │   ├── transmittal.py         # Orquestador de devoluciones
│   │   ├── claims.py              # Reclamaciones 3 niveles
│   │   ├── inbox.py               # Lectura buzón
│   │   ├── agenda.py              # Tareas/Notas/Reuniones
│   │   ├── reports.py             # Excels (Monitoring + Export)
│   │   ├── weekly_summary.py      # Emails ejecutivo + personal
│   │   └── scheduled_reports.py   # APScheduler + CRUD JSON
│   └── utils/json_store.py        # Locking cross-platform
├── gui/
│   ├── app.py                     # Ventana principal + routing
│   ├── theme.py                   # Paletas Light + Dark
│   ├── widgets/
│   │   ├── sidebar.py
│   │   └── table.py               # DataTable con scroll horizontal
│   └── views/
│       ├── home.py
│       ├── agenda.py
│       ├── inbox.py
│       ├── documentos.py
│       ├── devoluciones.py
│       ├── reclamaciones.py
│       └── reportes.py
├── data/                          # data_erp.xlsx, consulta_erp.xlsx
└── state/                         # JSONs runtime (agenda, claims_log, prefs…)
```

---

## 🔧 Variables de entorno (`.env`)

```bash
# IMAP/SMTP (obligatorias para Devoluciones, Reclamaciones e Inbox)
IMAP_HOST=imap.tuservidor.com
IMAP_PORT=993
IMAP_USER=tu-email@dominio.com
IMAP_PASS=tu-password

SMTP_HOST=smtp.tuservidor.com
SMTP_PORT=465
SMTP_USER=tu-email@dominio.com
SMTP_PASS=tu-password

# Claude API (opcional — activa Bandeja AI y párrafo IA del ejecutivo)
ANTHROPIC_API_KEY=sk-ant-...

# Destinatarios por defecto del resumen ejecutivo (opcional)
WEEKLY_EXECUTIVE_RECIPIENTS=director@empresa.com,jefe@empresa.com

# Carpeta de pedidos en red (opcional — guarda .eml en 02 DEVOLUCIONES / 03 RECLAMACIONES)
PEDIDOS_BASE_PATH=M:\base de datos de pedidos
```

---

## 🧰 Stack técnico

- **GUI**: CustomTkinter 5 (Tkinter modernizado, sin Chromium ni .NET)
- **Datos**: pandas + openpyxl
- **Email**: imaplib + smtplib + tnefparse + striprtf
- **HTML parsing**: lxml + BeautifulSoup
- **Scheduler**: APScheduler (BackgroundScheduler)
- **AI** *(opcional)*: anthropic (Claude)
- **Empaquetado**: PyInstaller (`build.spec`)

---

## 📜 Licencia

© 2026 [jparedesDS](https://jparedesds.github.io/). **Todos los derechos reservados.**

Este software es de uso personal. No se concede permiso para copiar, modificar, redistribuir ni explotar comercialmente sin autorización expresa del autor.

---

## 🔗 Enlaces

- 🌐 **Portfolio**: [jparedesds.github.io](https://jparedesds.github.io/)
- 💼 **GitHub**: [@jparedesDS](https://github.com/jparedesDS)
