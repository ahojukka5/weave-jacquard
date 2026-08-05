from pathlib import Path

path = Path(__file__).with_name("evidence_profile_generator.py")
text = path.read_text(encoding="utf-8")
old = 'end = text.index("    def form(\\n", start)'
new = 'end = text.index("    def form(", start)'
if text.count(old) != 1:
    raise SystemExit("evidence generator method boundary was not found exactly once")
path.write_text(text.replace(old, new), encoding="utf-8")
Path(__file__).unlink()
