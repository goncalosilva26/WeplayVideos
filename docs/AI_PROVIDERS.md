# AI providers (optional)

Behance Studio is complete without AI. Every stage — asset recognition,
brief interpretation, narrative planning, layout and copy — has an offline
implementation based on measured image analysis and documented heuristics.
An AI provider can *refine* three things:

| Feature | What it does | What is sent |
| --- | --- | --- |
| Recognise asset types | Corrects asset types the offline heuristics are unsure about; adds a short visual description and tags | A small JPEG preview (max 640 px, re-encoded, no metadata) + the file name and folder name |
| Interpret the creative brief | Reads personality and mood from free-form brief text, for axes the brief does not state explicitly | The brief text |
| Draft section descriptions | Writes one or two neutral sentences for sections that have no user text | The brief text, project name, category, section titles and asset descriptions |

Nothing else uses AI. Layout, typography and composition are always computed
locally.

## Privacy and cost rules

* **Off by default.** With *Provider: None* no network request is ever made.
* **Per-project consent.** Even with a provider configured, nothing from a
  project is sent until you tick *Allow AI assistance for the current project*
  (Settings → AI assistance, with that project open). Exception: a *Local
  model* provider on this computer or your local network.
* **Images need a second switch.** Previews are only sent when *Allow sending
  downscaled asset previews* is also enabled. Original files are never sent.
* **Cost.** OpenAI and Anthropic bill per request. Behance Studio never makes
  a request you did not enable, caches every answer by content hash
  (an identical request is never sent twice: previews and the brief are
  analysed once per project; a new variation only drafts copy for sections
  whose content changed), stops after repeated failures, and
  sends at most 150 previews per generation. *Test connection* only lists the
  available models, which providers do not bill.
* **Keys.** Stored in Windows Credential Manager (or the system keyring), read
  from environment variables, or — if no vault exists — kept in memory for
  the session only. Keys are never written to settings, projects, logs or
  exports, and are only sent over HTTPS (plain HTTP is allowed only for a
  local server).
* **Content integrity.** Drafted copy passes a fact guard that rejects text
  containing numbers, percentages, awards, clients, results, superlatives or
  proper names that are not in your own material. Rejected drafts are
  discarded and the offline text is kept. Your own text (script, brief
  description, brand messages) is never replaced.
* **Graceful fallback.** Timeouts (60 s default), bounded retries with
  backoff for 429/5xx responses, and any error simply leave the offline
  result in place; the generation notes say what happened.

## Setup

Settings → **AI assistance**:

### OpenAI (or any OpenAI-compatible API)

* Provider: *OpenAI-compatible API*
* API address: `https://api.openai.com/v1` (or your gateway, e.g. OpenRouter
  `https://openrouter.ai/api/v1`)
* Model: a vision-capable model, e.g. `gpt-4.1-mini` (default)
* API key: paste it; it goes straight to the credential vault.
* Alternative: set `BEHANCE_STUDIO_OPENAI_API_KEY` (or `OPENAI_API_KEY`).

### Anthropic

* Provider: *Anthropic API (Claude)*
* API address: `https://api.anthropic.com`
* Model: e.g. `claude-sonnet-5-5` (default) — any model that accepts images
* API key, or `BEHANCE_STUDIO_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY`.

### Local model (no cost, nothing leaves your computer)

* Install [Ollama](https://ollama.com) and pull a vision model, e.g.
  `ollama pull llava` (or use LM Studio's OpenAI-compatible server).
* Provider: *Local model*; API address `http://localhost:11434/v1`
  (LM Studio: `http://localhost:1234/v1`); Model: `llava` (or the name shown
  by your server). No key needed.

Then press **Test connection**, choose which features to use, and allow AI
for the project.

## How results are shown

* Asset types that came from AI are labelled **AI** in the project grid;
  your manual corrections always win and are never overwritten.
* The project overview states whether AI is active for the project.
* Generation notes list what AI changed (or why it was skipped).
* AI answers are cached in `<project>\Cache\ai\` (delete the folder or use
  *Clear project cache* to ask again).

## Not implemented

* AI evaluation/critique of finished layouts (`use_for_evaluation` in the
  settings file is reserved and currently unused).
* Image generation or editing of any kind — Behance Studio only arranges your
  own material.
