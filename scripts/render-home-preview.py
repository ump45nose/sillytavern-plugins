"""Export the pending homepage revision without replacing the approved baseline."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
renderer = Path('/home/yuwk/.codex/plugins/cache/openai-bundled/visualize/1.0.46/skills/visualize/scripts/render.py')
source = root / 'docs/design/novel-desktop/rework/home.fragment.html'
target = source.with_name('preview.html')
subprocess.run([sys.executable, str(renderer), str(source), str(target), '--force', '--title', 'Noval · 主页修订预览'], check=True)
# Keep the standalone preview at the real browser size, rather than adding a
# second frame around this full desktop application shell.
html = target.read_text()
html = html.replace('padding:1rem;background:inherit', 'padding:0;background:inherit', 1)
html = html.replace('height:calc(100vh - 2rem)', 'height:100vh!important', 1)
target.write_text(html)
