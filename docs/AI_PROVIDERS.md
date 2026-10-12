# AI providers (optional)

Behance Studio is complete without AI. Every stage — asset recognition,
brief interpretation, creative direction, layout, copy and quality checks —
has an offline implementation based on measured image analysis and
documented rules. **The offline Creative Director is rules-based, not AI**,
and the app never describes it as AI.

With a provider configured, AI can take on five jobs:

| Feature | What it does | What is sent |
| --- | --- | --- |
| Recognise asset types | Corrects asset types the offline heuristics are unsure about; adds a short visual description and tags | A small JPEG preview (max 640 px, re-encoded, no metadata) + the file name and folder name |
| Interpret the creative brief | Reads personality and mood from free-form brief text, for axes the brief does not state explicitly | The brief text |
| **Direct the five concepts** (2.0) | Plans each concept's storyboard: which compositional module each section uses, which assets go where, where chapters and brand messages pause the story, what is left out and why | The brief, brand messages, measured facts and file names of the assets, the concept, the module catalogue, the offline director's draft — and, if previews are allowed, **one contact sheet** of small labelled previews (plus a sheet of your reference screenshots, if any) |
| Draft section descriptions | Writes one or two neutral sentences for sections that show a description and have no user text | The brief text, project name, category, section titles and asset descriptions |
| **Critique the rendered proposals** (2.0, off by default) | Looks at every rendered section and scores it against a fixed rubric (1–5, closed list of problems); the weakest flagged sections are recomposed once | Small JPEG crops of the rendered sections (max 512 px wide) |

Layout geometry, typography, rendering and export are always computed
locally.

## What the AI director can and cannot do

The AI director answers with a structured storyboard (a JSON schema; with
Anthropic models it is enforced by *structured outputs*). Behance Studio
validates every item before anything is composed:

* modules, asset handles, chapter names and message numbers that do not
  exist are discarded;
* finished artwork (posters, social posts, documents, screens) is never put
  into crop-only modules — if the director asks for that, the piece is staged
  instead;
* counts are clamped to what each module can show, masks are only used on
  photographs that can take them, an asset appears once (the primary logo may
  repeat), the cover comes first and the closing last;
* **the director cannot write presentation text.** Text comes from your
  brief (brand messages are referenced by number), from your script, or from
  the neutral offline copy. Its one-sentence "idea" and its reasons for
  leaving assets out are shown in the proposal notes inside the app only.

If too little of a storyboard survives validation, or the provider fails,
the offline director plans that concept — generation always completes. Each
saved proposal records which director planned it (`sources.director`:
`ai`, `local` or `classic`).

## AI critique (bounded)

When *Critique the rendered proposals* is on (and previews are allowed for
the project), each proposal's rendered sections are sent once. Sections
scored 1–2 with the action "recompose" (at most three per proposal) are
recomposed with an alternative module, re-rendered and **kept only if the
technical rendered checks do not get worse**. It is one round: the critique
is not repeated on the recomposed version, and the notes say so. The score
(`ai_critique`) and the critique are stored with the proposal.

## Costs, estimates and spending limits

* **Estimate before every paid generation.** The app lists the requests a
  generation would make (per step), the expected tokens and, when the
  model's price is known, the expected and maximum cost — then asks: *Use
  AI*, *Generate offline* or *Cancel*. (Settings → *Show the cost estimate
  and ask before every paid generation*.) The command line prints the same
  estimate and only uses a paid provider with `--allow-paid-ai`.
* **Prices.** Built in only where documented: Anthropic list prices
  (October 2026, USD per million tokens, input/output) — `claude-opus-5-5`
  4 / 20, `claude-sonnet-5-5` 2 / 10, `claude-haiku-5-5` 0.10 / 0.50,
  `claude-fable-5-1` 10 / 50. For any other cloud model enter your
  provider's prices in Settings; until then costs are shown as *unknown*.
* **Limits.** *Limit per generation* (default $1.00) and an optional
  *Monthly limit*. A request is only sent when the amount already spent plus
  its expected cost fits; once a limit is reached, the remaining AI steps are
  skipped and done offline. If a limit is set but the model's price is
  unknown, paid requests are not made at all (the limit could not be
  enforced).
* **Real usage.** Spending is computed from the token usage each response
  reports. Month-to-date usage (request counts, tokens, amounts — never
  content) is kept in `ai_usage.json` in the app data folder and shown in
  Settings.
* **Caching.** Every answer is cached by content hash in
  `<project>\Cache\ai\`: regenerating with the same material and seed sends
  nothing. On Anthropic, the context shared by the five concept requests is
  marked for prompt caching.
* **Typical cost** (Butter & Bean fixture, 25 assets, five concepts, critique
  on, list prices): about $1.05 with `claude-opus-5-5` (the default model),
  roughly half with `claude-sonnet-5-5`, a few cents with `claude-haiku-5-5`.
  These are the app's own estimates, not measured bills.

## Privacy rules

* **Off by default.** With *Provider: None* no network request is ever made.
* **Per-project consent.** Even with a provider configured, nothing from a
  project is sent until you tick *Allow AI assistance for the current
  project* (Settings → AI assistance, with that project open). Exception: a
  *Local model* provider on this computer or your local network.
* **Images need a second switch.** Previews, contact sheets and rendered
  sections are only sent when *Allow sending downscaled asset previews* is
  also enabled. Original files are never sent.
* **Keys.** Stored in Windows Credential Manager (or the system keyring),
  read from environment variables, or — if no vault exists — kept in memory
  for the session only. Keys are never written to settings, projects, logs or
  exports, and are only sent over HTTPS (plain HTTP is allowed only for a
  local server).
* **Content integrity.** Drafted copy passes a fact guard that rejects text
  containing numbers, percentages, awards, clients, results, superlatives or
  proper names that are not in your own material. Your own text (script,
  brief description, brand messages) is never replaced.
* **Graceful fallback.** Timeouts (60 s default), bounded retries with
  backoff for 429/5xx responses, and any error simply leave the offline
  result in place; the generation notes say what happened.

## Reference screenshots

Put screenshots of work you admire (for example a Behance case study) in a
folder named `References`, `Referências`, `Inspiration` or `Moodboard` and
import it. Those images get the type *Reference / inspiration* and are
**never placed in a presentation** (offline or with AI). When AI direction
and previews are allowed, they are sent to the AI director as one extra
sheet, as a guide to pacing and mood only. The offline director does not
interpret references.

## Setup

Settings → **AI assistance**:

### Anthropic (recommended for vision + structured output)

* Provider: *Anthropic API (Claude)*
* API address: `https://api.anthropic.com`
* Model: `claude-opus-5-5` (default), `claude-sonnet-5-5`, `claude-haiku-5-5`
  or `claude-fable-5-1` — the price of the chosen model is shown below the
  field.
* API key, or `BEHANCE_STUDIO_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY`.

Requests use the current Messages API: structured outputs
(`output_config.format`) for every JSON answer, `output_config.effort`
(`low` for recognition/copy/critique, `medium` for direction) to bound the
reasoning these models always do, and no sampling parameters (which current
models reject). If a gateway refuses `output_config`, the request is retried
once without it.

### OpenAI (or any OpenAI-compatible API)

* Provider: *OpenAI-compatible API*
* API address: `https://api.openai.com/v1` (or your gateway, e.g. OpenRouter
  `https://openrouter.ai/api/v1`)
* Model: a vision-capable model, e.g. `gpt-4.1-mini` (default)
* Enter the model's prices in Settings to see costs (no prices are built in).
* API key, or `BEHANCE_STUDIO_OPENAI_API_KEY` (or `OPENAI_API_KEY`).

### Local model (no cost, nothing leaves your computer)

* Install [Ollama](https://ollama.com) and pull a vision model, e.g.
  `ollama pull llava` (or use LM Studio's OpenAI-compatible server).
* Provider: *Local model*; API address `http://localhost:11434/v1`
  (LM Studio: `http://localhost:1234/v1`); Model: `llava` (or the name shown
  by your server). No key needed. Small local models often fail the
  storyboard validation; the offline director then takes over.

Then press **Test connection** (it only lists models, which is not billed),
choose which features to use, and allow AI for the project.

## Implementation note

The clients use the Python standard library only (one small HTTP layer for
three provider families, no extra dependencies in the Windows build). They
follow the documented request shapes, and are tested against a local mock
server (`tests/ai_mock.py`) — no real provider was called during
development, so behaviour against the live APIs is unverified.

## Not implemented

* Image generation or editing of any kind — Behance Studio only arranges your
  own material.
* A local vision model (CLIP/ONNX) for offline semantic understanding: the
  model download host is blocked in the development environment; planned.
