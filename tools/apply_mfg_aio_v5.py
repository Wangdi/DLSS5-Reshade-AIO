from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/apply_mfg_aio_v2.py"
source = SCRIPT.read_text(encoding="utf-8")
start = source.index("def once(")
end = source.index("\n\ndef main()", start)

replacement = '''def once(text: str, old: str, new: str, name: str) -> str:
    if name == "Presentation MFG fields":
        struct_start = text.find("struct PresentationFrameSlot")
        if struct_start < 0:
            raise RuntimeError("PresentationFrameSlot not found")
        struct_end = text.find(chr(10) + "};", struct_start)
        if struct_end < 0:
            raise RuntimeError("PresentationFrameSlot end not found")
        struct_end += 3
        segment = text[struct_start:struct_end]
        count = segment.count(old)
        if count != 1:
            raise RuntimeError(f"PresentationFrameSlot target: expected one match, got {count}")
        return text[:struct_start] + segment.replace(old, new, 1) + text[struct_end:]
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{name}: expected one match, got {n}")
    return text.replace(old, new, 1)
'''

source = source[:start] + replacement + source[end:]
namespace = {"__name__": "__mfg_aio_v5__", "__file__": str(SCRIPT)}
exec(compile(source, str(SCRIPT), "exec"), namespace)
namespace["main"]()
