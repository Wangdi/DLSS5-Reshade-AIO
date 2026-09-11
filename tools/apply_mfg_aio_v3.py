from pathlib import Path
import runpy

SCRIPT = Path(__file__).with_name("apply_mfg_aio_v2.py")
ns = runpy.run_path(str(SCRIPT))
original_once = ns["once"]


def once(text: str, old: str, new: str, name: str) -> str:
    if name == "Presentation MFG fields" and text.count(old) > 1:
        struct_start = text.find("struct PresentationFrameSlot")
        if struct_start < 0:
            raise RuntimeError("PresentationFrameSlot not found")
        next_struct = text.find("\nstruct ", struct_start + 1)
        struct_end = len(text) if next_struct < 0 else next_struct
        segment = text[struct_start:struct_end]
        if segment.count(old) != 1:
            raise RuntimeError(
                f"PresentationFrameSlot: expected one target in struct, got {segment.count(old)}"
            )
        return text[:struct_start] + segment.replace(old, new, 1) + text[struct_end:]
    return original_once(text, old, new, name)


ns["once"] = once
ns["main"]()
