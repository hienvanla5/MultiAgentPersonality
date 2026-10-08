"""Test quiz nhiều câu và chấm điểm."""

from __future__ import annotations

from lifeos.agents import tutor
from lifeos.agents.schemas import Quiz
from lifeos.models import QuizResult


def _q(question: str, answer: int = 0) -> Quiz:
    return Quiz(
        question=question,
        options=["a", "b", "c", "d"],
        answer_index=answer,
        explanation="vì thế",
    )


# --- quiz_set ---


def test_quiz_set_returns_requested_count(fake_llm):
    questions = tutor.quiz_set(fake_llm, "SQL JOIN", "tone", count=2)
    assert len(questions) == 2
    assert all(isinstance(q, Quiz) for q in questions)


def test_quiz_set_count_capped_at_available(fake_llm):
    # FakeLLM luôn trả 3 câu, xin 5 thì chỉ nhận được 3
    assert len(tutor.quiz_set(fake_llm, "SQL", "tone", count=5)) == 3


def test_quiz_set_count_zero_becomes_one(fake_llm):
    assert len(tutor.quiz_set(fake_llm, "SQL", "tone", count=0)) == 1


def test_quiz_set_questions_are_distinct(fake_llm):
    questions = tutor.quiz_set(fake_llm, "SQL JOIN", "tone", count=3)
    texts = [q.question for q in questions]
    assert len(set(texts)) == len(texts)


def test_quiz_set_uses_tutor_persona(fake_llm):
    tutor.quiz_set(fake_llm, "SQL", "tone", count=2)
    assert fake_llm.count("QuizSet") == 1


# --- grade ---


def test_grade_all_correct():
    questions = [_q("q1", 0), _q("q2", 1), _q("q3", 2)]
    result = tutor.grade([0, 1, 2], questions)
    assert result.total == 3
    assert result.correct == 3
    assert result.score_pct == 100
    assert result.weak_topics == []


def test_grade_all_wrong_lists_every_weak_topic():
    questions = [_q("q1", 0), _q("q2", 1)]
    result = tutor.grade([3, 3], questions)
    assert result.correct == 0
    assert result.score_pct == 0
    assert result.weak_topics == ["q1", "q2"]


def test_grade_partial_score():
    questions = [_q("q1", 0), _q("q2", 0), _q("q3", 0), _q("q4", 0)]
    result = tutor.grade([0, 0, 1, 2], questions)
    assert result.correct == 2
    assert result.score_pct == 50
    assert result.weak_topics == ["q3", "q4"]


def test_grade_blank_answer_counts_wrong():
    questions = [_q("q1", 0), _q("q2", 0)]
    result = tutor.grade([0, -1], questions)
    assert result.correct == 1
    assert result.weak_topics == ["q2"]


def test_grade_missing_answers_treated_as_blank():
    questions = [_q("q1", 0), _q("q2", 0), _q("q3", 0)]
    result = tutor.grade([0], questions)
    assert result.total == 3
    assert result.correct == 1
    assert len(result.weak_topics) == 2


def test_grade_detail_mentions_each_question():
    questions = [_q("q1", 0), _q("q2", 1)]
    result = tutor.grade([0, 3], questions)
    assert len(result.detail) == 2
    assert "Câu 1: Đúng" in result.detail[0]
    assert "Câu 2: Sai" in result.detail[1]


def test_grade_empty_quiz():
    result = tutor.grade([], [])
    assert result.total == 0
    assert result.score_pct == 0


def test_grade_extra_answers_ignored():
    questions = [_q("q1", 0)]
    result = tutor.grade([0, 1, 2], questions)
    assert result.total == 1
    assert result.correct == 1


# --- follow_up_topics ---


def test_follow_up_topics_returns_weak_ones():
    result = QuizResult(total=3, correct=1, weak_topics=["a", "b"])
    assert tutor.follow_up_topics(result) == ["a", "b"]


def test_follow_up_topics_respects_limit():
    result = QuizResult(total=4, correct=0, weak_topics=["a", "b", "c", "d"])
    assert tutor.follow_up_topics(result, limit=2) == ["a", "b"]


def test_follow_up_topics_none_when_perfect():
    assert tutor.follow_up_topics(QuizResult(total=3, correct=3)) == []


# --- tích hợp: quiz rồi chấm ---


def test_quiz_then_grade_end_to_end(fake_llm):
    questions = tutor.quiz_set(fake_llm, "SQL JOIN", "tone", count=3)
    answers = [q.answer_index for q in questions]
    result = tutor.grade(answers, questions)
    assert result.correct == result.total
    assert result.score_pct == 100


def test_demo_llm_quiz_set_is_usable():
    from lifeos.demo import DemoLLM

    questions = tutor.quiz_set(DemoLLM(), "SQL JOIN", "tone", count=3)
    assert len(questions) == 3
    for question in questions:
        assert question.question
        assert len(question.options) >= 2
        assert 0 <= question.answer_index < len(question.options)
