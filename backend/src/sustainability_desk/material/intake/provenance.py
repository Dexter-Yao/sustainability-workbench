# ABOUTME: 资料规范化审阅载荷的唯一稳定指纹 owner，供投影、裁决和运行冻结共同使用。
# ABOUTME: 指纹覆盖片段、locator、warnings 与处理器身份/质量语义，明确排除运行时间戳。
# ABOUTME(en): Sole owner of the stable fingerprint for normalized material review payloads.
# ABOUTME(en): It covers fragments, locators, warnings and processor identity/quality, excluding run timestamps.
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from sustainability_desk.material.intake.models import NormalizedMaterial, ProcessingStep


def normalized_material_review_fingerprint(
    material: NormalizedMaterial,
    processing_steps: Sequence[ProcessingStep],
) -> str:
    """对用户实际审阅的规范化内容与解析质量语义生成 canonical SHA-256。"""

    payload = {
        "fragments": [
            fragment.model_dump(
                mode="json",
                exclude_computed_fields=True,
            )
            for fragment in material.fragments
        ],
        "warnings": list(material.warnings),
        "processingSteps": [
            {
                "step": step.step,
                "processor": step.processor,
                "status": step.status,
                "parser": step.parser,
                "model": step.model,
                "route": step.route,
                "inputFingerprint": step.input_fingerprint,
                "outputFingerprint": step.output_fingerprint,
                "qualityFlags": list(step.quality_flags),
                "message": step.message,
            }
            for step in processing_steps
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
