#!/usr/bin/env python3
"""Fix Dashboard.html: wrap Chart.js calls with guard for file:// protocol"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "outputs-binyu" / "Dashboard.html"

with open(HTML, "r", encoding="utf-8") as f:
    html = f.read()

# Add hasCharts flag before first chart
html = html.replace(
    "// Radar\nvar colors",
    "var hasCharts = typeof Chart !== 'undefined';\n// Radar\nvar colors",
    1
)

# Guard each chart block
replacements = [
    # (old_marker, new_marker) for opening each chart
    ('var ctx = document.getElementById("radar")', 'if(hasCharts){var ctx = document.getElementById("radar")'),
    ('var lctx = document.getElementById("latBar")', 'if(hasCharts){var lctx = document.getElementById("latBar")'),
    ('var tctx = document.getElementById("tokBar")', 'if(hasCharts){var tctx = document.getElementById("tokBar")'),
    ('var mlctx = document.getElementById("mmLatBar")', 'if(hasCharts){var mlctx = document.getElementById("mmLatBar")'),
    ('var mtctx = document.getElementById("mmTokBar")', 'if(hasCharts){var mtctx = document.getElementById("mmTokBar")'),
]

for old_marker, new_marker in replacements:
    if old_marker in html:
        html = html.replace(old_marker, new_marker, 1)
        print(f"[OK] Guarded: {old_marker[:50]}...")
    else:
        print(f"[MISS] Not found: {old_marker[:50]}...")

# Close each chart guard (find the "});" followed by blank line and next comment)
closers = [
    ('});\n\n// Performance cards', '});}\n\n// Performance cards'),
    ('});\n\n// Text tasks token chart', '});}\n\n// Text tasks token chart'),
    ('});\n\n// Multimodal latency chart', '});}\n\n// Multimodal latency chart'),
    ('});\n\n// Multimodal token chart', '});}\n\n// Multimodal token chart'),
    ('});\n\n// Hallucination', '});}\n\n// Hallucination'),
]

for old_closer, new_closer in closers:
    if old_closer in html:
        html = html.replace(old_closer, new_closer, 1)
        print(f"[OK] Closed guard")
    else:
        print(f"[MISS] Closer not found")

# Add Chart.js status note after performance cards
html = html.replace(
    'document.getElementById("perf").innerHTML = sortedModels.map',
    'if(!hasCharts){document.getElementById("perf").innerHTML += "<p style=\\"color:#d29922;margin-top:8px;font-size:12px\\">[Charts require network - Chart.js CDN not loaded]</p>";}\ndocument.getElementById("perf").innerHTML = sortedModels.map',
    1
)

with open(HTML, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\nFixed: {HTML}")
