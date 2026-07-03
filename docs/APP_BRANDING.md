# Gurukrupa Bullion — App Branding & Gold Theme Spec

For the mobile app, to match the web dashboard. Two parts: **logo** and **gold color theme** (light + dark).

---

## 1. Logo

**Mark** = a gold emblem: two upper triangles + a base trapezoid (a stylised "A"/mountain).
Recreate it from this SVG (scales to any size, transparent background):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="-8 -8 79 71">
  <g fill="#D0A954">
    <polygon points="20,0 29,17 19,34 0,34"/>
    <polygon points="43,0 34,17 44,34 63,34"/>
    <polygon points="21,38 42,38 51,55 12,55"/>
  </g>
</svg>
```

- **App icon / splash:** gold mark centered on a **white** rounded square (icon PNGs available: `gurukrupa-256.png`, `gurukrupa-512.png` — ask for the files).
- **Header lockup:** `[gold mark]  Gurukrupa Bullion` — "Gurukrupa" bold, "Bullion" a touch smaller / letter-spaced / uppercase. Geometric sans (Poppins / Century Gothic / system).
- **Wordmark colour:** neutral text colour (dark on light, light on dark) — mirrors the real logo (gold mark + dark wordmark). The **mark** is the only gold element.
- Mark gold is theme-aware: **#D0A954 on light, #E1C06E on dark** (brighter so it pops on dark).

---

## 2. Brand colours

| Role | Hex |
|---|---|
| Brand gold (mark) — light | `#D0A954` |
| Brand gold (mark) — dark | `#E1C06E` |
| Logo gold (exact, from file) | `#D7B56D` |
| Charcoal (wordmark/text) | `#303030` |

---

## 3. Gold theme tokens (use these everywhere)

The UI accent is **gold** (not blue). Key rule: **gold is light, so never put white text on a gold fill — use dark text.**

### Light theme
| Token | Hex | Use |
|---|---|---|
| accent (fills) | `#C9A24E` | active tabs, primary buttons, highlights, bars, dots |
| accent-hover | `#B08D33` | pressed/hover |
| accent-bg (pale tint) | `#F7EFD6` | selected-row / chip backgrounds |
| **on-accent** (text ON gold) | `#2A2205` | **label text on gold buttons/tabs (dark, not white)** |
| accent-ink (gold TEXT) | `#8F6F16` | gold-coloured text/numbers on light bg (readable) |
| yellow-ink (warning text) | `#9C7508` | amber/warning text on light |
| bg-primary | `#F1F3F4` | screen background |
| bg-surface | `#FFFFFF` | cards |
| bg-surface-alt | `#F8F9FA` | alt rows / formula strips |
| text-primary | `#202124` | main text |
| text-secondary | `#3C4043` | secondary text |
| text-muted | `#80868B` | labels/captions |
| border | `#DADCE0` | borders/dividers |
| green / red | `#1E8E3E` / `#D93025` | up / down |

### Dark theme
| Token | Hex |
|---|---|
| accent (fills) | `#D9B45C` |
| accent-hover | `#E1C06E` |
| accent-bg | `#2F2712` |
| **on-accent** (text ON gold) | `#241D02` |
| accent-ink (gold TEXT) | `#E5C877` |
| yellow-ink | `#F6C342` |
| bg-primary | `#1A1A2E` |
| bg-surface | `#16213E` |
| bg-surface-alt | `#1A2540` |
| text-primary | `#F1F5F9` |
| text-secondary | `#CBD5E1` |
| text-muted | `#94A3B8` |
| border | `#2D3748` |
| green | `#48BB78` |

### Signals (kept amber — the "action needed" colour, do NOT make it gold)
- Badge/pill background `#F59E0B`, with **dark** number text `#3A2600` (white on amber is unreadable).

---

## 4. Where to apply

| Element | Style |
|---|---|
| App icon / splash | Gold mark on white |
| Header | Gold mark + "Gurukrupa Bullion" |
| Active tab / segment | Gold fill (`accent`) + **dark text** (`on-accent`) |
| Primary button (Sign in, Save…) | Gold fill + **dark text** |
| Secondary button | Transparent + gold border/text (`accent-ink`) |
| Count badges / highlights | Gold fill + dark text |
| Gold numbers / links | `accent-ink` (light) / `#E5C877` (dark) |
| Signals count | Amber `#F59E0B` + dark text `#3A2600` |
| Up / Down values | green `#1E8E3E` / red `#D93025` |

---

## 5. Do / Don't

- ✅ Dark text on gold fills (`on-accent`). ❌ White text on gold (unreadable).
- ✅ Gold **text** uses `accent-ink` (deeper), not the bright fill gold.
- ✅ Mark = gold; wordmark = neutral text colour.
- ✅ Support light + dark; the gold brightens on dark.
- ❌ Don't recolour the signals amber, per-commodity category colours, or green/red status.
