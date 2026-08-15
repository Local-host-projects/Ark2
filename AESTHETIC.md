# ARK — Aesthetic & Design Language

> *"Don't read history. Scroll it."*

ARK is a time machine disguised as a social feed. The aesthetic must hold two things
in tension at once: **the archive** (ink, paper, telegrams, halftone print, stamped
dates) and **the feed** (fast, familiar, thumb-driven, alive). Every design decision
below serves that tension. The UI chrome is modern and quiet; the *content* is period,
loud, and textured. The user should feel like they opened Twitter in 1939.

---

## 1. Brand essence

| Attribute | Meaning in UI |
|---|---|
| **Archival** | Warm ink blacks, paper creams, stamped monospace dates, halftone imagery |
| **Alive** | Real-time ticker motifs, "LIVE" pulses, unread dots, breaking-news red |
| **Credible** | Editorial serif headlines, source citations, restrained decoration |
| **Immersive** | Content is period-styled; chrome disappears; media feels found, not generated |

**One rule above all:** *the chrome is the museum; the content is the exhibit.*
Interface elements stay neutral and minimal so period content (posts, newspapers,
broadcasts) carries all the flavor.

---

## 2. Color palette

### Core
| Token | Hex | Usage |
|---|---|---|
| `--ink` | `#100E0B` | Primary background (dark mode is default) |
| `--ink-2` | `#1A1712` | Raised surfaces, cards |
| `--ink-3` | `#26221B` | Borders-on-dark, hover states |
| `--paper` | `#F2ECDD` | Primary text on dark; light-mode background |
| `--paper-dim` | `#B5AC97` | Secondary text |
| `--paper-faint` | `#7A7362` | Tertiary text, timestamps, metadata |

### Accent
| Token | Hex | Usage |
|---|---|---|
| `--vermilion` | `#C2452D` | Primary accent. CTAs, LIVE badges, breaking news, unread |
| `--gold` | `#C9A227` | Secondary accent. Highlights, verified-era badge, hover glints |
| `--wire-blue` | `#4E6E8E` | Links, "wire report" metadata, quiet info accents |
| `--telegram` | `#E8DFC8` | Inset paper surfaces (newspaper cards, telegram posts) |

### Semantic
- Success / "verified against source": muted olive `#6F7D4E`
- Danger / destructive: `--vermilion` darkened `#9E3521`
- Focus ring: `--gold` at 60% opacity, 2px offset

**Rules**
- Vermilion is *earned*: only for live/breaking/primary-action. Never decorative.
- No pure `#000` or `#FFF` anywhere — everything warm-shifted (archive, not OLED).
- Period media (newspaper cards, posters) may use its own inner palette on `--telegram`
  paper; the outer card chrome stays on ink tokens.

---

## 3. Typography

| Role | Typeface | Notes |
|---|---|---|
| Display / headlines | **Newsreader** (serif) | Editorial, slightly condensed opsz. Italic for pull-quotes |
| UI / body | **Inter** | All chrome, buttons, feed body text |
| Timestamps / stamps / tickers | **IBM Plex Mono** | Uppercase, letter-spaced — telegram/date-stamp feel |

### Scale (rem, 1rem = 16px)
```
display-xl  clamp(2.5rem, 6vw, 4.5rem)   / 1.05   Newsreader 500
display     clamp(2rem, 4vw, 3rem)       / 1.1    Newsreader 500
title       1.375rem                      / 1.3    Newsreader 600
body-lg     1.125rem                      / 1.6    Inter 400
body        0.9375rem                     / 1.55   Inter 400
caption     0.8125rem                     / 1.4    Inter 500
stamp       0.75rem                       / 1.2    Plex Mono 500, +0.08em tracking, UPPERCASE
```

- Headlines: serif, tight leading, `text-wrap: balance`.
- Dates always render as stamps: `14 AUG 1945 · 08:16 GMT` in mono caps.
- Never letter-space the serif. Never use the serif for buttons.

---

## 4. Space, shape, depth

- **Spacing scale:** 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64 / 96 px. Sections breathe: min 96px vertical on desktop, 64px mobile.
- **Radius:** cards `14px`, buttons `10px`, pills/badges `999px`, media `10px`. Newspaper/telegram insets are `2px` — paper is cut square.
- **Borders over shadows.** 1px `--ink-3` borders define surfaces. Shadows only for overlays (modal, sheet): `0 24px 64px rgb(0 0 0 / .5)`.
- **Texture:** a barely-there film grain (2–3% opacity noise) over the whole app, and halftone dot treatment on hero imagery. Subtle — if a user notices it consciously, dial it down.
- **Max content width:** 1200px marketing pages; the feed itself is a 600px column (like the platforms it echoes).

---

## 5. Signature components

### Post card (the atom of ARK)
- Avatar (circular, 40px, subtle sepia treatment on portraits)
- Name in Inter 600 + handle + **era-verified badge** (small gold laurel) for grounded-in-source accounts
- Stamp-style timestamp, top-right, mono caps
- Body in Inter; period voice comes from *content*, not styling
- Media block: images get a faint halftone/sepia grade; newspapers render as `--telegram` paper insets with serif masthead
- Footer actions: reply / repost / archive-star — line icons, `--paper-faint`, vermilion only when active

### LIVE / BREAKING ribbon
Mono caps, vermilion, 2px pulsing dot. Used for tickers ("● LIVE — LONDON, 3 SEPT 1939")
and pinned breaking events. This is the heartbeat of the "world outside" illusion.

### Era card (simulation picker)
Full-bleed halftone key image, ink gradient scrim, serif title, mono date-range stamp,
one-line hook. Hover: image de-sepias slightly (history "waking up"), gold underline glint.

### Storyteller byline
Correspondent/anchor/analyst accounts get a thin wire-blue left rule on their posts and
a `WIRE` / `PRESS` / `ANALYSIS` mono tag — the user learns to read them as signal in the noise.

### Timeline scrubber
Horizontal mono-stamped date rail with event ticks. Current position = gold marker.
This is the "you are here in time" instrument — always accessible, never intrusive.

---

## 6. Motion

- **Default:** 150–220ms, `cubic-bezier(.2,.7,.2,1)`. Motion whispers.
- Feed entries fade-and-rise 8px on arrival (stagger 40ms) — the feed feels *received*, like wire dispatches.
- LIVE dot: 1.6s soft pulse. Ticker: slow marquee, pausable on hover.
- Era-card hover: 400ms sepia→color cross-grade.
- Respect `prefers-reduced-motion`: all of the above collapse to opacity-only.

---

## 7. Responsive behavior

Mobile-first. Breakpoints: `640 / 900 / 1200`.

- **< 640:** single column, feed edge-to-edge (12px gutter), nav collapses to logo + menu button, bottom tab bar inside the app shell (Feed / Timeline / Profiles / You), tap targets ≥ 44px.
- **640–900:** feed column centered, era cards 2-up.
- **> 900:** marketing pages go asymmetric (copy left, feed-mock right); app gains left rail (nav) + right rail (timeline/context).
- Type uses `clamp()` throughout; no fixed heights on text containers.
- PWA: standalone display, `--ink` theme-color, safe-area insets respected.

---

## 8. Accessibility & voice

- All text ≥ 4.5:1 contrast on its surface (paper-on-ink passes comfortably; check gold on ink for small text — use it at 700 weight or larger sizes only).
- Focus visible always (gold ring). Full keyboard traversal of the feed.
- Every simulation is labeled: a persistent, quiet `SIMULATION` stamp in the chrome. Immersion never means deception.
- Copy voice: confident, spare, slightly literary. Headlines read like front pages, not SaaS ("Live inside history", not "Leverage AI-powered learning").

### Don'ts
- No neon, no glassmorphism, no purple-gradient AI clichés.
- No skeuomorphic parchment backgrounds behind UI chrome.
- No emoji in system copy. Period content may use what the era plausibly had (i.e., none).
- Never style modern chrome to *pretend* to be old — only content is period.

---

## 9. File map for the next model

- `homepage.html` — self-contained landing page (embedded CSS + minimal JS), implements everything above. Fonts via Google Fonts: Newsreader, Inter, IBM Plex Mono.
- Design tokens live in `:root` of that file — lift them directly into the app's global stylesheet when the build starts.
