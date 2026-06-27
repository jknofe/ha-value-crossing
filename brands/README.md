# Brand assets

Icon for the Value Crossing integration: two trend lines crossing, with a red
dot marking the crossing point.

```
custom_integrations/value_crossing/
  icon.svg      source (vector), not submitted to brands
  icon.png      256x256 RGBA, transparent
  icon@2x.png   512x512 RGBA, transparent
```

## How the icon gets used

Home Assistant does not load an integration icon from this repository. The icon
shown in *Settings -> Devices & Services* and in HACS comes from the central
[home-assistant/brands](https://github.com/home-assistant/brands) repository,
keyed by the integration domain (`value_crossing`).

To make this icon appear, copy the two PNGs into a brands PR at:

```
custom_integrations/value_crossing/icon.png
custom_integrations/value_crossing/icon@2x.png
```

Only the PNGs go to brands (not the SVG). They already meet the brands rules:
square, exact 256/512 sizes, transparent corners, trimmed to content.

## Regenerating the PNGs from the SVG

`icon.svg` is the source of truth. There is no system SVG rasterizer with
transparency on the build machine, so the PNGs were produced by rendering the
artwork over white and over black (via `qlmanage`) and recovering true alpha
from the two renders, then trimming to a centered square and resizing with
Lanczos. Re-run that process if the SVG changes.
