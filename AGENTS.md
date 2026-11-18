# AGENTS.md

## What this repo is

Scaffold only: **no application code, no package manifest, no build/test/lint config, no CI.**
Branch `main`, two commits, **no git remote** (work is local). Setup notes and team
workflow rules live in `README.md`.

Do not invent a stack or guess framework commands — confirm what is being built first.

## Shell environment (Windows / PowerShell)

`git` and `node` are installed, but **not on the PATH inherited by processes that started
before they were installed** — including OpenCode's own server. Inside such a shell,
`git` and `npx` fail with "not recognized". Refresh before use:

```powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
```

- git 2.56 — `C:\Program Files\Git\cmd\git.exe`
- node 26.13 / npm 11 — `C:\Program Files\nodejs`; until PATH is refreshed, `npx.cmd` dies with `'"node"' is not recognized`
- python 3.13 — plain `python`

## MCP server: `document-generator` (in `opencode.json`)

Local stdio server, `npx --yes document-generator-mcp@latest`, declared under `mcp.servers`.

- Writes `.docx` / `.pdf` into **`./generated_documents/`**, relative to the working
  directory. That folder is gitignored — never commit its output.
- Tools: `gerar_documento_word`, `gerar_documento_pdf`. **Parameters are Portuguese:**
  `nome_arquivo` (no extension), `titulo_documento`, `conteudo_principal`, `autor`,
  `formato` (`word` | `pdf` | `ambos`), `template`
  (`professional` | `minimalist` | `corporate` | `default`).
- Normalised tool names are `document_generator_*`.
- Gotcha: a session that started before this server was configured will not list those
  tools even though the server connects fine. Start a new session, or drive it over
  stdio: `initialize` → `notifications/initialized` → `tools/call`.
- Avoid the upstream snippet's `--cache /tmp/.npx-cache`: `/tmp` is not a real Windows
  path. It exists only to work around a stale-cache bug (`use strict: not found`).

## Skills

Installed globally in `~/.agents/skills`: `brainstorming`, `frontend-design`,
`web-design-guidelines`, `systematic-debugging`, `vercel-react-best-practices`.

`vercel-react-best-practices` ships as `AGENTS.md` + `rules/` with no `SKILL.md`, so it is
**not** loadable as a skill — copy it into a project as `AGENTS.md` if React is chosen.

## Git notes

`LF will be replaced by CRLF` warnings on `git add` are normal here; do not "fix" line
endings or add `.gitattributes` for it.
