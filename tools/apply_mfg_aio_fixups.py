from pathlib import Path

src = Path(__file__).resolve().parents[1] / "addon/src/nr-standalone.cpp"
s = src.read_text(encoding="utf-8")
if "D3D12_RESOURCE_BARRIER fg_begin[3] = {};" in s:
    s = s.replace("D3D12_RESOURCE_BARRIER fg_begin[3] = {};", "D3D12_RESOURCE_BARRIER fg_begin[4] = {};", 1)
if '_wtoi(value)' in s:
    s = s.replace('_wtoi(value)', 'atoi(value)', 1)
if "D3D12_RESOURCE_BARRIER fg_begin[4] = {};" not in s:
    raise SystemExit("MFG barrier array declaration not found after fixup")
if 'atoi(value)' not in s:
    raise SystemExit("MFG config atoi conversion not found after fixup")
src.write_text(s, encoding="utf-8")
print("Applied AIO MFG safety fixups")
