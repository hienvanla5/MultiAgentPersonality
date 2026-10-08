"""Tone adapter — chuyển UserProfile thành chỉ thị giọng điệu."""

from __future__ import annotations

from ..models import CommunicationStyle, StrictnessLevel, UserProfile

_COMM_STYLE_INSTRUCTION = {
    CommunicationStyle.DIRECT: (
        "Nói thẳng thắn, đi thẳng vào trọng tâm, không vòng vo. "
        "Ưu tiên lời khuyên ngắn gọn, thực dụng."
    ),
    CommunicationStyle.GENTLE: (
        "Dùng lời lẽ nhẹ nhàng, ấm áp, tránh từ ngữ mạnh hay gây áp lực. "
        "Luôn kèm theo lời động viên và ghi nhận nỗ lực."
    ),
    CommunicationStyle.BALANCED: (
        "Cân bằng giữa sự thẳng thắn và khích lệ. "
        "Rõ ràng, tôn trọng, không gay gắt cũng không dài dòng."
    ),
}

_STRICTNESS_INSTRUCTION = {
    StrictnessLevel.STRICT: (
        "Nhấn mạnh kỷ luật, đặt chuẩn cao, đừng ngại nhắc nhở nghiêm túc "
        "khi người dùng lệch kế hoạch."
    ),
    StrictnessLevel.MODERATE: (
        "Giữ mức kỷ luật vừa phải: nhắc nhở khi cần nhưng vẫn linh hoạt."
    ),
    StrictnessLevel.LENIENT: (
        "Ưu tiên sự thoải mái, tránh gây áp lực; khi lệch kế hoạch hãy "
        "hướng dẫn nhẹ nhàng thay vì nhắc nhở."
    ),
}


def build_tone_instruction(profile: UserProfile) -> str:
    """Tạo một chuỗi chỉ thị giọng điệu dựa trên hồ sơ người dùng."""
    parts = [
        _COMM_STYLE_INSTRUCTION[profile.communication_style],
        _STRICTNESS_INSTRUCTION[profile.strictness],
    ]
    if profile.name and profile.name != "bạn":
        parts.append(f"Gọi người dùng bằng tên '{profile.name}' khi phù hợp.")
    return " ".join(parts)
