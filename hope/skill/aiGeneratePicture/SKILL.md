---
name: ai-generate-picture
description: Redraw, generate, and replace Android UI image resources with exact-size SVG and WebP assets, including drawable discovery, density-aware sizing, transparent rasterization, previews, and controlled writeback. Use when a request mentions replacing or redesigning app images, Android drawable resources, res/layout image references, WebP icons, SVG/vector redraws, or Chinese requests such as 重新生成图片, 替换UI图片, and 重画图标.
---

# Android UI Asset Redraw

Use this skill for repeatable Android UI image replacement. Treat the existing
resource as a contract for name, target dimensions, density, transparency, and
visual role. Produce an isolated preview first, then write back only the files
the user has approved or explicitly named.

## Workflow

### 1. Establish scope

- Resolve the project root and the exact res/layout, resconfigs, and drawable
  directories named by the user.
- Check git status --short before editing. Preserve unrelated dirty files.
- Read the target layout and nearby code with rg to find direct and dynamic
  image references. Include aliases used by exit screens or duplicated
  layouts when the request covers a resource family.
- Ask for clarification only when the target resource or intended visual role
  cannot be determined from the repository.

### 2. Inventory the source asset

- Inspect the current image with an image viewer before designing.
- Measure every referenced bitmap with scripts/inspect_drawables.py or Pillow.
- Record the exact output width, height, color mode, alpha bounding box, density
  folder (drawable-xhdpi, drawable-xxhdpi, etc.), and file extension.
- Read nearby colors and shape XML so the redraw fits the existing UI. Do not
  infer density from the filename alone.
- For a batch, write a manifest that maps resource name, SVG source, target
  dimensions, and output WebP path.

### 3. Choose the generation route

- Prefer code-native SVG or Android VectorDrawable-style geometry for icons,
  badges, simple illustrations, and repeated UI symbols. It gives stable
  silhouettes, exact sizing, transparent edges, and easy revisions.
- Use model image generation only when it is available and the user wants
  painterly, photographic, or texture-heavy artwork. Do not invent an API key
  or claim an image was model-generated when the local tool is unavailable.
- Keep the visual role intact: an icon named n_ai_anv_ti_home_clean_broom_icon
  must still read as a broom/cleaning tool at its smallest target size.
- Design against the target size. Use a larger logical SVG viewBox (normally
  116x116 for xhdpi home tiles), bold outlines, few internal details, and
  margins that survive downsampling.
- Preserve transparent backgrounds for standalone icons. Avoid text inside
  icons unless the original asset contains required text.

### 4. Build an isolated preview batch

- Put sources and previews under a new directory such as
  output/home-assets-v3/, never directly over the package resources during
  exploration.
- Store editable SVG files in svg/, lossless WebP files in webp/, and a
  manifest.json beside them.
- Render SVG with scripts/render_svg_webp.py when a manifest is available.
  The script uses transparent headless Edge output and Pillow resizing; it
  does not add a white matte.
- Generate a contact sheet for batches. Include labels outside the artwork so
  the image itself remains suitable for Android use.
- Open the single asset and the contact sheet. Check the icon at its real
  target size, not only at a large zoom.

### 5. Review and write back

- Show the preview path before replacing a whole resource family.
- For a user-approved single-file replacement, copy only the named WebP into
  the exact density directory. Keep the SVG source and manifest for rollback
  and later variants.
- Update aliases only when they are explicitly in scope or the user asks for
  family-wide consistency. Do not silently replace every similarly named file.
- Never use a broad recursive copy, reset, checkout, or cleanup command in a
  dirty repository.

### 6. Validate

- Parse every SVG as XML.
- Verify each WebP has the manifest width and height, expected RGBA/alpha
  behavior, and a non-empty alpha bounding box.
- Compare the written package file with the approved preview by SHA-256 when
  exact byte identity matters.
- Run the narrowest relevant Android resource/build check after writeback. If
  a full build is expensive or blocked, report that explicitly and retain the
  image-level validation results.
- Re-run git status --short and summarize only the files changed by this
  task, distinguishing them from pre-existing modifications.

## Design Defaults

- Favor a restrained dark outline plus two or three contrasting accent colors.
- Use simple, recognizable silhouettes and stable outer dimensions.
- Keep shadows, highlights, and motion marks subordinate to the main shape.
- Avoid tiny strokes, fine text, muddy gradients, and details that disappear
  after xhdpi downsampling.
- Match the surrounding resource family rather than introducing a one-off
  illustration style.

## Bundled Renderer

Use the renderer with a manifest like:

~~~json
{
  "assets": [
    {
      "name": "n_ai_anv_ti_home_clean_broom_icon",
      "svg": "svg/n_ai_anv_ti_home_clean_broom_icon.svg",
      "width": 48,
      "height": 48
    }
  ]
}
~~~

Run:

~~~powershell
python scripts/render_svg_webp.py --manifest .\manifest.json
python scripts/render_svg_webp.py --manifest .\manifest.json --contact-sheet
~~~

Use --only NAME to render one asset while iterating. See
references/android-resource-workflow.md for density and resource-layout
details. Use scripts/inspect_drawables.py before and after writeback to record
dimensions, mode, and alpha bounds.
