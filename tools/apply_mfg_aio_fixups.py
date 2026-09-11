from pathlib import Path

src = Path(__file__).resolve().parents[1] / "addon/src/nr-standalone.cpp"
s = src.read_text(encoding="utf-8")
old = "D3D12_RESOURCE_BARRIER fg_begin[3] = {};"
new = "D3D12_RESOURCE_BARRIER fg_begin[4] = {};"
if old in s:
    s = s.replace(old, new, 1)
if new not in s:
    raise SystemExit("MFG barrier array declaration not found after fixup")
src.write_text(s, encoding="utf-8")
print("Applied AIO MFG safety fixups")
