"""Export to Canva: editable designs that look like the Behance Studio original.

How it works (see ``docs/CANVA.md``):

1. :mod:`.build` translates a proposal's Design Spec — the same structured
   document that produces the HTML presentation — into a flat *scene* of
   primitive, individually editable elements (text boxes, pictures,
   rectangles, ellipses) with absolute geometry and stacking order. Effects
   that have no editable equivalent are reproduced on the one element they
   belong to (never by flattening a page).
2. :mod:`.pages` cuts the long Behance canvas into pages of one size (a Canva
   design and a PowerPoint file have a single page size) without cutting
   text, splitting pictures and backgrounds seamlessly where needed.
3. :mod:`.pptx_out` writes a PowerPoint file — the format Canva's official
   design-import API and Canva's "Import file" both convert into a native,
   editable Canva design.
4. :mod:`.connect` uploads it through the Canva Connect API (OAuth 2.0 with
   PKCE, ``POST /v1/imports``) when the user has connected their account;
   otherwise the file is imported in Canva by hand.
"""
