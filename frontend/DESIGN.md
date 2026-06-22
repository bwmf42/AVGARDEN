# A/GARDEN Pink Grid

## Direction

A/GARDEN is a NAS media library manager. The UI should feel quiet, fast, and operational while keeping the existing pink-white identity. The direction is **Pink Grid**: a white/petal surface system, fine rose hairlines, compact cards, tabular status chips, and restrained motion.

This is informed by the installed `frontend-design` workflow and `huashu-design` anti-slop rules. It is not a strict copy of any external anchor because the project constraint is to keep pink-white as the signature.

## Tokens

- Background: `#fff7fa` with subtle 1px grid lines.
- Surface: `#ffffff`.
- Elevated surface: `#fffbfd`.
- Text: `#35242c`; muted text `#80636f`.
- Primary rose: `#e84d7a`.
- Deep rose: `#ba2f5d`.
- Soft rose line: `#f3c6d4`.
- Neutral line: `#eadde3`.
- Semantic colors:
  - Downloading: blue `#2563eb`
  - Queued: amber `#a15c00`
  - Failed: red `#b42318`
  - Done: green `#287a43`

## Rules

- Use real product labels: standard actions stay standard, such as `添加`, `刷新`, `返回`, `加入下载队列`.
- Avoid emoji as primary icons. Use text labels, small CSS dots, and existing SVG arrows where already present.
- Cards have `8px` radius or less. Repeated items may be cards; page sections should remain unframed or use a single surface panel.
- Favor 1px borders over heavy shadows. Shadows are reserved for hover and modal surfaces.
- Keep layouts dense enough for repeated scanning: compact headings, predictable grids, stable aspect ratios.
- Motion is short and functional: hover lift no more than 2px, transitions around 160-220ms.

## Signature Move

Every primary list view uses a **rose index strip**: cards and operational rows have a thin top or side accent line instead of large decorative gradients. This keeps the pink brand visible without flooding the interface.
