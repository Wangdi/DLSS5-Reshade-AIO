from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "addon/src/nr-standalone.cpp"
MENU = ROOT / "addon/include/aio-menu-schema.hpp"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, got {n}")
    return text.replace(old, new, 1)


def insert_after(text: str, marker: str, addition: str, label: str) -> str:
    return replace_once(text, marker, marker + addition, label)


def main() -> None:
    src = SRC.read_text(encoding="utf-8")
    menu = MENU.read_text(encoding="utf-8")

    if '"MfgMultiplier"' not in menu:
        menu = insert_after(
            menu,
            'inline constexpr const char *kPresetItems[] = {\n    "Default (NVIDIA)", "Preset J", "Preset K", "Preset L (Recommended default)", "Preset M" };',
            '\ninline constexpr const char *kMfgItems[] = { "2x (1 generated)", "3x (2 generated)", "4x (3 generated)" };',
            "MFG menu items",
        )
        menu = insert_after(
            menu,
            '{ "FrameGeneration", "Experimental DLSS Frame Generation (2x)", NR_BOOL, 1, 0, 1, nullptr, nullptr, 0,\n      "Presents one generated frame followed by one reconstructed real frame.", Group::Neural },',
            '\n    { "MfgMultiplier", "MFG multiplier (RTX 40 experimental)", NR_COMBO, 0, 0, 2, nullptr, kMfgItems, 3,\n      "2x is the normal single-frame DLSS-G path. 3x/4x require the Ada runtime unlock and a restart after changing.", Group::Neural },',
            "MFG menu setting",
        )

    if "#include \"../../mfg/aio-mfg-unlock.hpp\"" not in src:
        src = insert_after(
            src,
            '#include "nvof-motion-provider.hpp"',
            '\n#include "../../mfg/aio-mfg-unlock.hpp"',
            "MFG helper include",
        )

    src = src.replace('#define ADDON_VERSION "2.2.3"', '#define ADDON_VERSION "2.2.3-mfg1"', 1)

    if "g_mfg_multiplier" not in src:
        src = insert_after(
            src,
            'static bool g_framegen_enabled = true;\n',
            'static unsigned int g_mfg_multiplier = 2;\nstatic unsigned int g_mfg_active_generated_count = 1;\nstatic unsigned int g_mfg_active_frame_index = 1;\nstatic bool g_mfg_unlock_logged = false;\n',
            "MFG globals",
        )

    if "EffectiveMfgGeneratedCount" not in src:
        helper = '''\nstatic unsigned int EffectiveMfgGeneratedCount(bool direct_output)\n{\n    const unsigned int requested = std::clamp(g_mfg_multiplier, 2u, 4u) - 1u;\n    if (requested <= 1u) return 1u;\n    if (!direct_output) return 1u;\n    if (!dlss5_aio_mfg::IsReady())\n    {\n        if (!g_mfg_unlock_logged)\n        {\n            Log("MFG 3x/4x requested but Ada runtime unlock is unavailable; falling back to 2x");\n            g_mfg_unlock_logged = true;\n        }\n        return 1u;\n    }\n    return requested;\n}\n'''
        src = insert_after(src, 'static bool EffectiveFramegenEnabled()\n{\n    return g_framegen_enabled;\n}\n', helper, "MFG effective count helper")

    marker = 'read_setting("FrameGeneration", "1", value, sizeof(value)); g_framegen_enabled = strcmp(value, "0") != 0;'
    if 'read_setting("MfgMultiplier"' not in src:
        src = insert_after(
            src,
            marker,
            '\n        read_setting("MfgMultiplier", "2", value, sizeof(value)); g_mfg_multiplier = static_cast<unsigned int>(std::clamp(_wtoi(value), 2, 4));',
            "MFG config load",
        )

    marker = 'g_ngx_params->Set("DLSSG.OutputInterpolated", generated_output);\n    g_ngx_params->Set("DLSSG.MultiFrameCount", 1u); g_ngx_params->Set("DLSSG.MultiFrameIndex", 1u);'
    replacement = 'g_ngx_params->Set("DLSSG.OutputInterpolated", generated_output);\n    g_ngx_params->Set("DLSSG.MultiFrameCount", g_mfg_active_generated_count);\n    g_ngx_params->Set("DLSSG.MultiFrameIndex", g_mfg_active_frame_index);'
    if 'g_mfg_active_generated_count);' not in src:
        src = replace_once(src, marker, replacement, "DLSSG MFG parameters")

    marker = 'g_dlssg_module = have_dlssg ? LoadLibraryExW(dlssg_path, nullptr, LOAD_WITH_ALTERED_SEARCH_PATH) : nullptr;\n'
    if "dlss5_aio_mfg::Apply" not in src:
        addition = '''    if (g_dlssg_module != nullptr && g_mfg_multiplier > 2)\n    {\n        size_t gate_sites = 0, temporal_sites = 0;\n        std::string mfg_detail;\n        if (dlss5_aio_mfg::Apply(g_dlssg_module, gate_sites, temporal_sites, mfg_detail))\n            Log("%s", mfg_detail.c_str());\n        else\n            Log("Ada MFG unlock unavailable: %s; 3x/4x will fall back to 2x", mfg_detail.c_str());\n    }\n'''
        src = insert_after(src, marker, addition, "MFG runtime patch")

    old_struct = '''    Microsoft::WRL::ComPtr<ID3D12Resource> real_output;\n    Microsoft::WRL::ComPtr<ID3D12Resource> generated_output;\n    Microsoft::WRL::ComPtr<ID3D12Resource> original_input;'''
    new_struct = '''    Microsoft::WRL::ComPtr<ID3D12Resource> real_output;\n    Microsoft::WRL::ComPtr<ID3D12Resource> generated_output;\n    std::array<Microsoft::WRL::ComPtr<ID3D12Resource>, 2> mfg_generated_outputs;\n    unsigned int mfg_generated_count = 1;\n    Microsoft::WRL::ComPtr<ID3D12Resource> original_input;'''
    if "mfg_generated_outputs" not in src:
        src = replace_once(src, old_struct, new_struct, "Presentation MFG buffers")

    old_reset = '''        slot.generated_output.Reset();\n        slot.real_output.Reset();\n        slot.original_input.Reset();\n        slot.state.store(PresentationSlotFree, std::memory_order_release);'''
    new_reset = '''        slot.generated_output.Reset();\n        for (auto &output : slot.mfg_generated_outputs) output.Reset();\n        slot.mfg_generated_count = 1;\n        slot.real_output.Reset();\n        slot.original_input.Reset();\n        slot.state.store(PresentationSlotFree, std::memory_order_release);'''
    if "for (auto &output : slot.mfg_generated_outputs)" not in src:
        src = replace_once(src, old_reset, new_reset, "Presentation MFG reset")

    old_alloc = '''        if (!CreateTexture(ow, oh, result_format, true, D3D12_RESOURCE_STATE_COMMON, slot.real_output) ||\n            !CreateTexture(ow, oh, result_format, true, D3D12_RESOURCE_STATE_COMMON, slot.generated_output) ||\n            !CreateTexture(iw, ih, input_format, false, D3D12_RESOURCE_STATE_COMMON, slot.original_input))\n            return false;'''
    new_alloc = '''        if (!CreateTexture(ow, oh, result_format, true, D3D12_RESOURCE_STATE_COMMON, slot.real_output) ||\n            !CreateTexture(ow, oh, result_format, true, D3D12_RESOURCE_STATE_COMMON, slot.generated_output) ||\n            !CreateTexture(iw, ih, input_format, false, D3D12_RESOURCE_STATE_COMMON, slot.original_input))\n            return false;\n        slot.mfg_generated_count = std::clamp(g_mfg_multiplier, 2u, 4u) - 1u;\n        for (unsigned int generated = 1; generated < slot.mfg_generated_count; ++generated)\n            if (!CreateTexture(ow, oh, result_format, true, D3D12_RESOURCE_STATE_COMMON,\n                slot.mfg_generated_outputs[generated - 1]))\n                return false;'''
    if "slot.mfg_generated_count = std::clamp(g_mfg_multiplier" not in src:
        src = replace_once(src, old_alloc, new_alloc, "Presentation MFG allocation")

    old_local = '''    ID3D12Resource *real_output = pipeline_slot.real_output.Get();\n    ID3D12Resource *generated_output = pipeline_slot.generated_output.Get();\n    ID3D12Resource *original_snapshot = pipeline_slot.original_input.Get();\n    ScopedPresentationReservation direct_reservation;'''
    new_local = '''    ID3D12Resource *real_output = pipeline_slot.real_output.Get();\n    ID3D12Resource *generated_output = pipeline_slot.generated_output.Get();\n    ID3D12Resource *original_snapshot = pipeline_slot.original_input.Get();\n    ID3D12Resource *fg_outputs[3] = {generated_output, nullptr, nullptr};\n    unsigned int fg_generated_count = 1;\n    ScopedPresentationReservation direct_reservation;'''
    if "ID3D12Resource *fg_outputs[3]" not in src:
        src = replace_once(src, old_local, new_local, "FG output array")

    marker = '''        if (!real_output || !generated_output || !original_snapshot)\n        {\n            direct_reservation = {};\n            pipeline_slot.state.store(PipelineSlotFree, std::memory_order_release);\n            return false;\n        }\n'''
    addition = '''        PresentationFrameSlot &presentation = g_presentation_slots[direct_reservation.index];\n        fg_generated_count = EffectiveMfgGeneratedCount(true);\n        fg_outputs[0] = presentation.generated_output.Get();\n        for (unsigned int generated = 1; generated < fg_generated_count; ++generated)\n            fg_outputs[generated] = presentation.mfg_generated_outputs[generated - 1].Get();\n'''
    if "fg_generated_count = EffectiveMfgGeneratedCount(true)" not in src:
        src = insert_after(src, marker, addition, "FG direct output resources")

    marker = '''    const bool split_fg_path = evaluate_fg &&\n        PhaseScheduledFrameGenerationEnabled() &&\n        direct_reservation.index >= 0;'''
    repl = '''    const bool split_fg_path = evaluate_fg &&\n        PhaseScheduledFrameGenerationEnabled() &&\n        direct_reservation.index >= 0 &&\n        EffectiveMfgGeneratedCount(true) == 1;'''
    src = replace_once(src, marker, repl, "disable split path for MFG") if "EffectiveMfgGeneratedCount(true) == 1" not in src else src

    old_fg = '''    pipeline_slot.fg_split_submission = split_fg;\n    if (evaluate_fg && !split_fg)\n    {\n        D3D12_RESOURCE_BARRIER fg_begin[2] = {\n            Transition(real_output, D3D12_RESOURCE_STATE_UNORDERED_ACCESS,\n                D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE),\n            Transition(generated_output, D3D12_RESOURCE_STATE_COMMON,\n                D3D12_RESOURCE_STATE_UNORDERED_ACCESS)\n        };\n        commands->ResourceBarrier(2, fg_begin);\n        SetFgEvaluationContract(real_output, generated_output, depth, motion,\n            reset || g_fg_frames.load() == 0);\n        exception = 0;\n        fg_result = SafeEvaluateFg(&exception);\n        if (exception)\n        {\n            AbortNeuralFrameCommands(slot_index);\n            Log("DLSS-G evaluation exception 0x%08X; frame generation disabled", exception);\n            g_framegen_failed = true;\n            return false;\n        }\n    }'''
    new_fg = '''    pipeline_slot.fg_split_submission = split_fg;\n    unsigned int evaluated_fg_frames = 0;\n    if (evaluate_fg && !split_fg)\n    {\n        const unsigned int requested_generated_count =\n            EffectiveMfgGeneratedCount(direct_reservation.index >= 0);\n        fg_generated_count = requested_generated_count;\n        g_mfg_active_generated_count = requested_generated_count;\n        g_mfg_active_frame_index = 1;\n\n        D3D12_RESOURCE_BARRIER fg_begin[3] = {};\n        UINT fg_begin_count = 0;\n        fg_begin[fg_begin_count++] = Transition(real_output,\n            D3D12_RESOURCE_STATE_UNORDERED_ACCESS,\n            D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);\n        for (unsigned int generated = 0; generated < requested_generated_count; ++generated)\n            fg_begin[fg_begin_count++] = Transition(fg_outputs[generated],\n                D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_UNORDERED_ACCESS);\n        commands->ResourceBarrier(fg_begin_count, fg_begin);\n\n        const bool fg_reset = reset || g_fg_frames.load() == 0;\n        for (unsigned int generated = 0; generated < requested_generated_count; ++generated)\n        {\n            g_mfg_active_frame_index = generated + 1;\n            SetFgEvaluationContract(real_output, fg_outputs[generated], depth, motion,\n                fg_reset && generated == 0);\n            exception = 0;\n            fg_result = SafeEvaluateFg(&exception);\n            if (exception)\n            {\n                AbortNeuralFrameCommands(slot_index);\n                Log("DLSS-G MFG evaluation exception 0x%08X at generated frame %u; frame generation disabled",\n                    exception, generated + 1);\n                g_framegen_failed = true;\n                return false;\n            }\n            if (NVSDK_NGX_FAILED(fg_result))\n            {\n                Log("DLSS-G MFG evaluation failed: 0x%08X (%s) at generated frame %u",\n                    static_cast<unsigned int>(fg_result), ResultName(fg_result), generated + 1);\n                g_framegen_failed = true;\n                return false;\n            }\n            ++evaluated_fg_frames;\n        }\n    }'''
    if "evaluated_fg_frames" not in src:
        src = replace_once(src, old_fg, new_fg, "MFG evaluation loop")

    old_restore = '''    if (evaluate_fg && !split_fg)\n    {\n        restore[restore_count++] = Transition(real_output,\n            D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COMMON);\n        restore[restore_count++] = Transition(generated_output,\n            D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COMMON);\n    }\n    else'''
    new_restore = '''    if (evaluate_fg && !split_fg)\n    {\n        restore[restore_count++] = Transition(real_output,\n            D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COMMON);\n        for (unsigned int generated = 0; generated < evaluated_fg_frames; ++generated)\n            restore[restore_count++] = Transition(fg_outputs[generated],\n                D3D12_RESOURCE_STATE_UNORDERED_ACCESS, D3D12_RESOURCE_STATE_COMMON);\n    }\n    else'''
    if "evaluated_fg_frames; ++generated" not in src:
        src = replace_once(src, old_restore, new_restore, "MFG output restore")

    old_present_sig = '''static bool PresentProxySourcesOnWorker(ID3D12Resource *real_source,\n    ID3D12Resource *generated_source, ID3D12Resource *original_source,\n    bool has_generated_frame)'''
    new_present_sig = '''static bool PresentProxySourcesOnWorker(ID3D12Resource *real_source,\n    ID3D12Resource *generated_source, ID3D12Resource *original_source,\n    bool has_generated_frame, const PresentationFrameSlot *presentation_slot = nullptr)'''
    if "presentation_slot = nullptr" not in src:
        src = replace_once(src, old_present_sig, new_present_sig, "MFG presenter signature")

    old_present_sources = '''    ID3D12Resource *post_source = composite_post ? g_post_reshade_color.Get() : original_source;\n    ID3D12Resource *present_sources[2] = {\n        use_framegen ? generated_source : real_source,\n        real_source\n    };\n    const UINT present_count = use_framegen ? 2u : 1u;'''
    new_present_sources = '''    ID3D12Resource *post_source = composite_post ? g_post_reshade_color.Get() : original_source;\n    ID3D12Resource *present_sources[4] = {};\n    UINT generated_present_count = 0;\n    if (use_framegen)\n    {\n        generated_present_count = presentation_slot != nullptr ?\n            std::clamp(presentation_slot->mfg_generated_count, 1u, 3u) : 1u;\n        present_sources[0] = generated_source;\n        if (presentation_slot != nullptr && generated_present_count > 1)\n            for (UINT generated = 1; generated < generated_present_count; ++generated)\n                present_sources[generated] = presentation_slot->mfg_generated_outputs[generated - 1].Get();\n        present_sources[generated_present_count] = real_source;\n    }\n    else\n        present_sources[0] = real_source;\n    const UINT present_count = use_framegen ? generated_present_count + 1u : 1u;'''
    if "generated_present_count" not in src:
        src = replace_once(src, old_present_sources, new_present_sources, "MFG presentation sources")

    old_telemetry = '''    const bool record_proxy_gpu = g_performance_telemetry_enabled &&\n        !g_proxy_telemetry_pending && g_proxy_telemetry_query_heap && g_proxy_telemetry_readback;'''
    new_telemetry = '''    const bool record_proxy_gpu = g_performance_telemetry_enabled &&\n        generated_present_count <= 1 &&\n        !g_proxy_telemetry_pending && g_proxy_telemetry_query_heap && g_proxy_telemetry_readback;'''
    if "generated_present_count <= 1" not in src:
        src = replace_once(src, old_telemetry, new_telemetry, "MFG telemetry guard")

    src = src.replace('            RecordAcceptedProxyPresent(use_framegen && present_index == 0);',
                       '            RecordAcceptedProxyPresent(use_framegen && present_index < generated_present_count);', 1)

    old_staged_call = '''    const bool presented = PresentProxySourcesOnWorker(slot.real_output.Get(),\n        slot.generated_output.Get(), slot.original_input.Get(), slot.has_generated_frame);'''
    new_staged_call = '''    const PresentationFrameSlot *presentation_slot = nullptr;\n    const bool presented = PresentProxySourcesOnWorker(slot.real_output.Get(),\n        slot.generated_output.Get(), slot.original_input.Get(), slot.has_generated_frame,\n        presentation_slot);'''
    # The direct staged presenter has a PresentationFrameSlot, so patch its exact function body below.
    if "const PresentationFrameSlot *presentation_slot = nullptr" not in src:
        raise RuntimeError("unexpected source state before presenter call patch")

    old_stage_func = '''static bool PresentStagedFrameOnWorker(UINT slot_index)\n{'''
    stage_body_marker = '''    const bool presented = PresentProxySourcesOnWorker(slot.real_output.Get(),\n        slot.generated_output.Get(), slot.original_input.Get(), slot.has_generated_frame);'''
    stage_replacement = '''    const bool presented = PresentProxySourcesOnWorker(slot.real_output.Get(),\n        slot.generated_output.Get(), slot.original_input.Get(), slot.has_generated_frame, &slot);'''
    # Replace the occurrence nearest the staged presenter by locating the function slice.
    pos = src.find(old_stage_func)
    if pos < 0:
        raise RuntimeError("PresentStagedFrameOnWorker not found")
    next_pos = src.find('\nstatic ', pos + len(old_stage_func))
    slice_end = len(src) if next_pos < 0 else next_pos
    segment = src[pos:slice_end]
    if '&slot);' not in segment:
        segment2 = replace_once(segment, stage_body_marker, stage_replacement, "staged presenter MFG slot")
        src = src[:pos] + segment2 + src[slice_end:]

    src = src.replace('        g_framegen_enabled = external_fg_enabled != 0;\n',
                      '        g_framegen_enabled = external_fg_enabled != 0;\n', 1)

    if '"MfgMultiplier"' in src and 'MFG multiplier (RTX 40 experimental)' not in src:
        raise RuntimeError("MFG config/menu integration is inconsistent")

    SRC.write_text(src, encoding="utf-8")
    MENU.write_text(menu, encoding="utf-8")
    print("Applied DLSS5 AIO Ada MFG integration")


if __name__ == "__main__":
    main()
