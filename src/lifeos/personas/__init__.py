"""Persona layer — định nghĩa tính cách của từng agent."""

from .base import Persona
from .registry import PERSONAS, get_persona
from .tone_adapter import build_tone_instruction

__all__ = ["Persona", "PERSONAS", "get_persona", "build_tone_instruction"]