# Gastos Mensuales — Agent Instructions

Personal expense dashboard for Tomás Norman. Single-page app + Python mail reader + Telegram bot.

## Architecture

- **`index.html`** — The entire dashboard. Single HTML file (CSS + JS inline). Deployed on GitHub Pages. THIS IS THE MAIN APP.
- **`gastos.json`** — Expense data source of truth. Lives on GitHub repo. Updated via GitHub Contents API (PUT with SHA).
- **`config.json`** — Recurring expense definitions. Also lives on GitHub. Same API pattern.
- **No build step.** Open `index.html` directly or via GitHub Pages. No bundler, no npm.

## Data Flow

```
iPhone/PC browser → index.html → GitHub Contents API → gastos.json / config.json
Python scripts (local) → Gmail IMAP → manual update → push to GitHub
Telegram bot → telegram_bot.py → GitHub Contents API → gastos.json
```

The dashboard has NO backend server in production. All CRUD goes through GitHub API directly from the browser using a Personal Access Token stored in `localStorage`.

## GitHub API Pattern (CRITICAL)

All save operations use `ghGet()` + `ghPut()` with SHA tracking. The `shaCache` object persists the latest SHA to prevent 409 conflicts:

1. `ghGet(file)` → returns `{content, sha}` and caches `sha` in `shaCache[file]`
2. `ghPut(file, content, sha, msg)` → updates cache after successful PUT
3. On 401/403: clears bad token and prompts for new one (`ensureToken(true)`)
4. On 409: shows clear error message asking user to retry

**Bug history**: Previous versions had `if(API_AVAILABLE)` guards that skipped GitHub API calls on iPhone (where `API_AVAILABLE=false`). This caused edits to be lost on refresh. The current code ALWAYS calls GitHub API regardless of `API_AVAILABLE`.

## Mail Reading

- `leer_mails.py` — Reads Gmail via IMAP (App Password: stored separately). Outputs to `mails_resultado.txt` (gitignored). Run manually; agent parses output and updates `gastos.json` via GitHub API.
- `check_mails.py` — Automated version for scheduled execution (Windows Task Scheduler).
- `leer_detalle.py` — Detailed mail reader for specific senders.
- **Gmail App Password** is `wjpj bolj qbvl wykd` for `tominorman@gmail.com` IMAP.
- Key sender emails are in `config.json` under `gastos_recurrentes[].gmail_busqueda` and also hardcoded in `leer_mails.py`.
- **EPE is bimonthly** — each invoice has 2 installments with different due dates. Track both separately.
- **Bank emails (Credicoop, Banco Julio, eresumen.com)** send HTML emails with no structured plain text. Amounts and dates must be extracted from HTML.

## GitHub Repo

- Repo: `70miboy/gastos-mensuales` (public, required for free GitHub Pages)
- Live URL: `https://70miboy.github.io/gastos-mensuales/`
- GitHub Pages cache: ~2-5 minutes before changes appear
- **Never commit `gh_token.txt` or `telegram_bot_token.txt`.** They're in `.gitignore`.

## Conventions

- Currency: ARS (pesos argentinos). Format: `$ 1.234.567` with `toLocaleString('es-AR')`
- Dates: `YYYY-MM-DD` in JSON, displayed as `DD/MM` in dashboard
- Month keys: `YYYY-MM` format (e.g., `2026-05`)
- Calendar events: always at 08:00 AM (never midnight). URL uses `src=tominorman@gmail.com` to target that specific calendar.
- Category mapping in code: `tarjeta_credito` (in config) → `tarjeta` (in UI). `getConfigGastos()` handles this.

## Python Scripts

- Run with `python script_name.py` (Python 3.13, PowerShell on Windows)
- All scripts need `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')` to avoid encoding errors on Windows
- `actualizar_datos.py` updates `gastos.json` via GitHub API — requires `gh_token.txt` in project root
- `telegram_bot.py` — short-polling Telegram bot, no `python-telegram-bot` dependency

## Key Sender Emails (for mail scanning)

- `estudio.ormachea@gmail.com` — Accountant (IIBB, IVA, honorarios)
- `diegoormachea@hotmail.com` — Diego Ormachea (honorarios)
- `info@eresumen.com` — Visa NBSF resumen
- `asociados@bancocredicoop.coop` — Bank card resumenes
- `mensajesyalertas@bancocredicoop.coop` — Card payment alerts/deadlines
- `banco@bancojulio.com.ar` — Banco Julio
- `noreply@consorcioabierto.com` — Ubajay expensas
- `oficinavirtual@epe.santafe.gov.ar` — EPE electricity

## Known Limitations

- **PDF attachments** from bank emails can't be parsed by IMAP text extraction. Only plain text/HTML content is processed.
- **Master Patagonia (Joana)** and **Master Mercado Pago** — no emails arrive at `tominorman@gmail.com`. Need Joana's email or app access.
- **gastos.json encoding**: local file may have Mojibake due to Windows `cp1252` vs UTF-8. Always use `ensure_ascii=False` when writing via GitHub API.