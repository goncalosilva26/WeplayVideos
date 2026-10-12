# Behance Studio — User Guide

## 1. The basic workflow

1. **New project** (Home → *New project*, or `Ctrl+N`). Give it a name and drop
   files or whole folders onto the window. You can also choose
   *Import a folder* to turn an existing delivery folder into a project.
2. **Optional:** write a creative brief or a project script in the dialog, or
   include `brief.txt` / `GUIAO_PROJETO.txt` in the dropped folder.
3. **Generate Projects** (`Ctrl+G`). The ten stages run in the background
   with real progress and a *Cancel* button:
   import → analyse → understand → plan → creative directions → layout →
   validate → revise → render → save.
4. **Proposals** (`Ctrl+3`) shows one complete presentation per layout family.
   Hover a card to scroll through it; open it in the **Viewer**.
5. **Compare** two or three proposals side by side with synchronised scrolling
   and choose *Choose this one* to mark the preferred version.
6. **Edit** if you want (Viewer → *Edit*), then **Export** (`Ctrl+E`).

Try the built-in demo first: Home → *Demo project* creates the synthetic
“Butter & Bean” coffee-shop identity (25 assets + a brief) and generates it.

## 2. Supported files

| Kind | Formats |
| --- | --- |
| Images | JPG, PNG, WebP, TIFF, BMP, GIF (animated GIFs are kept animated in HTML) |
| Vector | SVG (rasterised at the needed resolution) |
| Video | MP4, MOV, WebM (poster frame + preview; embedded in HTML exports) |
| Text | `brief.txt`, `GUIAO_PROJETO.txt`, `.md`, `.json` |

* Originals are never modified. By default files are copied into the
  project's `Assets` folder (Settings → *Copy imported files*).
* Corrupt files, exact duplicates and near-duplicates are detected and
  reported; nothing is silently dropped.
* Unicode file names (accents, spaces, `&`) are fully supported.
* If an original moves, the asset shows as *missing*: right-click → *Relink*.

### Asset types

Every image gets a type (logo, logo variant, monogram, palette, typography,
pattern, illustration, packaging, poster, outdoor, social, stationery,
editorial, mockup, website, mobile, UI, photo, product, lifestyle, portrait,
before/after, video, motion…). Types marked **~** are offline estimates from
the file name, folder and measured image features; **AI** marks types from a
configured AI provider. Right-click an asset to correct its type, exclude it
from presentations, reveal it in Explorer, or remove it (removed copies go to
the project's Trash and can be recovered).

### Sections from your folders

If you organise the delivery in folders named after sections, drop the
**whole project folder** (or several section folders at once):

```
Butter & Bean/
  01 Logo/            02 Brand Elements/      03 Packaging/Cups/…
  04 Campaign/Posters/…   04 Campaign/Outdoor/…   05 Social Media/…
```

Every image then stays in the section its folder names, in your order
(numbers are kept for the order and removed from titles; folders such as
`JPG`, `Export`, `Final` or `v2` are ignored; a subfolder like
`Campaign/Posters` stays inside Campaign). The type recognised for an image —
by the offline analysis or by local AI — only changes *how* it is shown,
never *which section* it is in. Images outside the section folders are
placed by what they show.

The **Sections** choice in the project's side panel switches between
*Follow my folders* (default) and *Let AI organise by content*, which
ignores the folders and groups images by their recognised type.

After every generation, **Section report** (or
`BehanceStudio-cli diagnose <project>`) opens
`Diagnostics/latest.txt`: for every image, its folder, the measured type,
the AI answer and whether it was applied (and why not), the final section
and where each proposal placed it. Any image shown outside its section is
listed there.

## 3. The creative brief (`brief.txt`)

Optional, plain text, English or Portuguese. Use `Field: value` lines; any
other text is kept as general context. Recognised fields include:

```text
Project: Butter & Bean
Type: Specialty coffee shop brand identity
Language: English

About: Butter & Bean is a neighbourhood specialty coffee shop and bakery.

Brand personality: warm, welcoming, contemporary, slightly playful
Audience: young professionals and families from the neighbourhood

Brand messages:
- "Specialty Coffee. Freshly Baked."
- "Your New Favourite Corner."

Colours: Espresso #2E1F17, Butter #F4C95D, Cream #F7EFE3, Terracotta #D9663F
Typography: Fraunces for headlines, Manrope for body copy
Mood: warm, friendly editorial compositions with lifestyle imagery
Avoid: neon colours
```

What the brief influences: project category, presentation language, brand
palette (exact HEX values are used as given), typography (named fonts are
used when bundled, otherwise the closest bundled match is chosen and the
substitution is noted), personality (warm/cool, calm/energetic,
casual/refined, subtle/bold, classic/contemporary, geometric/organic — with
negations such as “not too luxurious”), mood, preferred families and tone.

The **About** text is used verbatim for the introduction. Brand messages are
used where a family shows quotes or marquees. Nothing else is invented: when
there is no description, the introduction only states what the presentation
shows (for example “A brand identity project for Butter & Bean, covering the
logo, packaging and photography.”).

## 4. The project script (`GUIAO_PROJETO.txt`)

The script is **authoritative**: when it defines sections, every proposal
follows its order, titles, text, images and exclusions exactly. Families only
change the visual treatment. Precedence:

> `GUIAO_PROJETO.txt` › `brief.txt` › what Behance Studio infers › defaults

Keys are case-insensitive and can be written in English or Portuguese.

```text
PROJECT: Butter & Bean
LANGUAGE: en
EXCLUDE: draft-*.jpg, old-logo.png
FAMILY: editorial, cinematic        (optional: limit the families)
STRICT: yes                         (default; "no" lets the app add sections for unused assets)

## Cover
TITLE: Butter & Bean
SUBTITLE: Specialty Coffee. Freshly Baked.
IMAGES: DSC_0157 shop interior.jpg
LAYOUT: full-bleed

## Introduction
TEXT:
Paragraphs are kept exactly as written,
including line breaks.

## Brand Identity
IMAGES:
- butter-bean-logo-primary.png | Primary logo
- butter-bean-monogram.png | Monogram

## Closing
TITLE: Thank you
```

* Section headings: `## Name`, `[Name]`, `== Name ==`, `SECTION: Name` or
  `SECÇÃO 1: Capa`. The section type is recognised from the name (Cover,
  Introduction, Logo, Palette, Typography, Packaging, Campaign, Social Media,
  Website, Photography, Motion, Closing, … and Portuguese equivalents) or set
  with `TYPE:`.
* Section keys: `TITLE`, `SUBTITLE`, `EYEBROW`, `TEXT`, `IMAGES`, `CAPTIONS`,
  `LAYOUT` (`full-bleed`, `single`, `two-up`, `grid`, `split`, `text`,
  `hero`, `sequence`), `BACKGROUND` (HEX), `NOTES`.
  Portuguese: `TÍTULO`, `SUBTÍTULO`, `TEXTO`, `IMAGENS`, `LEGENDAS`,
  `COMPOSIÇÃO`, `FUNDO`, `NOTAS`.
* Image references may be a file name, a name without extension, a relative
  path or a wildcard (`poster-*.png`). Captions follow a `|`.
* Lines starting with `//` are comments.
* A JSON file with the same fields (`{"project": …, "sections": [{"title": …,
  "images": […]}]}`) is also accepted.

**Missing or ambiguous references are never silently replaced.** The
Workspace → *Script* tab has *Check script*, which lists every missing,
ambiguous or excluded reference with suggestions (for example “Did you mean
`logo-primary-final.png`?”). At generation you can continue — the section is
laid out without the missing file and the proposal records the issue — or
fix the script first (CLI: `generate --strict` aborts instead).

Use *Insert template* in the Script tab for a starting point in English or
Portuguese.

## 5. Presentation language

English is the default. Portuguese (Portugal) is used when the project, brief
or script says so (`Language: pt` / `IDIOMA: pt`) or when the brief is clearly
written in Portuguese. Your own text is never translated or rewritten.

## 6. Proposals, versions and the Trash

* Each generation adds new numbered versions (`Versions/001`, `002`, …);
  nothing is overwritten.
* Proposal actions (right-click a card): open, rename, duplicate,
  regenerate (a new variation with a new seed), apply another layout family
  (keeps the content plan), set as preferred, favourite, export, move to
  Trash. Duplicate, regenerate and apply-family create a new version; the
  original stays unchanged.
* **Trash** keeps deleted proposals until you restore them or delete them
  permanently (with confirmation). *Empty Trash* also asks first. Source
  assets are never deleted by Trash operations.

## 7. Viewing and editing

The Viewer shows the presentation exactly as it will be exported.

* Zoom: `Ctrl +` / `Ctrl −`, fit width `Ctrl 0`, full screen `F11`.
* Click any section (or pick it in the list) and choose **Edit** to open the
  inspector: title, subtitle, text, images (replace with another project
  asset, or remove), the focal point used when an image is cropped,
  background colour, spacing, hide section; *Regenerate*
  re-rolls only that section's layout; *Duplicate*, *Move up/down*.
* Every edit is saved as a new state of the version: `Ctrl+Z` / `Ctrl+Y` undo
  and redo, and the history menu restores any earlier state.
* Sections fixed by the script show a lock. Changing them asks for
  confirmation and the deviation is recorded in the proposal.

## 8. Exporting

Export Center (`Ctrl+E`): pick proposals (or *Preferred* / *Favourites*),
formats and options, then *Export*. Every file is verified after it is
written; existing files are never overwritten (a ` (2)` suffix is added).

| Format | Notes |
| --- | --- |
| PDF — continuous | One tall page per section group, vector text, embedded fonts. Best for Behance. |
| PDF — A4 pages | The presentation paginated at section boundaries, optional 12 mm margins. |
| JPG / PNG / WebP / TIFF | Full-resolution renders with an sRGB profile. Long presentations are split automatically (*Automatic*), or choose continuous, fixed-height segments, or one image per section. WebP is limited to 16,383 px per image, so it is always segmented. |
| HTML package | A self-contained folder (`index.html` + assets + fonts) that works offline; videos and animated GIFs play. |
| ZIP | The selected formats (PDF + HTML + text if only ZIP is chosen) in one archive. |
| Presentation text | All titles and texts as Markdown, for proofreading or reuse. |
| Canva — editable design | A PowerPoint file Canva imports as an editable design (see below). |

Width defaults to 1400 px (Behance's content width). Image quality renders at
1× (*Standard*), 1.6× (*High*, default) or 2.4× (*Maximum*) pixel density;
PDF text stays vector at any setting. A section subset can be exported when one proposal is
selected.

### Export to Canva

**Canva** in the Viewer, **Export to Canva** in Proposals (selected proposals,
or the whole project when none is selected) or the proposal's right-click
menu. Every text box, picture and shape becomes its own editable element in
Canva, positioned as in the proposal; long presentations are split into
pages of one size without cutting text. Then either open it in your Canva
account automatically (after connecting Canva in Settings, optional) or drag
the saved `.pptx` onto canva.com. A report next to the file lists the pages
and sections, the visual match with the original and anything Canva cannot
reproduce exactly (e.g. font weights other than regular/bold). Details,
limitations and how the integration works: [CANVA.md](CANVA.md).

## 9. Settings

* **Projects** — default folder, copy-on-import, default language.
* **Generation** — proposals per generation, creative variation (how far
  layouts may vary), design width, which families to generate, reduce motion.
* **Rendering** — the Chromium/Edge executable (automatic by default) with a
  *Test* button.
* **AI assistance** — optional; see [AI_PROVIDERS.md](AI_PROVIDERS.md).
* **Canva** — optional connection to your Canva account (Client ID and secret of
  a Canva Connect integration); see [CANVA.md](CANVA.md).
* **Performance & storage** — worker threads, project cache size and cleanup.
* **Diagnostics** — environment report and the log folder for support.

## 10. Keyboard shortcuts

| Keys | Action |
| --- | --- |
| `Ctrl+N` / `Ctrl+O` | New / open project |
| `Ctrl+I` | Add assets |
| `Ctrl+G` | Generate proposals |
| `Ctrl+E` | Export Center |
| `Ctrl+1` … `Ctrl+8` | Home, Project, Proposals, Viewer, Compare, Export, Trash, Settings |
| `Ctrl+Z` / `Ctrl+Y` | Undo / redo an edit (Viewer) |
| `Ctrl+0`, `Ctrl +`, `Ctrl −` | Fit width, zoom in, zoom out (Viewer) |
| `F11` | Full-screen preview |

## 11. Troubleshooting

* **“No rendering browser”** — run `setup_windows.bat` again with an internet
  connection, or install Microsoft Edge / Google Chrome, or point Settings →
  Rendering to `msedge.exe`.
* **The app does not start** — run `BehanceStudio_debug.bat` to see messages,
  and check the log (`%APPDATA%\BehanceStudio\logs\behance_studio.log`).
* **Videos do not play in the in-app preview** — the preview uses a WebM
  proxy that is generated automatically; exports keep the original video.
* **An image appears in the wrong section** — open *Section report*. If its
  folder is shown as “—”, the image was imported on its own (not inside its
  section folder) and was placed by type: re-import the whole project folder,
  or right-click the image to set its type. Projects imported before this
  version have no folder information; import the folder again.
* **A project folder was moved** — open it again with *Open project*; paths
  inside the project are relative. Assets that were linked (not copied) can
  be relinked from the asset context menu.
