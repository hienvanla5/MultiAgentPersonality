"""Test persona layer và bộ sinh câu hỏi làm rõ."""

from __future__ import annotations

import pytest

from lifeos.clarify import clarifying_questions, needs_clarification
from lifeos.models import CommunicationStyle, StrictnessLevel, UserProfile
from lifeos.personas import PERSONAS, build_tone_instruction, get_persona

EXPECTED_KEYS = {"orchestrator", "career", "tutor", "scheduler", "critic", "nudger"}


def test_six_personas_defined():
    assert set(PERSONAS) == EXPECTED_KEYS


def test_persona_has_required_fields():
    for key, persona in PERSONAS.items():
        assert persona.key == key
        assert persona.name.strip()
        assert persona.role.strip()
        assert persona.tone.strip()
        assert persona.system_prompt.strip()


def test_render_without_tone_is_base_prompt():
    persona = get_persona("career")
    assert persona.render_system_prompt("") == persona.system_prompt.strip()


def test_render_with_tone_appends_instruction():
    persona = get_persona("career")
    rendered = persona.render_system_prompt("CHỈ THỊ RIÊNG")
    assert persona.system_prompt.strip() in rendered
    assert "CHỈ THỊ RIÊNG" in rendered


def test_get_persona_unknown_raises():
    with pytest.raises(KeyError):
        get_persona("khong-ton-tai")


def test_tone_direct_and_strict():
    prof = UserProfile(
        communication_style=CommunicationStyle.DIRECT,
        strictness=StrictnessLevel.STRICT,
    )
    tone = build_tone_instruction(prof)
    assert "thẳng thắn" in tone
    assert "kỷ luật" in tone


def test_tone_gentle_and_lenient():
    prof = UserProfile(
        communication_style=CommunicationStyle.GENTLE,
        strictness=StrictnessLevel.LENIENT,
    )
    tone = build_tone_instruction(prof)
    assert "nhẹ nhàng" in tone
    assert "thoải mái" in tone


def test_tone_mentions_name_when_custom():
    assert "Lan" in build_tone_instruction(UserProfile(name="Lan"))


def test_tone_omits_default_name():
    assert "bạn" not in build_tone_instruction(UserProfile(name="bạn"))


def test_clarify_returns_questions_for_vague_goal():
    questions = clarifying_questions("kiếm nhiều tiền hơn")
    assert 1 <= len(questions) <= 3


def test_clarify_returns_empty_for_clear_goal():
    goal = "Chuyển sang Data Analyst trong 6 tháng, 10 giờ mỗi tuần"
    assert clarifying_questions(goal) == []


def test_needs_clarification_flag():
    assert needs_clarification("abc") is True
    assert needs_clarification("Học Data Analyst trong 6 tháng, 10 giờ/tuần") is False
