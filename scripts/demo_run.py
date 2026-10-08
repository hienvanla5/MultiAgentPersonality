"""Chạy demo Life OS từ dòng lệnh.

Mặc định dùng LLM giả (offline). Thêm --real để gọi API thật (cần .env).
"""

from __future__ import annotations

import argparse
from datetime import date

from lifeos import persistence, progress, reflection, srs
from lifeos.acl import MessageBus
from lifeos.agents import team, tutor
from lifeos.agents.contract_net import ContractNet
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


def print_team(goal: str, llm=None) -> None:
    """In quá trình tự tổ chức nhóm: phân rã, lập nhóm, thương lượng."""
    print("\n[10] TỰ TỔ CHỨC NHÓM (phân rã → lập nhóm → thương lượng)")
    plan = team.self_organize(goal, llm=llm)
    source = "LLM phân rã" if llm is not None else "quy tắc cố định"
    print(f"  Nguồn phân rã: {source}")

    print(f"  Mục tiêu: {plan.breakdown.goal}")
    print(f"  Phân rã thành {len(plan.breakdown.tasks)} nhiệm vụ:")
    for task in plan.breakdown.tasks:
        print(
            f"    - [{task.priority}] {task.id} "
            f"(kỹ năng: {task.skill}, công sức {task.effort})"
        )

    print(f"  Nhóm tự lập: {', '.join(plan.members)}")
    if plan.excluded:
        print(f"  Không tham gia (không có việc phù hợp): {', '.join(plan.excluded)}")

    print("\n  Kết quả thương lượng Contract Net:")
    for result in plan.results:
        if result.assigned:
            print(
                f"    ✓ {result.task.id:<14} → {result.awarded_to:<10} "
                f"({result.bid_count} thầu, {len(result.refusals)} từ chối)"
            )
        else:
            print(f"    ✗ {result.task.id:<14} → không ai nhận: {result.reason}")


def print_acl(goal: str, llm=None) -> None:
    """In bản ghi tin nhắn ACL của một phiên thương lượng."""
    print("\n[11] GIAO THỨC ACL (bản ghi tin nhắn)")
    bus = MessageBus()
    net = ContractNet(bus)

    # Phân rã một lần rồi dùng lại — gọi hai lần sẽ tốn thêm một lượt LLM.
    breakdown = team.decompose(goal, llm=llm)
    members, _ = team.build_roster(breakdown)
    if not breakdown.tasks or not members:
        print("  Không có nhiệm vụ hoặc không có thành viên nào để thương lượng.")
        return

    # Chỉ chạy một nhiệm vụ để bản ghi đủ ngắn mà vẫn đủ bốn pha.
    net.run(breakdown.tasks[0], members)

    for message in bus.messages:
        print(f"    {message.render()}")
    print(f"\n  Tổng {len(bus)} tin nhắn trong hội thoại.")


def print_reflection(store) -> None:
    """In kết quả suy ngẫm từ các kế hoạch đã lưu."""
    print("\n[12] SUY NGẪM TỪ QUÁ KHỨ")
    past = persistence.recent_plans(store, limit=5)
    if not past:
        print("  Chưa có kế hoạch nào được lưu — không có gì để nhìn lại.")
        return

    stats = reflection.outcome_stats(past)
    print(f"  Đã xem {stats.plans} kế hoạch có dữ liệu hoàn thành.")
    print(f"  Tỉ lệ hoàn thành trung bình: {stats.avg_completion * 100:.0f}%")
    print(f"  Hệ số tải đề xuất cho lần sau: {stats.suggested_load_factor}")
    print(f"  {stats.reason}")


def print_srs_persistence(plan, store) -> None:
    """Lưu thẻ ôn tập xuống SQLite rồi đọc lại để chứng minh thẻ không mất."""
    print("\n[13] THẺ ÔN TẬP LƯU XUỐNG SQLITE")
    today = date.today()
    plan_id = persistence.save_plan(store, plan)
    print(f"  Kế hoạch được lưu với id #{plan_id}")

    cards = srs.cards_from_plan(plan, today=today)
    if not cards:
        print("  Lộ trình chưa có module nên chưa có thẻ nào.")
        return

    written = persistence.save_review_cards(store, plan_id, cards)
    print(f"  Đã ghi {written} thẻ.")

    # Ghi lại lần nữa: phải ghi đè, không nhân đôi
    persistence.save_review_cards(store, plan_id, cards)
    print(f"  Ghi lại lần hai -> vẫn {store.count_cards(plan_id)} thẻ (ghi đè).")

    # Mô phỏng một lượt ôn rồi đọc lại từ DB
    topic = cards[0].topic
    updated = persistence.review_and_save(store, plan_id, topic, quality=5, today=today)
    print(f"  Ôn thẻ '{topic}' -> hẹn lại sau {updated.interval_days} ngày.")

    reloaded = persistence.load_review_cards(store, plan_id)
    match = next(c for c in reloaded if c.topic == topic)
    print(f"  Đọc lại từ SQLite: {len(reloaded)} thẻ, thẻ vừa ôn có")
    print(
        f"    lặp {match.repetitions} lần, khoảng cách {match.interval_days} ngày, "
        f"đến hạn {match.due_date.isoformat()}"
    )

    due = persistence.due_review_cards(store, plan_id, today=today)
    print(f"  Đến hạn hôm nay: {len(due)} thẻ.")


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
    parser.add_argument(
        "--team",
        action="store_true",
        help="Chạy tự tổ chức nhóm + in bản ghi giao thức ACL",
    )
    parser.add_argument(
        "--adapt",
        action="store_true",
        help="Suy ngẫm từ kế hoạch đã lưu để điều chỉnh mức tải kế hoạch mới",
    )
    parser.add_argument(
        "--srs",
        action="store_true",
        help="Lưu thẻ ôn tập xuống SQLite rồi đọc lại để kiểm chứng",
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
    past_plans = (
        persistence.recent_plans(persistence.default_store(), limit=5)
        if args.adapt
        else None
    )
    if args.adapt:
        print(f"Chế độ thích ứng: xem lại {len(past_plans or [])} kế hoạch đã lưu.")

    print("\n--- Tiến độ lập kế hoạch ---")
    for node, update in iter_plan(
        profile, llm=llm, program_weeks=args.weeks, past_plans=past_plans
    ):
        print(f"  {NODE_LABELS.get(node, node)}")
        if "plan" in update:
            plan = update["plan"]
    if plan is None:
        raise SystemExit("Đồ thị không trả về kế hoạch.")
    print_plan(plan)

    if plan.reflection is not None:
        print("\n[SUY NGẪM]")
        print(f"  {plan.reflection.stats.reason}")
        if plan.reflection.advice:
            print(f"  Lời khuyên: {plan.reflection.advice[:300]}")

    if args.team:
        # Phân rã bằng chính LLM đang dùng (thật hoặc giả), có lưới an toàn.
        print_team(profile.goal_summary, llm=llm)
        print_acl(profile.goal_summary, llm=llm)

    if args.adapt:
        print_reflection(persistence.default_store())

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

    if args.srs:
        print_srs_persistence(plan, persistence.default_store())

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