# Project Echo

> ⚡ A terminal UI coding assistant powered by local LLMs — private, fast, extensible with skills, and yours.
>
> ⚡ Un asistente de programación con interfaz de terminal impulsado por LLMs locales — privado, rápido, extensible con skills, y tuyo.

---

🇬🇧 [English](#english) · 🇪🇸 [Español](#español)

---

## English

### What is Project Echo?

Project Echo is a terminal UI (TUI) coding assistant that runs entirely on your machine. It connects to a local LLM server — [Ollama](https://ollama.com) or any OpenAI-compatible endpoint (LM Studio, llama.cpp, vLLM) — and lets you chat about your code, create and edit files, run commands, and search your project, all without your code ever leaving your computer.

Every file operation is sandboxed to your project root and requires your explicit confirmation through an interactive action card before anything touches the disk.

### Features

- **Chat with your codebase** — Echo knows your project tree, recent actions, and remembered facts, and includes them as context in every conversation.
- **File operations with confirmation cards** — when the model wants to create, edit, delete, or move a file, you get a card with a content preview and **Apply / Reject / Edit** buttons. Nothing is written without your approval.
- **Skills system** — teach Echo reusable behaviors with simple markdown files, compatible with the [github.com/anthropics/skills](https://github.com/anthropics/skills) format. Activate several at once, install skill packs straight from GitHub, and let Echo write new skills from your conversations. See [Skills](#skills) below.
- **Thinking indicators** — animated spinners show what Echo is doing in real time (thinking, streaming, reading/creating/editing files, running commands), in the chat and in the top bar. Input is never blocked — you can keep typing while Echo works.
- **Persistent configuration** — tune behavior with `/config` (confirmation cards, streaming, history window, default mode, …); every change saves immediately to `~/.echo/config.json` and applies without restart. `Ctrl+A` toggles auto-apply on the spot.
- **Build / Plan modes** — ▶ BUILD lets the model modify files; ◎ PLAN is pure conversation: no tools are sent to the model and no actions are parsed, so you can discuss and design freely. The conversation is saved either way — plan first, then switch to Build and Echo remembers everything that was planned.
- **Native tool calling + text fallback** — models with tool support (⚡) use Ollama's native tool calls; models that answer in plain text are covered by a parser that extracts ` ```action ` blocks, JSON blocks, and tool-call-shaped JSON.
- **Sandboxed executor** — all paths are resolved and verified against the project root; path traversal (`../`) and absolute escapes are rejected. Shell commands run with a 60-second timeout.
- **Dual memory system** — per-project memory (conversations, file index, facts, action log) in `.echo/memory.db` with a human-readable `.echo/memory.md` mirror, plus global preferences in `~/.echo/preferences.md`.
- **Undo** — every applied file action pushes its inverse onto an undo stack; `/undo` reverts the last change.
- **Streaming responses** — token-by-token output in the chat as the model generates.
- **Model picker** — switch models on the fly with `Ctrl+S`; conversation history is preserved across switches.
- **Two providers** — Ollama out of the box, or any OpenAI-compatible server via config.

### Installation

Requirements: **Windows / macOS / Linux**, **Python 3.10+**, and a running LLM server (e.g. Ollama).

```bash
# 1. Get a local model server and a model
ollama pull qwen2.5-coder:14b

# 2. Install Project Echo
cd project-echo
pip install -e .
```

### Launching

```bash
# Primary command
pe                          # launch in the current directory
pe C:\path\to\your\project  # launch in a specific project

pe --help
pe --version
```

`pecho` and `project-echo` are aliases for the same command, and `python -m echo` also works. (The command was renamed from `echo` because `echo` is a built-in in PowerShell, cmd, and every Unix shell.)

On startup Echo shows your project tree and connects to the model server (a green ● in the top bar means connected). Type a message to chat, or ask for changes — e.g. *"create a hello.py that prints the current time"* — and apply the resulting action card.

### Skills

Skills are reusable instruction sets that shape how Echo behaves — coding conventions, review checklists, domain knowledge. Each skill is a folder containing a `SKILL.md` with YAML frontmatter, **compatible with the [anthropics/skills](https://github.com/anthropics/skills) format**:

```markdown
---
name: python-best-practices
description: Enforce Python best practices when writing code
---
# Python Best Practices
- Always use type hints on all functions
- Use pathlib instead of os.path
...
```

**Where skills live** (both locations are scanned):

| Location | Path | Scope |
|---|---|---|
| Global | `~/.echo/skills/<name>/SKILL.md` | available in every project |
| Project | `<project>/.echo/skills/<name>/SKILL.md` | this project only — **overrides a global skill with the same name** |

**Using multiple skills simultaneously** — any number of skills can be active at once. All active skills are concatenated and prepended to the system prompt (global skills load first, project skills after). They stay active for every message until you deactivate them, and the top bar shows `✦ N skills` while any are active.

```text
/skills                      list all available skills (global + project, ✦ = active)
/skills active               list only the currently active skills
/skill python-best-practices activate a skill
/skill code-review           activate another one — both are now active
/skill off code-review       deactivate one specific skill
/skill off                   deactivate ALL skills
```

**Echo creates skills from conversation** — after discussing conventions, patterns, or decisions, capture them as a permanent skill:

```text
/skill save api-conventions           save to this project's .echo/skills/
/skill save --global api-conventions  save to ~/.echo/skills/ for all projects
```

Echo analyzes the conversation, generates the `SKILL.md`, saves it, and activates it immediately.

**Installing skills from GitHub** — no git required, only the GitHub API:

```text
/skill install https://github.com/anthropics/skills
    finds every SKILL.md in the repo and installs each one globally

/skill install https://github.com/anthropics/skills/tree/main/skills/pdf
    installs just one skill from a folder URL

/skill install <url> --project
    same, but into this project's .echo/skills/ instead of ~/.echo/skills/

/skill uninstall <name>
    removes an installed skill (asks for confirmation first)

/skill update
    re-downloads every skill that was installed from a URL
```

Progress is shown live as each skill downloads:

```text
Installing skills from github.com/anthropics/skills...
✓ python-best-practices
✗ broken-skill (no SKILL.md found)
Installed 2 of 3 skills
```

Each installed skill gets an `echo-meta.json` recording its source URL and install date — that's what `/skill update` uses to refresh them.

Two starter skills ship preinstalled (`python-best-practices`, `code-review`), and the official Anthropic skills (pdf, docx, xlsx, mcp-builder, frontend-design, …) install directly with `/skill install https://github.com/anthropics/skills` since the format is identical.

### Thinking indicators

Echo always shows what it's doing, Claude Code-style. While waiting for the model, an animated spinner appears under the last message (`⠋ Thinking...`); it disappears the instant the first token arrives. When the model calls a tool you'll see what it's about to do (`⠋ Creating src/main.py...`, `⠋ Running: pytest...`) before the confirmation card appears. The right side of the top bar mirrors this: `●` when idle, `⠋ generating...` / `⠋ streaming...` / `⠋ creating file...` while working.

With `confirm_actions` off (auto-apply), cards are skipped and the spinner resolves into a result line instead:

```text
✓ Created src/main.py (1035 chars)
✗ Failed: pytest (exit 1)
```

### Configuration (`/config`)

Settings persist in `~/.echo/config.json`. Inspect or change them at runtime — every change saves immediately and applies without restart:

```text
/config                        show all settings
/config confirm_actions        show one setting
/config confirm_actions false  change it -> "✓ confirm_actions → false (saved)"
```

| Setting | Values | Default | Effect |
|---|---|---|---|
| `confirm_actions` | `true` / `false` | `true` | `true`: every action shows an Apply/Reject card. `false`: actions auto-execute with ✓/✗ result lines, and the top bar shows an **`[auto]`** badge. Toggle instantly with `Ctrl+A`. |
| `streaming` | `true` / `false` | `true` | `false` waits for the complete response before displaying it (spinner shows the whole time). |
| `auto_close_session` | `true` / `false` | `true` | On exit, writes a session summary (messages, actions, mode) to global memory. |
| `include_context_default` | `true` / `false` | `true` | `false` sends a minimal system prompt without the project tree/facts (faster on slow models). |
| `max_history` | number ≥ 0 | `20` | How many conversation messages are sent to the model; read fresh on every message. `0` = unlimited. |
| `mode` | `build` / `plan` | `build` | Startup mode; changing it switches mode immediately. |
| `theme` | `dark` | `dark` | Color theme (dark only, for now). |

### Slash commands

| Command | Description |
|---|---|
| `/help` | Show help |
| `/tree` | Show the project tree |
| `/read <path>` | Show a file |
| `/search <text>` | Search project files (case-insensitive) |
| `/run <cmd>` | Run a shell command (60 s timeout) |
| `/clear` | Clear the conversation |
| `/memory` | Show project memory (facts, recent actions) |
| `/plan` | Switch to PLAN mode (pure conversation) |
| `/build` | Switch to BUILD mode |
| `/models` | List available models |
| `/model <name>` | Switch model (history preserved) |
| `/skills` | List available skills · `/skills active` lists active ones |
| `/skill <name>` | Activate a skill |
| `/skill off [name]` | Deactivate all skills, or one by name |
| `/skill save [--global] <name>` | Create a skill from this conversation |
| `/skill install <url> [--project]` | Install skills from a GitHub repo or folder URL |
| `/skill uninstall <name>` | Remove an installed skill (with confirmation) |
| `/skill update` | Re-download all URL-installed skills |
| `/config [<key> [<value>]]` | Show or change settings (see Configuration) |
| `/undo` | Undo the last applied file action |
| `/prefs` | Show global preferences (`~/.echo/preferences.md`) |

### Keyboard shortcuts

| Keys | Action |
|---|---|
| `Ctrl+M` | Toggle Build/Plan mode * |
| `Ctrl+S` | Open the model picker |
| `Ctrl+A` | Toggle `confirm_actions` (cards ↔ auto-apply, `[auto]` badge updates instantly) |
| `Ctrl+L` | Clear the conversation |
| `Ctrl+T` | Show the project tree |
| `Ctrl+C` | Quit |

\* Most terminals send `Ctrl+M` as Enter; if it doesn't trigger, use `/plan` and `/build`.

### Supported models

Any model your server can run will work for chat. Models from these families are detected as **tool-capable** and receive native tool definitions — they're marked with **⚡** in the top bar and the model picker:

`qwen2.5` · `qwen2.5-coder` · `qwen3` · `llama3.1` · `llama3.2` · `llama3.3` · `mistral-nemo` · `deepseek-coder-v2` · `hermes3`

Other models (and tool-capable models that reply in plain text — qwen2.5-coder often does) still create files through the action-block fallback parser. **Recommended:** `qwen2.5-coder:14b` or larger for the best code quality.

### Provider configuration

Connection settings live in the same `~/.echo/config.json` (edit the file directly for these):

```json
{
  "provider": "ollama",
  "base_url": "http://localhost",
  "port": 11434,
  "model": "qwen2.5-coder:14b"
}
```

Set `"provider": "openai"` (with the matching `port`, and `api_key` if needed) for LM Studio, llama.cpp server, vLLM, etc. Behavior settings are managed with `/config` — see the table above.

### Troubleshooting

| Symptom | Fix |
|---|---|
| Red ● in the top bar / "Could not reach server" | Start your server (`ollama serve`) and check `base_url`/`port` in `~/.echo/config.json`. |
| "No models available" | Pull one: `ollama pull qwen2.5-coder:14b`, then `Ctrl+S`. |
| Model writes code but no action card appears | Check `.echo/debug.log` in your project — it records the request, tool calls, parsing, and card mounting for every exchange. |
| `pe` not found | Make sure Python's `Scripts` directory is on PATH, or use `python -m echo`. |
| `Ctrl+M` does nothing | Your terminal sends it as Enter — use `/plan` and `/build` instead. |
| A skill doesn't show up in `/skills` | The folder must contain a `SKILL.md` with `name:` in its frontmatter, directly under the skills directory. |
| Slow responses | Try a smaller model (`qwen2.5-coder:7b`), or check GPU usage — CPU-only inference is slow for 14b+. |

---

## Español

### ¿Qué es Project Echo?

Project Echo es un asistente de programación con interfaz de terminal (TUI) que funciona completamente en tu máquina. Se conecta a un servidor de LLM local — [Ollama](https://ollama.com) o cualquier endpoint compatible con OpenAI (LM Studio, llama.cpp, vLLM) — y te permite conversar sobre tu código, crear y editar archivos, ejecutar comandos y buscar en tu proyecto, sin que tu código salga nunca de tu computadora.

Cada operación de archivos está aislada (sandbox) dentro de la raíz del proyecto y requiere tu confirmación explícita mediante una tarjeta de acción interactiva antes de tocar el disco.

### Características

- **Conversa con tu código** — Echo conoce el árbol de tu proyecto, las acciones recientes y los datos memorizados, y los incluye como contexto en cada conversación.
- **Operaciones de archivos con tarjetas de confirmación** — cuando el modelo quiere crear, editar, borrar o mover un archivo, aparece una tarjeta con vista previa y botones **Apply / Reject / Edit**. No se escribe nada sin tu aprobación.
- **Sistema de skills** — enséñale a Echo comportamientos reutilizables con simples archivos markdown, compatible con el formato de [github.com/anthropics/skills](https://github.com/anthropics/skills). Activa varios a la vez, instala packs de skills directamente desde GitHub, y deja que Echo escriba skills nuevos a partir de tus conversaciones. Ver [Skills](#skills-1) abajo.
- **Indicadores de actividad** — spinners animados muestran qué está haciendo Echo en tiempo real (pensando, streaming, leyendo/creando/editando archivos, ejecutando comandos), en el chat y en la barra superior. La entrada nunca se bloquea — puedes seguir escribiendo mientras Echo trabaja.
- **Configuración persistente** — ajusta el comportamiento con `/config` (tarjetas de confirmación, streaming, ventana de historial, modo por defecto, …); cada cambio se guarda al instante en `~/.echo/config.json` y se aplica sin reiniciar. `Ctrl+A` alterna el auto-aplicar al momento.
- **Modos Build / Plan** — ▶ BUILD permite al modelo modificar archivos; ◎ PLAN es conversación pura: no se envían herramientas al modelo ni se parsean acciones, para discutir y diseñar con libertad. La conversación se guarda igualmente — planifica primero, cambia a Build y Echo recuerda todo lo planificado.
- **Tool calling nativo + fallback de texto** — los modelos con soporte de herramientas (⚡) usan las tool calls nativas de Ollama; los que responden en texto plano están cubiertos por un parser que extrae bloques ` ```action `, bloques JSON y JSON con forma de tool call.
- **Ejecutor con sandbox** — todas las rutas se verifican contra la raíz del proyecto; se rechazan el path traversal (`../`) y los escapes absolutos. Los comandos de shell tienen un límite de 60 segundos.
- **Sistema de memoria dual** — memoria por proyecto (conversaciones, índice de archivos, datos, registro de acciones) en `.echo/memory.db` con un espejo legible en `.echo/memory.md`, más preferencias globales en `~/.echo/preferences.md`.
- **Deshacer** — cada acción aplicada guarda su inversa en una pila; `/undo` revierte el último cambio.
- **Respuestas en streaming** — la salida aparece token a token mientras el modelo genera.
- **Selector de modelos** — cambia de modelo al instante con `Ctrl+S`; el historial se conserva.
- **Dos proveedores** — Ollama de fábrica, o cualquier servidor compatible con OpenAI vía configuración.

### Instalación

Requisitos: **Windows / macOS / Linux**, **Python 3.10+** y un servidor de LLM en ejecución (por ej. Ollama).

```bash
# 1. Consigue un servidor de modelos local y un modelo
ollama pull qwen2.5-coder:14b

# 2. Instala Project Echo
cd project-echo
pip install -e .
```

### Cómo iniciarlo

```bash
# Comando principal
pe                          # iniciar en el directorio actual
pe C:\ruta\a\tu\proyecto    # iniciar en un proyecto específico

pe --help
pe --version
```

`pecho` y `project-echo` son alias del mismo comando, y `python -m echo` también funciona. (El comando se renombró desde `echo` porque `echo` es un comando integrado en PowerShell, cmd y todas las shells de Unix.)

Al iniciar, Echo muestra el árbol del proyecto y se conecta al servidor de modelos (un ● verde en la barra superior indica conexión). Escribe un mensaje para conversar, o pide cambios — por ej. *"crea un hello.py que imprima la hora actual"* — y aplica la tarjeta de acción resultante.

### Skills

Los skills son conjuntos de instrucciones reutilizables que moldean el comportamiento de Echo — convenciones de código, listas de revisión, conocimiento de dominio. Cada skill es una carpeta con un `SKILL.md` con frontmatter YAML, **compatible con el formato de [anthropics/skills](https://github.com/anthropics/skills)**:

```markdown
---
name: python-best-practices
description: Enforce Python best practices when writing code
---
# Python Best Practices
- Always use type hints on all functions
- Use pathlib instead of os.path
...
```

**Dónde viven los skills** (se escanean ambas ubicaciones):

| Ubicación | Ruta | Alcance |
|---|---|---|
| Global | `~/.echo/skills/<nombre>/SKILL.md` | disponible en todos los proyectos |
| Proyecto | `<proyecto>/.echo/skills/<nombre>/SKILL.md` | solo este proyecto — **sobreescribe un skill global con el mismo nombre** |

**Varios skills a la vez** — puede haber cualquier cantidad de skills activos simultáneamente. Todos los skills activos se concatenan y se anteponen al system prompt (los globales cargan primero, los de proyecto después). Permanecen activos en cada mensaje hasta que los desactives, y la barra superior muestra `✦ N skills` mientras haya alguno activo.

```text
/skills                      listar todos los skills (global + proyecto, ✦ = activo)
/skills active               listar solo los skills activos
/skill python-best-practices activar un skill
/skill code-review           activar otro — ahora ambos están activos
/skill off code-review       desactivar un skill específico
/skill off                   desactivar TODOS los skills
```

**Echo crea skills desde la conversación** — después de discutir convenciones, patrones o decisiones, captúralos como un skill permanente:

```text
/skill save api-conventions           guardar en .echo/skills/ del proyecto
/skill save --global api-conventions  guardar en ~/.echo/skills/ para todos los proyectos
```

Echo analiza la conversación, genera el `SKILL.md`, lo guarda y lo activa inmediatamente.

**Instalar skills desde GitHub** — sin git, solo la API de GitHub:

```text
/skill install https://github.com/anthropics/skills
    encuentra cada SKILL.md del repositorio y los instala globalmente

/skill install https://github.com/anthropics/skills/tree/main/skills/pdf
    instala un solo skill desde la URL de una carpeta

/skill install <url> --project
    igual, pero en el .echo/skills/ de este proyecto en vez de ~/.echo/skills/

/skill uninstall <nombre>
    elimina un skill instalado (pide confirmación primero)

/skill update
    vuelve a descargar todos los skills instalados desde una URL
```

El progreso se muestra en vivo mientras se descarga cada skill:

```text
Installing skills from github.com/anthropics/skills...
✓ python-best-practices
✗ broken-skill (no SKILL.md found)
Installed 2 of 3 skills
```

Cada skill instalado guarda un `echo-meta.json` con su URL de origen y fecha de instalación — eso es lo que usa `/skill update` para refrescarlos.

Vienen dos skills de ejemplo preinstalados (`python-best-practices`, `code-review`), y los skills oficiales de Anthropic (pdf, docx, xlsx, mcp-builder, frontend-design, …) se instalan directamente con `/skill install https://github.com/anthropics/skills` porque el formato es idéntico.

### Indicadores de actividad

Echo siempre muestra qué está haciendo, al estilo Claude Code. Mientras espera al modelo, aparece un spinner animado bajo el último mensaje (`⠋ Thinking...`); desaparece en el instante en que llega el primer token. Cuando el modelo llama a una herramienta verás qué va a hacer (`⠋ Creating src/main.py...`, `⠋ Running: pytest...`) antes de que aparezca la tarjeta de confirmación. El lado derecho de la barra superior refleja lo mismo: `●` en reposo, `⠋ generating...` / `⠋ streaming...` / `⠋ creating file...` mientras trabaja.

Con `confirm_actions` desactivado (auto-aplicar), no hay tarjetas y el spinner se convierte en una línea de resultado:

```text
✓ Created src/main.py (1035 chars)
✗ Failed: pytest (exit 1)
```

### Configuración (`/config`)

Los ajustes persisten en `~/.echo/config.json`. Consúltalos o cámbialos en caliente — cada cambio se guarda al instante y se aplica sin reiniciar:

```text
/config                        mostrar todos los ajustes
/config confirm_actions        mostrar un ajuste
/config confirm_actions false  cambiarlo -> "✓ confirm_actions → false (saved)"
```

| Ajuste | Valores | Por defecto | Efecto |
|---|---|---|---|
| `confirm_actions` | `true` / `false` | `true` | `true`: cada acción muestra una tarjeta Apply/Reject. `false`: las acciones se ejecutan solas con líneas ✓/✗, y la barra superior muestra la insignia **`[auto]`**. Se alterna al instante con `Ctrl+A`. |
| `streaming` | `true` / `false` | `true` | `false` espera la respuesta completa antes de mostrarla (el spinner se ve todo el tiempo). |
| `auto_close_session` | `true` / `false` | `true` | Al salir, escribe un resumen de la sesión (mensajes, acciones, modo) en la memoria global. |
| `include_context_default` | `true` / `false` | `true` | `false` envía un system prompt mínimo sin árbol/datos del proyecto (más rápido en modelos lentos). |
| `max_history` | número ≥ 0 | `20` | Cuántos mensajes de la conversación se envían al modelo; se lee fresco en cada mensaje. `0` = sin límite. |
| `mode` | `build` / `plan` | `build` | Modo de inicio; cambiarlo conmuta el modo inmediatamente. |
| `theme` | `dark` | `dark` | Tema de color (solo dark, por ahora). |

### Comandos slash

| Comando | Descripción |
|---|---|
| `/help` | Mostrar ayuda |
| `/tree` | Mostrar el árbol del proyecto |
| `/read <ruta>` | Mostrar un archivo |
| `/search <texto>` | Buscar en los archivos del proyecto |
| `/run <cmd>` | Ejecutar un comando de shell (límite de 60 s) |
| `/clear` | Limpiar la conversación |
| `/memory` | Mostrar la memoria del proyecto |
| `/plan` | Cambiar a modo PLAN (conversación pura) |
| `/build` | Cambiar a modo BUILD |
| `/models` | Listar los modelos disponibles |
| `/model <nombre>` | Cambiar de modelo (se conserva el historial) |
| `/skills` | Listar skills · `/skills active` lista los activos |
| `/skill <nombre>` | Activar un skill |
| `/skill off [nombre]` | Desactivar todos los skills, o uno por nombre |
| `/skill save [--global] <nombre>` | Crear un skill a partir de esta conversación |
| `/skill install <url> [--project]` | Instalar skills desde un repo o carpeta de GitHub |
| `/skill uninstall <nombre>` | Eliminar un skill instalado (con confirmación) |
| `/skill update` | Volver a descargar los skills instalados por URL |
| `/config [<clave> [<valor>]]` | Mostrar o cambiar ajustes (ver Configuración) |
| `/undo` | Deshacer la última acción de archivo aplicada |
| `/prefs` | Mostrar las preferencias globales (`~/.echo/preferences.md`) |

### Atajos de teclado

| Teclas | Acción |
|---|---|
| `Ctrl+M` | Alternar modo Build/Plan * |
| `Ctrl+S` | Abrir el selector de modelos |
| `Ctrl+A` | Alternar `confirm_actions` (tarjetas ↔ auto-aplicar, la insignia `[auto]` se actualiza al instante) |
| `Ctrl+L` | Limpiar la conversación |
| `Ctrl+T` | Mostrar el árbol del proyecto |
| `Ctrl+C` | Salir |

\* La mayoría de las terminales envían `Ctrl+M` como Enter; si no funciona, usa `/plan` y `/build`.

### Modelos soportados

Cualquier modelo que tu servidor pueda ejecutar sirve para conversar. Los modelos de estas familias se detectan como **compatibles con herramientas** y reciben las definiciones de tools nativas — se marcan con **⚡** en la barra superior y en el selector de modelos:

`qwen2.5` · `qwen2.5-coder` · `qwen3` · `llama3.1` · `llama3.2` · `llama3.3` · `mistral-nemo` · `deepseek-coder-v2` · `hermes3`

Los demás modelos (y los compatibles que respondan en texto plano — qwen2.5-coder suele hacerlo) también crean archivos gracias al parser de bloques de acción. **Recomendado:** `qwen2.5-coder:14b` o superior.

### Configuración del proveedor

Los ajustes de conexión viven en el mismo `~/.echo/config.json` (edita el archivo directamente para estos):

```json
{
  "provider": "ollama",
  "base_url": "http://localhost",
  "port": 11434,
  "model": "qwen2.5-coder:14b"
}
```

Usa `"provider": "openai"` (con el `port` correspondiente, y `api_key` si hace falta) para LM Studio, llama.cpp server, vLLM, etc. Los ajustes de comportamiento se gestionan con `/config` — ver la tabla de arriba.

### Solución de problemas

| Síntoma | Solución |
|---|---|
| ● rojo en la barra superior / "Could not reach server" | Inicia tu servidor (`ollama serve`) y revisa `base_url`/`port` en `~/.echo/config.json`. |
| "No models available" | Descarga uno: `ollama pull qwen2.5-coder:14b`, luego `Ctrl+S`. |
| El modelo escribe código pero no aparece la tarjeta de acción | Revisa `.echo/debug.log` en tu proyecto — registra la petición, las tool calls, el parseo y el montaje de tarjetas de cada intercambio. |
| `pe` no se encuentra | Asegúrate de que el directorio `Scripts` de Python esté en el PATH, o usa `python -m echo`. |
| `Ctrl+M` no hace nada | Tu terminal lo envía como Enter — usa `/plan` y `/build`. |
| Un skill no aparece en `/skills` | La carpeta debe contener un `SKILL.md` con `name:` en su frontmatter, directamente bajo el directorio de skills. |
| Respuestas lentas | Prueba un modelo más pequeño (`qwen2.5-coder:7b`), o revisa el uso de GPU — la inferencia solo con CPU es lenta para 14b+. |

---

Built with [Textual](https://textual.textualize.io/) · skills format by [anthropics/skills](https://github.com/anthropics/skills) · your code never leaves your machine.
