"""Bundle sim-web into one self-contained HTML file (for sharing or hosting)."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
SIM = ROOT / "sim-web"

def bundle(out):
    html = (SIM / "index.html").read_text()
    css = (SIM / "styles.css").read_text()
    css += """
:root { padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px); }
html { scroll-padding-top: env(safe-area-inset-top, 0px); }
.app-shell { height: 100%; }
"""
    html = html.replace('<link rel="stylesheet" href="styles.css">', f"<style>\n{css}\n</style>")
    html = html.replace("""<script>window.BABYLON || document.write('<script src="vendor/babylon.js"><\\/script>');</script>\n""", "")
    model = SIM / "assets" / "machine.stl"
    if model.exists() and model.stat().st_size < 8_000_000:
        import base64
        b64 = base64.b64encode(model.read_bytes()).decode()
        html = html.replace('<script src="stl.js"></script>', f'<script src="stl.js"></script>\n<script>window.MACHINE_STL_B64="{b64}";</script>')
    for name in ("cell-plan.js", "kinematics.js", "stl.js", "app.js"):
        code = (SIM / name).read_text().replace("</script", "<\\/script")
        html = html.replace(f'<script src="{name}"></script>', f"<script>\n{code}\n</script>")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(html)
    return out

if __name__ == "__main__":
    print(bundle(sys.argv[1] if len(sys.argv) > 1 else ROOT / "output" / "soft-jaw-cell-sim.html"))
