"""Export the RP design at the full browser viewport, without a second frame."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
renderer = Path('/home/yuwk/.codex/plugins/cache/openai-bundled/visualize/1.0.47/skills/visualize/scripts/render.py')
source = root / 'docs/design/rp-desktop/approved.fragment.html'
target = source.with_name('preview.html')
subprocess.run([sys.executable, str(renderer), str(source), str(target), '--force', '--title', 'RP · 工作台布局修订'], check=True)
html = target.read_text()
html = html.replace('padding:1rem;background:inherit', 'padding:0;background:inherit', 1)
# The export bridge reports content height; the application must stay inside
# the real viewport, including on the initial load and after window resizing.
html = html.replace('height:calc(100vh - 2rem)', 'height:100vh!important', 1)
target.write_text(html)
