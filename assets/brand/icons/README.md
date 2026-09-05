# ShotockViz — App Icon / Favicon Set

Generated from the brand's "SV" candlestick-arrow mark (clean flat variant), 2026-09-05.

## What's inside

- **`icon-rounded-{size}.png`** — corners pre-rounded, purple gradient background. Use for web `<link rel="icon">`, PWA manifest icons, README badges — anywhere the OS/browser does NOT apply its own mask.
- **`icon-square-{size}.png`** — full-bleed square, same gradient background, no rounded corners baked in. Use for iOS App Store icon, Android legacy launcher icon, or any platform that applies its own icon mask.
- **`favicon.ico`** — multi-resolution (16/32/48) ICO, ready to drop at `frontend/public/favicon.ico`.
- **`apple-touch-icon.png`** — 180×180, square (iOS rounds it automatically). Reference as `<link rel="apple-touch-icon" href="/apple-touch-icon.png">`.
- **`adaptive-icon-foreground.png` / `adaptive-icon-background.png`** — 512×512 Android adaptive icon layers (foreground = mark only, transparent; background = flat gradient). Android applies its own shape mask (circle/squircle/rounded-square depending on OEM launcher) on top of these two layers.
- **`maskable-icon-192.png` / `maskable-icon-512.png`** — PWA "maskable" icons with a wider safe zone (per the [maskable.app](https://maskable.app) spec) so nothing important gets clipped when a launcher crops to its own shape.
- **`icon-social-1024.png`** — 1024×1024 rounded, for app-store-style listings or social profile pictures.
- **`logo-mark-full.png`** — the full detailed "SV" + candlestick mark, transparent background, no icon chrome. For anywhere >64px (headers, docs, larger UI).
- **`logo-mark-simplified.png`** — the simplified "S"-only glyph, transparent background. Used automatically for every icon ≤64px because the full mark's thin candlestick wicks turn into an unreadable blur below ~64px — this is standard practice (a simplified favicon glyph distinct from the full logo).

## Why two mark variants

The original artwork (3 candlesticks + S + V arrow) has fine 4-6px strokes that don't survive downscaling to 16-48px — verified by rendering it at those sizes first (came out as an indistinct purple blob). Rather than ship a broken favicon, icons ≤64px use the simplified "S" ribbon alone (a single bold shape already present in the full mark, no fine strokes), and icons >64px use the full detailed mark. Both are visible in `preview.html`.

## Colors

Background gradient sampled from the actual logo artwork (diagonal, top-left → bottom-right):
- `#3A089E` (deep violet)
- `#9333EA` (vivid violet)

## Frontend integration (React 19 + TanStack Start, per this repo's stack)

```html
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/icon-rounded-32.png" type="image/png" sizes="32x32">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/manifest.json">
```

`manifest.json` icons array:
```json
{
  "icons": [
    { "src": "/icon-rounded-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icon-rounded-512.png", "sizes": "512x512", "type": "image/png" },
    { "src": "/maskable-icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable" },
    { "src": "/maskable-icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
```
