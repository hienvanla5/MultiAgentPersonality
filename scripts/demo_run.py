"""Chạy demo Life OS từ dòng lệnh.

Mặc định dùng LLM giả (offline). Thêm --real để gọi API thật (cần .env).
"""

from __future__ import annotations

import argparse

from lifeos.clarify import clarifying_questions
from lifeos.demo import DemoLLM
from lifeos.graph import NODE_LABELS, iter_adjust, iter_plan
from lifeos.llm import get_llm, has_api_key
from lifeos.models import (
    CommunicationStyle,
    EnergyWindow,
    StrictnessLevel,
    UserProfile,
)

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo Life OS")
    parser.add_argument(
        "--real", action="store_true", help="Gọi LLM thật thay vì LLM giả"
    )
    parser.add_argument(
        "--skip-adjust", action="store_true", help="Không chạy phần điều chỉnh"
    )
    args = parser.parse_args()

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
    for node, update in iter_plan(profile, llm=llm):
        print(f"  {NODE_LABELS.get(node, node)}")
        if "plan" in update:
            plan = update["plan"]
    if plan is None:
        raise SystemExit("Đồ thị không trả về kế hoạch.")
    print_plan(plan)

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