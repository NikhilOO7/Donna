#!/usr/bin/env python3
"""
Extract each SVG diagram from VOICE_DOC_DEMO_PRESENTATION.html
into standalone files in docs/diagrams/.

Each output file is a self-contained SVG with:
- XML declaration + xmlns
- Inline <style> with all the .node-bg / .edge / animation CSS
- Dark background rect (so the diagram looks right on a light page)

GitHub renders these via <img> tags including CSS animations.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
HTML = ROOT / "VOICE_DOC_DEMO_PRESENTATION.html"
DEST = ROOT / "docs" / "diagrams"
DEST.mkdir(parents=True, exist_ok=True)

# Stable filename per diagram (in document order)
NAMES = [
    "01-architecture",
    "02-document-upload-pipeline",
    "03-knowledge-graph-sample",
    "04-research-pipeline",
    "05-text-chat-flow",
    "06-voice-chat-flow",
    "07-five-agent-fan-out",
    "08-memory-model",
    "09-tts-speakback",
    "10-summary-pipeline",
]

STYLE_BLOCK = """<style>
.node-bg{fill:#1a2336;stroke:#2b3654;stroke-width:1.2}
.node-bg.indigo{stroke:#6366f1;fill:#1b1d3a}
.node-bg.violet{stroke:#8b5cf6;fill:#221a3a}
.node-bg.amber{stroke:#f59e0b;fill:#2c2418}
.node-bg.emerald{stroke:#10b981;fill:#152a23}
.node-bg.pink{stroke:#ec4899;fill:#2a1a26}
.node-bg.sky{stroke:#0ea5e9;fill:#15273a}
.node-bg.rose{stroke:#f43f5e;fill:#2a1820}
.node-bg.green{stroke:#22c55e;fill:#152a22}
.node-label{fill:#eaeef4;font:600 12.5px Inter,system-ui,sans-serif;text-anchor:middle;dominant-baseline:middle}
.node-sub{fill:#8a93ab;font:10.5px Inter,system-ui,sans-serif;text-anchor:middle;dominant-baseline:middle;letter-spacing:.06em}
.node-tag{fill:#cbd5e1;font:700 9.5px Inter,system-ui,sans-serif;text-anchor:middle;dominant-baseline:middle;letter-spacing:.12em;text-transform:uppercase}
.edge{fill:none;stroke:#3a4258;stroke-width:1.4}
.edge.dashed{stroke-dasharray:5 5}
.edge.flow{stroke:#5c6788}
.edge.accent{stroke:#8b5cf6}
.edge.amber{stroke:#f59e0b}
.edge.pink{stroke:#ec4899}
.edge.emerald{stroke:#10b981}
.edge.sky{stroke:#0ea5e9}
.edge-label{fill:#9ca3b8;font:10.5px ui-monospace,SFMono-Regular,monospace;text-anchor:middle;letter-spacing:.04em}
.lane-label{fill:#6b7390;font:700 10.5px Inter,system-ui,sans-serif;letter-spacing:.18em;text-transform:uppercase;text-anchor:middle}
@keyframes flowA{0%{offset-distance:0%}100%{offset-distance:100%}}
@keyframes nodePulse{0%,100%{filter:drop-shadow(0 0 0 rgba(99,102,241,0))}50%{filter:drop-shadow(0 0 8px rgba(99,102,241,.55))}}
@keyframes nodePulseViolet{0%,100%{filter:drop-shadow(0 0 0 rgba(139,92,246,0))}50%{filter:drop-shadow(0 0 8px rgba(139,92,246,.55))}}
@keyframes nodePulseAmber{0%,100%{filter:drop-shadow(0 0 0 rgba(245,158,11,0))}50%{filter:drop-shadow(0 0 8px rgba(245,158,11,.55))}}
@keyframes nodePulseEmerald{0%,100%{filter:drop-shadow(0 0 0 rgba(16,185,129,0))}50%{filter:drop-shadow(0 0 8px rgba(16,185,129,.55))}}
.node-pulse{animation:nodePulse 2.6s ease-in-out infinite}
.node-pulse.violet{animation-name:nodePulseViolet}
.node-pulse.amber{animation-name:nodePulseAmber}
.node-pulse.emerald{animation-name:nodePulseEmerald}
.flow-dot{filter:drop-shadow(0 0 4px currentColor)}
</style>"""


def extract_all() -> None:
    html = HTML.read_text(encoding="utf-8")

    # Match every <svg viewBox="0 0 11xx XXX"...> ... </svg> at top-level
    # (the 10 architecture diagrams — not the small inline icon SVGs).
    pattern = re.compile(
        r'(<svg viewBox="0 0 11\d{2} \d{3,4}"[^>]*>.*?</svg>)',
        re.DOTALL,
    )
    matches = pattern.findall(html)
    print(f"Found {len(matches)} diagram SVGs")

    if len(matches) != len(NAMES):
        print(f"WARNING: expected {len(NAMES)} diagrams, found {len(matches)}")

    for idx, (name, svg_block) in enumerate(zip(NAMES, matches)):
        # Extract viewBox to set width/height proportionally for the file
        vb_match = re.search(r'viewBox="(0 0 (\d+) (\d+))"', svg_block)
        if not vb_match:
            print(f"  ✗ {name}: viewBox missing")
            continue
        width, height = vb_match.group(2), vb_match.group(3)

        # Inject xmlns + viewport-friendly width/height
        # Replace the opening <svg ...> with one that includes xmlns
        opening = re.match(r"<svg[^>]*>", svg_block).group(0)
        new_opening = (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}" '
            f'preserveAspectRatio="xMidYMid meet">'
        )
        svg_block = svg_block.replace(opening, new_opening, 1)

        # Inject the dark background + style block right after the opening <svg>
        background = (
            f'\n  <rect width="100%" height="100%" fill="#0a0f1c"/>'
            f'\n  {STYLE_BLOCK}'
        )
        svg_block = svg_block.replace(new_opening, new_opening + background, 1)

        # Pretty-print: ensure newlines around top-level groups (already mostly there)
        output = '<?xml version="1.0" encoding="UTF-8"?>\n' + svg_block + "\n"

        path = DEST / f"{name}.svg"
        path.write_text(output, encoding="utf-8")
        print(f"  ✓ {name}.svg ({width}×{height}, {len(output)//1024} KB)")


if __name__ == "__main__":
    extract_all()
