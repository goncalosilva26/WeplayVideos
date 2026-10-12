# Export to Canva

Every proposal can be exported as a **Canva design in which each text box,
picture and shape is its own editable element**, laid out like the original
presentation. Use **Export to Canva** in the Viewer, in the Proposals page
(one, several or all proposals) or choose *Canva — editable design* in the
Export Center.

## Using it

1. **Export to Canva** → choose the proposals (or *All proposals* for the
   whole project), the page size (automatic by default) and where to save.
2. Then either
   * **Open it in my Canva account** — when you have connected Canva
     (Settings → Canva), the file is imported into your Canva account and
     the design opens in the browser; or
   * **Save the file** — open canva.com and drag the `.pptx` onto the home
     page (or *Create a design → Import file*). Canva converts it into an
     editable design. No setup or account connection is needed for this.
3. Next to the file you get `… - Canva report.txt` (page/section structure,
   the visual check, every approximation), `….canva.json` (the exported pages
   as structured data) and `Fonts for Canva/` (the fonts used, with their
   licences).

To put the result on Behance, download every page from Canva (PNG/JPG) and
upload them in order with the spacing between images set to 0: the pages are
consecutive strips of the presentation and join without seams.

## Which integration method, and why

Canva's official developer platform offers these routes (researched for this
feature; canva.dev itself is blocked from the build environment, so the facts
below come from Canva's documentation pages as found by web search — see
*Sources*):

| Method | What it produces | Used? |
| --- | --- | --- |
| **Connect API — design import** (`POST /v1/imports`, then `GET /v1/imports/{jobId}`) | Canva converts an uploaded file (PowerPoint, PDF, Illustrator, Photoshop, Keynote, Word…) into a **native, editable Canva design** and returns its edit URL. Scope `design:content:write`; rate limit 20 imports per minute per user; design titles up to 50 characters. | **Yes** — with a PowerPoint file (below), when the user connects Canva |
| Canva's own **Import file** (drag a `.pptx` onto canva.com) | The same conversion, by hand. Canva's help centre: up to 50 MB and 100 slides; charts, SmartArt, 3D objects and WordArt are not imported. | **Yes** — default, needs no setup |
| Connect API — create design (`POST /v1/designs`) | A blank design of a given size, optionally with *one* image placed as a flat picture | No: cannot create text boxes or shapes |
| Connect API — image-to-design import | Canva's AI splits an *image* into layers | No: would mean flattening the presentation first; the result is not controlled |
| Connect API — autofill (brand templates) | Fills text/image fields of a template designed in Canva | No: needs Canva Enterprise and one hand-made template per layout |
| Apps SDK — Design Editing API | Creates/edits individual elements, but only from an app running **inside** the Canva editor (JavaScript), installed per user and reviewed by Canva before public release | Not now. The exported `.canva.json` holds everything such an app would need (each element with geometry, styles and order) |

So the most reliable, officially supported way to get **native editable
elements** from a desktop application is to give Canva's importer a file
format it converts element by element. PowerPoint is the best fit: text
boxes, pictures (with crop), shapes, fills, outlines and shadows are explicit
objects in the file, whereas PDF stores positioned glyphs and paths that
importers have to reassemble.

## How the conversion works

The presentation is already a structured document — the **Design Spec**
(`docs/design-spec.schema.json`): sections of exact height holding layers
with absolute geometry, stacking order, typography with computed line breaks,
masks, effects and device frames. The same Spec generates the HTML
presentation (previews, PDF, images) and the Canva version:

```
Design Spec ──► HTML/CSS renderer ──► preview, PDF, images, HTML
     └───────► scene of editable elements ──► pages ──► .pptx ──► Canva (import API or by hand)
```

`behance_studio/canva/`:

* `build.py` — Spec → *scene*: every layer becomes one or more primitives
  (`text`, `image`, `rect`, `ellipse`) with absolute geometry, rotation,
  opacity, fill (solid or gradient), outline, shadow, crop and stacking
  order; device frames are rebuilt from shapes around the picture; each
  section gets its background element.
* `pages.py` — the long canvas → pages of one size (below).
* `pptx_out.py` — scene → PowerPoint: native text boxes (runs with font,
  size, bold/italic, colour with alpha, letter spacing, exact line spacing,
  paragraph spacing, alignment), pictures (crop rectangle, transparency,
  geometry, outline, shadow), shapes (rectangle, rounded rectangle, ellipse,
  top-rounded rectangle; solid/gradient fill; outline; outer shadow or glow).
  Theme styles are removed so nothing depends on PowerPoint defaults. 1 CSS
  px = 9525 EMU (96 px per inch); 1 px = 0.75 pt.
* `connect.py` — Canva Connect client (OAuth 2.0 + PKCE, import, polling).
* `check.py` — the visual checks.
* `export.py` — orchestration, report, fonts, export history.

### Property mapping

| Design Spec | In the exported design | Exact? |
| --- | --- | --- |
| Text: family, size, colour, opacity, italic, letter spacing, line height, alignment, rotation | Same properties on a native text box | Yes |
| Text: designed line breaks (headlines, labels) | Kept as line breaks; the box does not re-wrap and leaves room for slightly wider font metrics | Yes |
| Text: body paragraphs | One paragraph per paragraph, wrapping at a width computed so the designed lines come out again (±3.5 % metric tolerance); otherwise kept as line breaks | Yes, and re-wraps naturally when edited |
| Font weight | PowerPoint stores regular/bold only: weights ≥ 600 → bold, others → regular | **Approximation** (reported) |
| Variable-font width / optical size | Not representable in PowerPoint | **Approximation** (reported) |
| Outlined type | Text outline, no fill | Yes in PowerPoint/LibreOffice; Canva unverified |
| Images: cover/contain, focal point, zoom, padding mat | Picture with crop rectangle on an image that keeps the hidden parts (re-croppable); mat as a shape | Yes |
| Rotation, opacity | Native rotation and transparency | Yes |
| Corner radius, circle/oval/pill/arch masks | *Exact look* (default): drawn into that picture's alpha. *Maximum editability*: native rounded-rectangle/ellipse/top-rounded geometry | Yes / native |
| Gradients (linear, radial) | *Exact look*: drawn as a picture of that shape. *Editability*: native linear gradient; radial always drawn | Yes |
| Edge fades, filters (greyscale, muted, dim), recoloured marks, perspective tilt, pattern fills | Drawn into the picture of that one layer | Yes (look); not re-editable as an effect |
| Blend modes over a plain background | Blended colour computed (text, shapes) or drawn (pictures) | Yes; over mixed backgrounds: not reproduced (reported) |
| Shadows | Native outer shadow / glow; a transparent box's shadow becomes its own element (shapes for hard shadows, a picture for soft ones) | Close; soft-shadow spread is approximated |
| Device frames (phone, tablet, browser, poster frame) | Separate shapes (body, bar, buttons, island) + the screen picture | Yes |
| Video, animated GIF | Poster frame picture | **Approximation** (reported) |

Transparent pictures are written with *alpha bleeding* (invisible pixels take
their neighbours' colour) so editors that resample without premultiplied
alpha do not draw light halos around logos.

### Pages

A Canva design and a PowerPoint file have one page size, while a Behance
presentation is one long column (often 10 000–25 000 px). The export cuts it
into consecutive strips 1400 px wide:

* the page height is chosen automatically (1000–2600 px; Canva allows up to
  8000 px per side) to need the fewest splits, or set by the user;
* a cut never goes through text, rotated or masked elements: it moves up to
  just above them, and the rest of that page continues the background
  ("+N px background" in the report);
* backgrounds and pictures crossing a cut are split into two pieces that
  meet exactly (each piece is still a picture with its own crop);
* the section structure and order are listed per page in the report and in
  each page's notes.

## Visual verification

`check.py` compares, page by page, the original presentation rendered by
Chromium with (a) the exported pages drawn from exactly the properties stored
in the file ("conversion check", available in the app) and (b) the `.pptx`
rendered by **LibreOffice** — an independent program reading the actual file
(tests, and `canva-export --libreoffice`). The score is the share of the
page area without a visible difference (after a light blur, so anti-aliasing
does not count).

Results on the synthetic Butter & Bean project (all 11 layout families, 2026-10-12):
see `DEVELOPMENT_STATUS.md` → *Canva export* for the table. In short: the
conversion matches the original on ≈ 99.5–100 % of the page area for 10 of 11
families, and LibreOffice's rendering of the files on ≈ 98–99.7 %. The
lowest is *Posters* (≈ 96 % / 91 %): its display type uses Fraunces at weight
850, which PowerPoint files can only store as bold, and LibreOffice renders
Fraunces without its optical-size axis (wider letters).

**Not verified:** Canva's own import and rendering. canva.com and the Canva
API are not reachable from the build environment and no Canva account was
available. The upload protocol was tested against a local stand-in for the
Canva API (`tests/canva_mock.py`) that checks PKCE, client authentication,
token rotation, the import headers and the file, not Canva's converter.
Please compare the first pages in Canva with the preview after your first
export.

## Connecting your Canva account (optional)

Needed only for *Open it in my Canva account*. Canva's API is free; nothing is
paid.

1. Open the **Canva Developer Portal** (Settings → Canva → *Canva Developer
   Portal*), sign in and create an integration for the **Connect API**.
2. **Scopes:** enable `design:content:write`, `design:meta:read` and
   `profile:read`.
3. **Authentication:** add the redirect URL shown in Settings → Canva
   (default `http://127.0.0.1:51723/oauth/redirect` — Canva accepts
   `127.0.0.1`, not `localhost`, for local apps) and generate a **client
   secret** (Canva shows it only once).
4. Paste the **Client ID** and **Client secret** in Settings → Canva and press
   **Connect to Canva**; approve the request in the browser.

The client secret and the sign-in (refresh token) are stored in Windows
Credential Manager, never in settings, projects or exports. Access tokens are
kept in memory only; refresh tokens are single-use and replaced on each
refresh. *Disconnect* revokes the token. According to Canva's documentation,
a *private* integration (your team only) requires a Canva Enterprise plan,
and a *public* integration must pass Canva's review before people outside
your team can use it; whether an unreviewed integration works for your own
account could not be checked here. Without a connection, the manual import
works for every Canva account.

Command line: `BehanceStudio-cli canva-connect --client-id … --client-secret …`,
`canva-status`, `canva-disconnect`, and
`canva-export <project> --version all [--upload] [--combine] [--page-height N] [--editable] [--libreoffice]`.

## Limitations

* Weights other than regular/bold, width and optical-size variations of the
  variable fonts are shown as the nearest regular/bold style.
* Fonts are referenced by name. All bundled fonts are Google Fonts; Canva uses
  its own copy when its library has the family, otherwise it substitutes. The
  files are exported in *Fonts for Canva* for Canva Pro/Teams brand kits.
* Effects drawn into a picture (fades, filters, masks in *Exact look*,
  perspective) look right but are part of that picture; choose *Maximum
  editability* to keep masks and linear gradients as shape properties.
* Soft shadows are approximated (CSS shadow spread is emulated with a scaled
  shadow, which LibreOffice ignores).
* Blend modes over photographs or other layers are not reproduced.
* Videos and animations are exported as their poster frames.
* The last page (and, rarely, a page whose cut had to move above a text
  block) ends with a strip of background, because all pages have one size.

## Sources

* Canva Connect — Create design import job: <https://www.canva.dev/docs/connect/api-reference/design-imports/create-design-import-job/>
* Canva Connect — Get design import job: <https://www.canva.dev/docs/connect/api-reference/design-imports/get-design-import-job/>
* Canva Connect — Authentication (PKCE, 127.0.0.1 redirect URLs): <https://www.canva.dev/docs/connect/authentication/>
* Canva Connect — Generate an access token: <https://www.canva.dev/docs/connect/api-reference/authentication/generate-access-token/>
* Canva Connect — Creating integrations / Submitting integrations: <https://www.canva.dev/docs/connect/creating-integrations/>, <https://canva.dev/docs/connect/submitting-integrations>
* Canva Connect — Create design: <https://www.canva.dev/docs/connect/api-reference/designs/create-design/>
* Canva Apps SDK — Design Editing API: <https://www.canva.dev/docs/apps/design-editing/>
* Canva Help Center — Importing PowerPoint presentations: <https://www.canva.cn/en/help/powerpoint-import-cn/>
* Canva Help Center — Custom dimensions (40–8000 px): <https://www.canva.com/help/design-from-scratch/>
