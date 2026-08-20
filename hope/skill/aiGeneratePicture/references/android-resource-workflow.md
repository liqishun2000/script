# Android Resource Workflow

Use this reference when a task involves Android layouts, resource overlays, or
drawable density folders.

## Locate References

Start from the repository root and search the named layout and code:

~~~powershell
rg -n "image|src|background|drawable|n_ai_" app/src/main/resconfigs app/src/main/java
rg --files app/src/main/resconfigs | rg "drawable|layout|values"
~~~

Check both XML references and runtime assignments. A grid may obtain its
icons from Kotlin/Java even when the main layout does not mention them.

## Density and Output Size

Preserve the existing density folder and bitmap dimensions unless the user
explicitly asks for a resize. Typical xhdpi targets from a home screen are:

| Visual role | Typical size |
| --- | --- |
| Home tile icon | 116x116 |
| Top feature icon | 120x120 |
| Small status icon | 48x48 or 64x64 |
| Badge or arrow | 24x24 to 36x36 |
| Large summary shield | 160x160 |
| Landscape card background | 640x272 |

These are examples, not defaults to apply blindly. Measure the actual source
file with Pillow before choosing a target.

For a vector source, use a logical viewBox that gives the artwork room to
remain crisp (116x116 is convenient for xhdpi tile icons), then rasterize to
the exact bitmap dimensions recorded in the manifest. Keep a transparent
margin when the original has one.

## Visual Inspection

Check all of the following before replacing an asset:

- silhouette at the real target size;
- alpha edges against both a light and a dark viewer background;
- alignment with neighboring icons;
- visual weight and accent colors from nearby resources;
- absence of text or fine lines that disappear after downsampling.

For a single icon, compare the original and candidate side by side. For a
batch, use a labeled contact sheet plus a direct view of the smallest assets.

## Manifest Shape

The bundled renderer accepts a JSON file with an assets array. Paths are
relative to the manifest directory:

~~~json
{
  "assets": [
    {
      "name": "resource_name",
      "svg": "svg/resource_name.svg",
      "width": 116,
      "height": 116,
      "webp": "webp/resource_name.webp"
    }
  ]
}
~~~

The webp field is optional on input. The renderer fills it when omitted.
Use a separate preview directory so an experiment cannot overwrite package
resources accidentally.

## Controlled Writeback

After approval, copy only the selected output:

~~~powershell
Copy-Item -LiteralPath .\output\webp\resource_name.webp -Destination .\app\src\main\resconfigs\...\drawable-xhdpi\resource_name.webp
~~~

Resolve the destination and verify its density folder before copying. Do not
bulk-copy an entire output directory into a dirty project. Leave aliases alone
unless the user explicitly includes them.

## Validation

Use a small Python check for dimensions and alpha:

~~~powershell
@'
from pathlib import Path
from PIL import Image

path = Path("resource.webp")
image = Image.open(path)
assert image.mode == "RGBA"
assert image.size == (48, 48)
assert image.getbbox() is not None
print(path, image.size, image.mode, image.getbbox())
'@ | python -
~~~

Parse SVG sources with the standard XML parser. Compare SHA-256 values when
the package file must exactly match the reviewed preview. Finish by checking
git status and separating this task's changes from pre-existing changes.

## Renderer Fallbacks

The bundled script prefers Microsoft Edge on Windows because it preserves
transparent SVG screenshots with a fixed viewport. If Edge is unavailable,
pass another Chromium-compatible executable with the script's browser option,
or use an installed SVG rasterizer such as CairoSVG. Do not silently fall back
to a white-background screenshot.
