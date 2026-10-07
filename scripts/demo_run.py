"""Chạy demo Life OS từ dòng lệnh.

Mặc định dùng LLM giả (offline). Thêm --real để gọi API thật (cần .env).
"""

from __future__ import annotations

import argparse
from datetime import date

from lifeos import persistence, progress, srs
from lifeos.agents import tutor
from lifeos.clarify import clarifying_questions
from lifeos.demo import DemoLLM
from lifeos.graph import NODE_LABELS, iter_adjust, iter_plan
from lifeos.llm import get_llm, has_api_key
from lifeos.models import (
    CommunicationStyle,
    EnergyWindow,
    StrictnessLevel,
    TaskStatus,
    UserProfile,
)
from lifeos.tools.calendar import write_ics

TASK_TYPE_LABEL = {
    "study": "Học",
    "review": "Ôn tập",
    "project": "Dự án",
    "interview_prep": "Luyện phỏng vấn",
    "rest": "Nghỉ",
    "other": "Khác",
}


def default_profile() -> UserProfile:
    return UserProfile(
        name="Minh",
        goal_summary=(
            "Chuyển từ vị trí hành chính sang Data Analyst trong 6 tháng, "
            "vẫn đi làm full-time"
        ),
        current_skills=["Excel", "SQL cơ bản", "Tiếng Anh đọc hiểu"],
        hours_per_week=10,
        energy_windows=[EnergyWindow(label="Tối", start="20:00", end="22:00")],
        communication_style=CommunicationStyle.DIRECT,
        strictness=StrictnessLevel.STRICT,
        notes="Không học được giờ hành chính.",
    )


def print_plan(plan, event=None) -> None:
    print("=" * 72)
    print(f"MỤC TIÊU: {plan.goal.description}")
    print(f"Thời hạn: {plan.goal.deadline_months} tháng")
    print("=" * 72)

    print("\n[1] KHOẢNG TRỐNG KỸ NĂNG (Chiến Lược Gia)")
    for gap in plan.gaps:
        print(f"  - (ưu tiên {gap.priority}) {gap.skill}: {gap.rationale}")

    if plan.study_plan:
        print(f"\n[2] LỘ TRÌNH HỌC (Giáo Viên) — {plan.study_plan.total_weeks} tuần")
        for module in plan.study_plan.modules:
            print(f"  {module.order + 1}. {module.title} ({module.duration_hours}h)")
        print(f"  Định hướng: {plan.study_plan.overview}")

    if plan.first_week:
        week = plan.first_week
        print(
            f"\n[3] LỊCH TUẦN {week.week} (Huấn Luyện Viên Kỷ Luật) — "
            f"{week.total_hours} giờ, {len(week.tasks)} buổi"
        )
        for task in week.tasks:
            label = TASK_TYPE_LABEL.get(
                getattr(task.task_type, "value", task.task_type), "Khác"
            )
            print(
                f"  {task.day} {task.start} | {task.duration_min:>3} phút | "
                f"{label:<16} | {task.title}"
            )

    if plan.roundtable:
        print("\n[4] HỘI ĐỒNG PERSONA")
        for turn in plan.roundtable.turns:
            print(f"\n  ▸ {turn.persona} ({turn.role}):")
            print(f"    {turn.content}")
        if plan.roundtable.synthesis:
            print(f"\n  ★ {plan.roundtable.synthesis.persona} tổng hợp:")
            print(f"    {plan.roundtable.synthesis.content}")

    if event is not None:
        print("\n[5] ĐIỀU CHỈNH KẾ HOẠCH")
        print(f"  Lý do: {event.reason}")
        print(f"  Tuần {event.old_week} -> tuần {event.new_week}")
        print(f"  {event.message}")

    if plan.weeks:
        print(f"\n[6] LỊCH NHIỀU TUẦN — {len(plan.weeks)} tuần")
        for week in plan.weeks:
            modules = ", ".join(
                dict.fromkeys(t.module_ref for t in week.tasks if t.module_ref)
            )
            print(
                f"  Tuần {week.week:>2}: {len(week.tasks)} buổi, "
                f"{week.total_hours}h — {modules or 'ôn tập'}"
            )


def print_progress(plan) -> None:
    """In báo cáo tiến độ (mô phỏng đã hoàn thành tuần 1)."""
    print("\n[7] TIẾN ĐỘ")
    marked = progress.mark_week(plan, 1, TaskStatus.DONE)
    print(f"  (mô phỏng: đánh dấu xong {marked} buổi của tuần 1)")

    prog = progress.program_progress(plan)
    print(f"  Hoàn thành: {prog.overall_pct}% ({prog.hours_done}/{prog.hours_planned} giờ)")
    print(f"  Tuần hiện tại: {prog.current_week} | chuỗi tuần xong: {prog.streak}")
    print(f"  Trạng thái: {'đúng tiến độ' if prog.on_track else 'chệch tiến độ'}")
    print(f"  {prog.note}")

    upcoming = progress.next_tasks(plan, limit=3)
    if upcoming:
        print("  Buổi sắp tới:")
        for task in upcoming:
            print(f"    - {task.day} {task.start} | {task.title}")


def print_review(plan) -> None:
    """In vòng ôn tập cách quãng."""
    print("\n[8] ÔN TẬP CÁCH QUÃNG (SRS)")
    today = date.today()
    cards = srs.cards_from_plan(plan, today=today)
    if not cards:
        print("  Chưa có thẻ ôn tập (lộ trình chưa có module).")
        return
    print(f"  {srs.summarize(cards, today=today)}")
    # Mô phỏng một lượt ôn để thấy khoảng cách giãn ra
    card = cards[0]
    print(f"  Ví dụ thẻ '{card.topic}':")
    for quality, label in [(5, "nhớ tốt"), (5, "nhớ tốt"), (1, "quên")]:
        srs.review(card, quality, today=today)
        print(
            f"    trả lời {label:<8} -> lặp {card.repetitions}, "
            f"hẹn lại sau {card.interval_days} ngày, ease {card.ease:.2f}"
        )


def print_quiz(llm, plan) -> None:
    """In bài kiểm tra nhiều câu kèm kết quả chấm."""
    print("\n[9] KIỂM TRA HIỂU BIẾT")
    topic = "SQL JOIN"
    if plan.study_plan and plan.study_plan.modules:
        topic = plan.study_plan.modules[0].title

    questions = tutor.quiz_set(llm, topic, "tone", count=3)
    print(f"  Chủ đề: {topic} — {len(questions)} câu")
    for index, question in enumerate(questions, start=1):
        print(f"\n  Câu {index}: {question.question}")
        for option_index, option in enumerate(question.options):
            print(f"    {option_index}. {option}")

    # Mô phỏng: đúng câu đầu, sai các câu còn lại
    answers = [
        q.answer_index if i == 0 else (q.answer_index + 1) % max(1, len(q.options))
        for i, q in enumerate(questions)
    ]
    result = tutor.grade(answers, questions)
    print(f"\n  Kết quả: {result.correct}/{result.total} ({result.score_pct}%)")
    for line in result.detail:
        print(f"    {line}")
    if result.weak_topics:
        print("  Cần ôn lại:")
        for weak in tutor.follow_up_topics(result):
            print(f"    - {weak}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo Life OS")
    parser.add_argument(
        "--real", action="store_true", help="Gọi LLM thật thay vì LLM giả"
    )
    parser.add_argument(
        "--skip-adjust", action="store_true", help="Không chạy phần điều chỉnh"
    )
    parser.add_argument(
        "--weeks", type=int, default=12, help="Số tuần sinh ra trong lịch (mặc định 12)"
    )
    parser.add_argument(
        "--ics", metavar="PATH", help="Xuất lịch ra file .ics để import vào calendar"
    )
    parser.add_argument(
        "--progress", action="store_true", help="In báo cáo tiến độ (mô phỏng)"
    )
    parser.add_argument(
        "--quiz", action="store_true", help="Chạy thử phần kiểm tra hiểu biết"
    )
    parser.add_argument(
        "--save", action="store_true", help="Lưu kế hoạch vào SQLite và in id"
    )
    parser.add_argument(
        "--list-plans", action="store_true", help="Liệt kê kế hoạch đã lưu rồi thoát"
    )
    args = parser.parse_args()

    if args.list_plans:
        summaries = persistence.list_plans(persistence.default_store())
        if not summaries:
            print("Chưa có kế hoạch nào được lưu.")
        for summary in summaries:
            print(
                f"  #{summary.id} | {summary.created_at} | "
                f"{summary.weeks} tuần | {summary.progress_pct}% | "
                f"{summary.goal_summary}"
            )
        return

    profile = default_profile()

    questions = clarifying_questions(profile.goal_summary)
    print(f"Hồ sơ: {profile.name} | {profile.hours_per_week} giờ/tuần")
    print(f"Câu hỏi làm rõ còn lại: {questions or 'không (mục tiêu đã đủ rõ)'}")

    if args.real:
        if not has_api_key():
            raise SystemExit(
                "Chưa có LLM_API_KEY trong .env — bỏ --real hoặc điền key."
            )
        llm = get_llm()
        print("Chế độ: LLM thật")
    else:
        llm = DemoLLM()
        print("Chế độ: LLM giả (offline demo)")

    plan = None
    print("\n--- Tiến độ lập kế hoạch ---")
    for node, update in iter_plan(profile, llm=llm, program_weeks=args.weeks):
        print(f"  {NODE_LABELS.get(node, node)}")
        if "plan" in update:
            plan = update["plan"]
    if plan is None:
        raise SystemExit("Đồ thị không trả về kế hoạch.")
    print_plan(plan)

    if args.progress:
        print_progress(plan)

    if args.quiz:
        print_quiz(llm, plan)

    if args.ics:
        target = write_ics(plan.weeks, args.ics, calendar_name="Life OS")
        print(f"\n[ICS] Đã ghi {len(plan.weeks)} tuần ra {target}")

    if args.save:
        plan_id = persistence.save_plan(persistence.default_store(), plan)
        print(f"\n[LƯU] Kế hoạch id #{plan_id} (xem lại bằng --list-plans)")

    if not args.skip_adjust:
        print("\n--- Tiến độ điều chỉnh ---")
        new_plan = None
        event = None
        for node, update in iter_adjust(
            plan,
            profile,
            reason="Trượt 2 buổi vì deadline gấp ở công việc chính",
            missed=["Học SQL: SELECT, WHERE, JOIN", "Luyện SQL trên SQLBolt"],
            llm=llm,
        ):
            print(f"  {NODE_LABELS.get(node, node)}")
            if "plan_out" in update:
                new_plan = update["plan_out"]
            if "event" in update:
                event = update["event"]
        if new_plan is not None:
            print_plan(new_plan, event)

    if isinstance(llm, DemoLLM):
        print(f"\n(các lời gọi LLM: {llm.calls})")


if __name__ == "__main__":
    main()