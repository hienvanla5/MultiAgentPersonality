"""Định nghĩa lớp Persona."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Persona:
    key: str
    name: str
    role: str                 # vai trò ngắn gọn
    tone: str                 # mô tả giọng điệu mặc định
    values: list[str] = field(default_factory=list)
    system_prompt: str = ""

    def render_system_prompt(self, tone_instruction: str = "") -> str:
        """Trả về system prompt, nối thêm chỉ thị giọng điệu theo người dùng nếu có."""
        base = self.system_prompt.strip()
        if tone_instruction:
            base += (
                "\n\n## Hướng dẫn giọng điệu theo người dùng (được điều chỉnh riêng)\n"
                + tone_instruction
            )
        return base
