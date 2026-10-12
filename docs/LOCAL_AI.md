# Free local AI with Ollama

Behance Studio can use a vision-language model running **on your own PC**
through [Ollama](https://ollama.com). It is free, needs no account or API
key, and nothing leaves your computer. Without it the app still works fully
offline (measured image analysis and a rules-based director).

## What local AI does in the app

| Step | What the model does | Safeguards |
| --- | --- | --- |
| **Recognise design purpose** — automatically after every import, and before every generation | Looks at a small preview of each image and says what it is *for*: logo, symbol, colour sheet, type sheet, pattern, packaging, poster, outdoor, social post, stationery, editorial, mockup, website/app screen, photograph… plus how it is presented (flat artwork, design shown in a photographed scene, plain photograph, brand element, document sheet, screen) | Answers are structured (JSON schema). Answers that contradict what the app measured itself (e.g. a "photograph" with a transparent background, a "logo" that is a full-colour photo, a still image called a video) are recorded but **not applied**. Your own corrections always win. |
| **Put images in the right sections** | When the project is organised in section folders (`01 Logo`, `03 Packaging/Cups`…), **the folders decide the sections** and the model's answer only decides how an image is shown (cropped photograph or whole artwork). An answer that contradicts the folder (e.g. "social post" for a file in `01 Logo`) is recorded but not applied. Images without a meaningful folder are placed by their recognised purpose. *Sections → Let AI organise by content* lets the model's answer decide the section instead. | Every planner (offline director, AI director, classic layouts) receives the same validated image → section mapping. After planning, a **section check** moves any image shown outside its section back to it (never swapped for another image or dropped) and restores the folder order; script sections are only reported. The quality report warns about any remaining mismatch, and `Diagnostics/latest.txt` lists every image's folder, AI answer, decision and placement. |
| **Creative direction** | Plans each of the five concepts: which images to show, in what order, with which composition, what to leave out and why | The storyboard is validated before use (unknown images/modules discarded, artwork never cropped, counts clamped, no AI-written text). If too little survives, the offline director plans that concept. |
| **Critique** (optional, off by default) | Reviews the rendered sections and flags weak ones for one round of recomposition | Changes are kept only if the technical checks do not get worse. |

## Choosing a model for an RTX 3060 12 GB + 32 GB RAM

Sizes are approximate for Ollama's default 4-bit builds; Ollama shows the
exact size when downloading. "GPU memory" includes the context window this
app uses (up to 16–32 K tokens for creative direction).

| Model (`ollama pull …`) | Download | GPU memory | Verdict |
| --- | --- | --- | --- |
| **`qwen3-vl:8b`** | ≈ 6 GB | ≈ 9 GB | **Recommended (default).** Strong at reading text inside designs (logos, labels, posters) and at producing the structured answers the app needs. Fits entirely in 12 GB, so it runs fully on the GPU. |
| `qwen3-vl:4b` | ≈ 3.3 GB | ≈ 5.5 GB | Lighter alternative: faster, somewhat less accurate. Use it if games/other apps need the GPU at the same time. |
| `qwen2.5vl:7b` | ≈ 6 GB | ≈ 9 GB | Previous generation; a good fallback if your Ollama version cannot run Qwen3-VL. |
| `gemma3:12b` | ≈ 8 GB | ≈ 11 GB | Capable, but leaves almost no GPU headroom on 12 GB; slower. |
| `gemma3:4b` | ≈ 3.3 GB | ≈ 5 GB | Small and fast; weaker at reading text and at long planning answers. |
| `llava`, `moondream` | — | — | Not recommended: older/smaller models misread text in designs and struggle with planning. |

32 GB of RAM is plenty; if a model does not fit the GPU, Ollama runs part of
it on the CPU (slower). `ai-check --test` shows how much of the model is in
GPU memory.

**Important:** these recommendations are based on the models' published
characteristics. They could not be benchmarked while building this feature
(the development environment has no GPU and could not reach Ollama's
download servers). Run `ai-check --test` on your PC to measure accuracy and
speed with your own hardware and images.

## Windows setup, step by step

1. **Update the NVIDIA driver** (GeForce Experience / NVIDIA App, or
   nvidia.com). Ollama uses CUDA through the normal driver; nothing else to
   install.
2. **Install Ollama.** Download *OllamaSetup.exe* from
   <https://ollama.com/download/windows> and run it (no administrator rights
   needed) — or in PowerShell: `winget install Ollama.Ollama`.
   Ollama starts automatically (a llama icon appears in the taskbar
   notification area) and listens on `http://localhost:11434`.
   Qwen3-VL needs a recent Ollama (0.12.7 or newer at the time of writing):
   if a download fails with "requires a newer version", update Ollama.
3. **Download the model** (≈ 6 GB, once). Either:
   * in Behance Studio: *Settings → AI assistance* → Provider **Ollama** →
     **Download model**, or
   * in PowerShell: `ollama pull qwen3-vl:8b`
4. **Check it.** In *Settings → AI assistance* press **Check again** — it
   should say *Local AI ready*. Or double-click **`LocalAI_Check.bat`** in
   the app folder (it checks Ollama and, when ready, runs the real test of
   step 5; `LocalAI_Check.bat --pull` also downloads a missing model). Or run:
   ```
   .venv\Scripts\python -m behance_studio ai-check
   ```
   (packaged build: `BehanceStudio-cli.exe ai-check`).
5. **Test it for real** (recommended once):
   ```
   .venv\Scripts\python -m behance_studio ai-check --test
   .venv\Scripts\python -m behance_studio ai-check --test --folder "C:\path\to\your project images"
   ```
   The first command scores the model on labelled test images with the file
   names hidden; the second shows what it decides for your own files. Both
   report seconds per image, GPU use and one creative-direction run.
   The automated live tests run the same checks:
   `run_tests.bat tests\test_ollama_live.py -s`.
6. **Use it.** Import images (they are recognised automatically; types from
   AI show "· AI" in the asset grid) and press *Generate*.

Ollama is the default provider in this version; settings from earlier
versions that had "no AI" switch to Ollama automatically. Paid providers you
chose are never changed. Choose *None — offline only* to turn AI off.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "Ollama is not installed" although it is | Start Ollama from the Start menu; if it runs on another port or PC, enter its address in *API address*. |
| "not downloaded yet" | *Download model* in Settings, or `ollama pull qwen3-vl:8b`. |
| Slow, or `ai-check` shows little GPU use | Update the NVIDIA driver; close other GPU-heavy apps; try `qwen3-vl:4b`. In a terminal, `ollama ps` shows "100% GPU" when it fits. |
| First request is slow | The model is loaded into memory on first use (it then stays loaded 15 minutes). |
| "Not enough memory" | Choose `qwen3-vl:4b`. |
| Some images keep a heuristic type marked "~" | The model was unsure (confidence < 0.6), its answer contradicted the measurements, or it contradicted the image's section folder; *Section report* shows which. Right-click the image to set the type yourself. |
| Analysis runs again every time | It should not: answers are cached per image content and model (`%APPDATA%\BehanceStudio\ai-cache\`). The log line "AI asset recognition … N analysed, M from cache" shows what happened. Changing the model or replacing an image does trigger a new analysis. |

## Privacy and cost

* Requests go only to the Ollama server you configured (by default
  `localhost`); previews never leave your PC, so no per-project consent is
  needed for a server on this computer. A server on another computer of
  your network needs the usual "allow previews" switch.
* No account, no API key, no usage limits; the cost estimate shows
  "no charge" and no confirmation is asked.
