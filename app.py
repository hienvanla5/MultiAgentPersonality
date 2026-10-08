"""Giao diện Streamlit cho Life OS.

Chạy: uv run streamlit run app.py
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from lifeos import persistence, progress, srs
from lifeos.acl import MessageBus
from lifeos.agents import team, tutor
from lifeos.agents.contract_net import ContractNet
from lifeos.clarify import clarifying_questions
from lifeos.config import get_settings
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
from lifeos.personas import build_tone_instruction
from lifeos.tools.calendar import tasks_to_ics

st.set_page_config(page_title="Life OS", page_icon="🧭", layout="wide")

DEFAULT_GOAL = (
    "Chuyển từ vị trí hành chính sang Data Analyst trong 6 tháng, "
    "vẫn đi làm full-time"
)

TASK_LABEL = {
    "study": "Học",
    "review": "Ôn tập",
    "project": "Dự án",
    "interview_prep": "Luyện phỏng vấn",
    "rest": "Nghỉ",
    "other": "Khác",
}

STYLE_OPTIONS = {
    "Thẳng thắn": CommunicationStyle.DIRECT,
    "Nhẹ nhàng": CommunicationStyle.GENTLE,
    "Cân bằng": CommunicationStyle.BALANCED,
}

STRICT_OPTIONS = {
    "Nghiêm khắc": StrictnessLevel.STRICT,
    "Vừa phải": StrictnessLevel.MODERATE,
    "Dễ tính": StrictnessLevel.LENIENT,
}

PERSONA_AVATAR = {
    "Người Phản Biện": "🔍",
    "Người Động Viên": "💪",
    "Người Dẫn Đường": "🧭",
    "Chiến Lược Gia": "🎯",
    "Giáo Viên": "📚",
    "Huấn Luyện Viên Kỷ Luật": "⏰",
}


def render_sidebar() -> tuple[UserProfile, bool, int, bool]:
    st.sidebar.title("🧭 Life OS")
    st.sidebar.caption(
        "Hồ sơ dùng để cá nhân hoá kế hoạch **và** giọng điệu của mọi agent."
    )

    name = st.sidebar.text_input("Tên", "Minh")
    goal = st.sidebar.text_area("Mục tiêu", DEFAULT_GOAL, height=110)
    skills_raw = st.sidebar.text_input(
        "Kỹ năng hiện có (cách nhau bằng dấu phẩy)", "Excel, SQL cơ bản"
    )
    hours = st.sidebar.slider("Giờ mỗi tuần", 1, 40, 10)
    weeks = st.sidebar.slider(
        "Số tuần lập lịch chi tiết",
        1,
        26,
        12,
        help="Các tuần sau được sinh tự động từ lộ trình, không tốn thêm lời gọi LLM.",
    )

    col_a, col_b = st.sidebar.columns(2)
    energy_start = col_a.text_input("Năng lượng từ", "20:00")
    energy_end = col_b.text_input("đến", "22:00")

    style_label = st.sidebar.selectbox(
        "Phong cách giao tiếp", list(STYLE_OPTIONS), index=0
    )
    strict_label = st.sidebar.selectbox(
        "Mức độ nghiêm khắc", list(STRICT_OPTIONS), index=0
    )
    notes = st.sidebar.text_input("Ràng buộc khác", "Không học được giờ hành chính")

    offline = st.sidebar.checkbox(
        "Dùng LLM giả (offline, không cần API key)",
        value=not has_api_key(),
        help="Bật để chạy thử toàn bộ luồng mà không tốn phí API.",
    )
    adapt = st.sidebar.checkbox(
        "Học từ kế hoạch đã lưu",
        value=False,
        help=(
            "Đọc lại các kế hoạch trong SQLite để suy ngẫm. Nếu bạn hay trượt "
            "việc, kế hoạch mới sẽ tự nhẹ hơn."
        ),
    )
    if not offline and not has_api_key():
        st.sidebar.warning("Chưa có `LLM_API_KEY` trong `.env`.")

    profile = UserProfile(
        name=name.strip() or "bạn",
        goal_summary=goal.strip(),
        current_skills=[s.strip() for s in skills_raw.split(",") if s.strip()],
        hours_per_week=hours,
        energy_windows=[
            EnergyWindow(label="Năng lượng cao", start=energy_start, end=energy_end)
        ],
        communication_style=STYLE_OPTIONS[style_label],
        strictness=STRICT_OPTIONS[strict_label],
        notes=notes,
    )

    settings = get_settings()
    if offline:
        st.sidebar.caption("Chế độ: LLM giả (tức thời, không gọi mạng)")
    else:
        st.sidebar.caption(
            f"Model: `{settings.llm_model}` · timeout {settings.llm_timeout:.0f}s "
            f"· thử lại {settings.llm_max_retries}"
        )
        st.sidebar.caption(
            "Model suy luận có thể mất 30-60s mỗi bước — cả luồng vài phút. "
            "Nếu quá chậm, đổi `LLM_MODEL` sang `deepseek-v4.1-flash`."
        )
    return profile, offline, weeks, adapt


def render_saved_plans() -> None:
    """Cho phép mở lại kế hoạch đã lưu, kèm `plan_id`.

    Không có bước này thì thẻ ôn tập tuy đã nằm trong SQLite nhưng **không có
    đường quay lại**: `plan_id` chỉ sống trong `session_state`, nên đóng trình
    duyệt là mất, và lần sau bấm "Lập kế hoạch" sẽ sinh một `plan_id` mới khiến
    thẻ cũ thành mồ côi.
    """
    st.sidebar.divider()
    st.sidebar.subheader("Kế hoạch đã lưu")
    try:
        summaries = persistence.list_plans(persistence.default_store(), limit=10)
    except Exception as exc:  # noqa: BLE001 - DB lỗi không chặn phần còn lại
        st.sidebar.caption(f"Không đọc được SQLite: {exc}")
        return

    if not summaries:
        st.sidebar.caption("Chưa có kế hoạch nào. Bấm **Lập kế hoạch** để tạo.")
        return

    labels = {
        f"#{s.id} · {s.goal_summary[:34]} · {s.progress_pct}%": s.id
        for s in summaries
    }
    choice = st.sidebar.selectbox("Mở lại", ["—"] + list(labels))
    if choice == "—":
        return
    if not st.sidebar.button("Tải kế hoạch này", use_container_width=True):
        return

    try:
        plan = persistence.load_plan(persistence.default_store(), labels[choice])
    except Exception as exc:  # noqa: BLE001 - hiển thị lỗi cho người dùng
        st.sidebar.error(f"Không đọc được kế hoạch: {exc}")
        return

    if plan is None:
        st.sidebar.error("Không tìm thấy kế hoạch này.")
        return

    st.session_state.plan = plan
    st.session_state.plan_id = labels[choice]
    st.sidebar.success("Đã tải kế hoạch. Thẻ ôn tập cũ được giữ nguyên.")


def llm_for(offline: bool):
    if offline:
        if "demo_llm" not in st.session_state:
            st.session_state.demo_llm = DemoLLM()
        return st.session_state.demo_llm
    return get_llm()


def render_gaps(plan) -> None:
    st.subheader("1. Khoảng trống kỹ năng — Chiến Lược Gia 🎯")
    if not plan.gaps:
        st.write("Không phát hiện khoảng trống rõ ràng.")
        return
    st.dataframe(
        [
            {
                "Ưu tiên": gap.priority,
                "Kỹ năng": gap.skill,
                "Vì sao cần": gap.rationale,
                "Nguồn học": ", ".join(gap.resources),
            }
            for gap in plan.gaps
        ],
        use_container_width=True,
        hide_index=True,
    )


def render_study_plan(plan) -> None:
    st.subheader("2. Lộ trình học — Giáo Viên 📚")
    if plan.study_plan is None:
        return
    st.caption(
        f"{plan.study_plan.total_weeks} tuần · "
        f"{len(plan.study_plan.modules)} module · {plan.study_plan.overview}"
    )
    st.dataframe(
        [
            {
                "Thứ tự": module.order + 1,
                "Module": module.title,
                "Giờ": module.duration_hours,
                "Kỹ năng": ", ".join(module.skills_covered),
            }
            for module in plan.study_plan.modules
        ],
        use_container_width=True,
        hide_index=True,
    )


def render_week(week) -> None:
    if week is None:
        return
    st.subheader(
        f"3. Lịch tuần {week.week} — Huấn Luyện Viên Kỷ Luật ⏰ "
        f"({week.total_hours} giờ)"
    )
    st.dataframe(
        [
            {
                "Ngày": task.day,
                "Bắt đầu": task.start,
                "Phút": task.duration_min,
                "Loại": TASK_LABEL.get(
                    getattr(task.task_type, "value", task.task_type), "Khác"
                ),
                "Việc": task.title,
            }
            for task in week.tasks
        ],
        use_container_width=True,
        hide_index=True,
    )


def render_roundtable(plan) -> None:
    st.subheader("4. Hội đồng persona — nhiều tính cách, một kết luận")
    if plan.roundtable is None:
        return
    for turn in plan.roundtable.turns:
        with st.chat_message(
            turn.persona, avatar=PERSONA_AVATAR.get(turn.persona, "🤖")
        ):
            st.markdown(f"**{turn.persona}** · _{turn.role}_")
            st.write(turn.content)
    if plan.roundtable.synthesis is not None:
        with st.chat_message("Người Dẫn Đường", avatar="🧭"):
            st.markdown("**Người Dẫn Đường** · _Tổng hợp ý kiến hội đồng_")
            st.write(plan.roundtable.synthesis.content)


def render_program(plan) -> None:
    st.divider()
    st.subheader("6. Lịch nhiều tuần — cả chương trình 🗓️")
    if not plan.weeks:
        st.info("Kế hoạch này chưa có lịch nhiều tuần.")
        return

    st.dataframe(
        [
            {
                "Tuần": week.week,
                "Số buổi": len(week.tasks),
                "Giờ": week.total_hours,
                "Module": ", ".join(
                    dict.fromkeys(
                        task.module_ref for task in week.tasks if task.module_ref
                    )
                )
                or "ôn tập",
            }
            for week in plan.weeks
        ],
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Xem chi tiết từng tuần"):
        for week in plan.weeks:
            st.markdown(f"**Tuần {week.week}** — {week.summary}")
            st.dataframe(
                [
                    {
                        "Ngày": task.day,
                        "Bắt đầu": task.start,
                        "Phút": task.duration_min,
                        "Việc": task.title,
                        "Trạng thái": task.status.value,
                    }
                    for task in week.tasks
                ],
                use_container_width=True,
                hide_index=True,
            )

    st.download_button(
        "⬇️ Tải lịch .ics (import vào Google Calendar / Outlook)",
        data=tasks_to_ics(plan.weeks, calendar_name="Life OS").encode("utf-8"),
        file_name="lifeos-lich.ics",
        mime="text/calendar",
        use_container_width=True,
    )


def render_progress(plan) -> None:
    st.divider()
    st.subheader("7. Tiến độ 📈")
    if not plan.weeks:
        st.info("Cần lịch nhiều tuần để theo dõi tiến độ.")
        return

    numbers = [week.week for week in plan.weeks]
    selected = st.selectbox("Tuần muốn cập nhật", numbers, index=0)
    week = next(w for w in plan.weeks if w.week == selected)

    done_ids: list[str] = []
    for task in week.tasks:
        label = (
            f"{task.day} {task.start} · {task.title} ({task.duration_min} phút)"
        )
        if st.checkbox(
            label, value=task.status == TaskStatus.DONE, key=f"done-{task.id}"
        ):
            done_ids.append(task.id)

    if st.button("Lưu tiến độ tuần này", use_container_width=True):
        for task in week.tasks:
            status = (
                TaskStatus.DONE if task.id in done_ids else TaskStatus.PLANNED
            )
            progress.mark_task(plan, task.id, status)
        st.session_state.plan = plan
        st.success(
            f"Đã ghi nhận {len(done_ids)}/{len(week.tasks)} buổi của tuần {selected}."
        )

    summary = progress.program_progress(plan)
    columns = st.columns(4)
    columns[0].metric("Hoàn thành", f"{summary.overall_pct}%")
    columns[1].metric("Giờ đã học", f"{summary.hours_done}/{summary.hours_planned}")
    columns[2].metric("Tuần hiện tại", summary.current_week)
    columns[3].metric("Chuỗi tuần xong", summary.streak)

    if summary.on_track:
        st.success(summary.note)
    else:
        st.warning(summary.note)

    upcoming = progress.next_tasks(plan, limit=3)
    if upcoming:
        st.caption(
            "Sắp tới: "
            + " · ".join(f"{t.day} {t.start} {t.title}" for t in upcoming)
        )


def _review_cards(plan, plan_id, today):
    """Đọc thẻ ôn tập đã lưu; chưa có thì sinh từ lộ trình rồi lưu lại.

    Trả về `(cards, store)`. `store` là `None` khi chưa có `plan_id` (kế hoạch
    chưa được lưu) — khi đó thẻ chỉ sống trong phiên làm việc như trước.
    """
    if plan_id is None:
        return srs.cards_from_plan(plan, today=today), None

    store = persistence.default_store()
    cards = persistence.load_review_cards(store, plan_id)
    if not cards:
        cards = srs.cards_from_plan(plan, today=today)
        if cards:
            persistence.save_review_cards(store, plan_id, cards)
    return cards, store


def render_review(plan, plan_id) -> None:
    st.divider()
    st.subheader("8. Ôn tập cách quãng — chống quên 🔁")
    today = date.today()

    try:
        cards, store = _review_cards(plan, plan_id, today)
    except Exception as exc:  # noqa: BLE001 - DB lỗi không chặn phần còn lại
        st.warning(f"Không đọc được thẻ ôn tập từ SQLite ({exc}). Dùng bản tạm.")
        cards, store = srs.cards_from_plan(plan, today=today), None

    if not cards:
        st.info("Lộ trình chưa có module nên chưa tạo được thẻ ôn tập.")
        return

    st.write(srs.summarize(cards, today=today))
    if store is not None:
        st.caption(
            f"Thẻ được lưu trong SQLite (kế hoạch #{plan_id}) — mở lại vẫn còn."
        )
    else:
        st.caption("Chưa lưu được kế hoạch nên thẻ chỉ tồn tại trong phiên này.")

    st.dataframe(
        [
            {
                "Chủ đề": card.topic,
                "Đến hạn": card.due_date.isoformat(),
                "Lần lặp": card.repetitions,
                "Khoảng cách (ngày)": card.interval_days,
                "Ease": round(card.ease, 2),
                "Số lần quên": card.lapses,
            }
            for card in cards
        ],
        use_container_width=True,
        hide_index=True,
    )

    due = srs.due_cards(cards, today=today)
    if not due:
        st.caption("Hôm nay không có thẻ nào đến hạn.")
        return

    st.markdown(f"**Thẻ đến hạn: {due[0].topic}**")
    quality = st.slider(
        "Bạn nhớ được bao nhiêu? (0 = quên hẳn, 5 = nhớ hoàn hảo)", 0, 5, 4
    )
    if st.button("Ghi nhận lượt ôn", use_container_width=True):
        if store is not None:
            card = persistence.review_and_save(
                store, plan_id, due[0].topic, quality, today=today
            )
        else:
            card = srs.review(due[0], quality, today=today)

        if card is None:
            st.error("Không tìm thấy thẻ này trong SQLite để cập nhật.")
        else:
            st.success(
                f"Lần ôn tới sau {card.interval_days} ngày "
                f"({card.due_date.isoformat()}), hệ số dễ {card.ease:.2f}."
            )


def render_quiz(plan, profile: UserProfile, offline: bool) -> None:
    st.divider()
    st.subheader("9. Kiểm tra hiểu biết 🎓")
    modules = plan.study_plan.modules if plan.study_plan else []
    topics = [module.title for module in modules] or ["Kiến thức chung"]
    topic = st.selectbox("Chủ đề", topics)
    count = st.slider("Số câu hỏi", 1, 5, 3)

    if st.button("Tạo bài kiểm tra", use_container_width=True):
        try:
            with st.spinner("Giáo Viên đang soạn câu hỏi..."):
                questions = tutor.quiz_set(
                    llm_for(offline),
                    topic,
                    build_tone_instruction(profile),
                    count=count,
                )
        except Exception as exc:  # noqa: BLE001 - hiển thị lỗi cho người dùng
            st.error(f"Không tạo được câu hỏi: {exc}")
            return
        if not questions:
            st.warning("Không nhận được câu hỏi nào.")
            return
        st.session_state.quiz = questions
        st.session_state.quiz_result = None

    questions = st.session_state.get("quiz")
    if not questions:
        st.caption("Bấm **Tạo bài kiểm tra** để bắt đầu.")
        return

    answers: list[int] = []
    for index, question in enumerate(questions, start=1):
        st.markdown(f"**Câu {index}.** {question.question}")
        choice = st.radio(
            "Chọn đáp án",
            options=list(range(len(question.options))),
            format_func=lambda i, q=question: f"{i}. {q.options[i]}",
            key=f"quiz-{index}-{question.question[:30]}",
            label_visibility="collapsed",
        )
        answers.append(choice)

    if st.button("Chấm điểm", type="primary", use_container_width=True):
        result = tutor.grade(answers, questions)
        st.session_state.quiz_result = result

    result = st.session_state.get("quiz_result")
    if result is None:
        return

    st.metric("Điểm", f"{result.correct}/{result.total}", f"{result.score_pct}%")
    for line in result.detail:
        st.write(line)
    if result.weak_topics:
        st.warning(
            "Cần ôn lại:\n\n"
            + "\n".join(f"- {weak}" for weak in tutor.follow_up_topics(result))
        )
    else:
        st.success("Trả lời đúng hết — có thể chuyển sang chủ đề tiếp theo.")


def render_team(goal: str) -> None:
    st.divider()
    st.subheader("10. Tự tổ chức nhóm — phân rã & thương lượng 🤝")
    st.caption(
        "Bộ điều phối phân rã mục tiêu thành nhiệm vụ, tự chọn thành viên theo "
        "kỹ năng cần có, rồi để các agent tự bỏ thầu (Contract Net Protocol). "
        "Không agent nào bị gán việc ngoài chuyên môn."
    )

    if st.button("Chạy tự tổ chức nhóm", use_container_width=True):
        st.session_state.team_plan = team.self_organize(goal)

    team_plan = st.session_state.get("team_plan")
    if team_plan is None:
        st.caption("Bấm nút để xem nhóm tự hình thành như thế nào.")
        return

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Nhiệm vụ sau khi phân rã**")
        st.dataframe(
            [
                {
                    "Ưu tiên": task.priority,
                    "Nhiệm vụ": task.id,
                    "Kỹ năng": task.skill,
                    "Công sức": task.effort,
                }
                for task in team_plan.breakdown.tasks
            ],
            use_container_width=True,
            hide_index=True,
        )
    with col_b:
        st.markdown("**Nhóm tự lập**")
        st.write(", ".join(team_plan.members) or "(không có ai)")
        if team_plan.excluded:
            st.caption(f"Không tham gia: {', '.join(team_plan.excluded)}")

    st.markdown("**Kết quả thương lượng**")
    st.dataframe(
        [
            {
                "Nhiệm vụ": result.task.id,
                "Người nhận": result.awarded_to or "—",
                "Số thầu": result.bid_count,
                "Từ chối": len(result.refusals),
                "Ghi chú": result.reason,
            }
            for result in team_plan.results
        ],
        use_container_width=True,
        hide_index=True,
    )

    if team_plan.fully_staffed:
        st.success(
            f"Đã giao đủ {team_plan.assigned_count}/{len(team_plan.results)} nhiệm vụ."
        )
    else:
        st.warning(
            f"Chưa giao được: {', '.join(team_plan.unassigned)}. "
            "Không agent nào đủ năng lực hoặc đúng chuyên môn."
        )

    with st.expander("Bản ghi giao thức ACL"):
        bus = MessageBus()
        net = ContractNet(bus)
        members, _ = team.build_roster(team_plan.breakdown)
        if members and team_plan.breakdown.tasks:
            net.run(team_plan.breakdown.tasks[0], members)
        for message in bus.messages:
            st.text(message.render())
        st.caption(f"{len(bus)} tin nhắn trong hội thoại.")


def render_reflection(plan) -> None:
    """Hiển thị kết quả suy ngẫm từ các kế hoạch trước (nếu có)."""
    reflection = plan.reflection
    if reflection is None:
        return
    st.divider()
    st.subheader("11. Suy ngẫm từ quá khứ 🔁")
    if reflection.stats.plans:
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Kế hoạch đã xem", reflection.stats.plans)
        col_b.metric(
            "Hoàn thành trung bình",
            f"{reflection.stats.avg_completion * 100:.0f}%",
        )
        col_c.metric("Hệ số tải đề xuất", reflection.stats.suggested_load_factor)
        st.write(reflection.stats.reason)
    if reflection.advice:
        st.info(reflection.advice)
    if not reflection.has_lessons and not reflection.stats.plans:
        st.caption("Chưa có dữ liệu quá khứ để học.")


def render_adjust(profile: UserProfile, offline: bool, plan) -> None:
    st.divider()
    st.subheader("5. Lệch kế hoạch? Hội đồng tự điều chỉnh")
    tasks = plan.first_week.tasks if plan.first_week else []
    if not tasks and plan.weeks:
        tasks = plan.weeks[0].tasks
    missed = st.multiselect(
        "Buổi bạn đã trượt", [task.title for task in tasks]
    )
    reason = st.text_input(
        "Lý do", "Deadline gấp ở công việc chính, phải làm thêm buổi tối"
    )
    if st.button("Điều chỉnh kế hoạch", use_container_width=True):
        try:
            with st.status("Hội đồng đang xem lại...", expanded=True) as status:
                new_plan = None
                event = None
                for node, update in iter_adjust(
                    plan, profile, reason, missed=missed, llm=llm_for(offline)
                ):
                    st.write(NODE_LABELS.get(node, node))
                    if "plan_out" in update:
                        new_plan = update["plan_out"]
                    if "event" in update:
                        event = update["event"]
                status.update(label="Đã điều chỉnh xong", state="complete")
            if new_plan is not None and event is not None:
                st.session_state.plan = new_plan
                st.session_state.event = event
            else:
                st.error("Không nhận được kết quả điều chỉnh.")
        except Exception as exc:  # noqa: BLE001 - hiển thị lỗi cho người dùng
            st.error(f"Lỗi khi điều chỉnh: {exc}")

    event = st.session_state.get("event")
    if event is not None:
        st.success(
            f"Đã điều chỉnh: tuần {event.old_week} → tuần {event.new_week}"
        )
        st.write(event.message)
        render_week(st.session_state.plan.first_week)


def main() -> None:
    profile, offline, weeks, adapt = render_sidebar()
    render_saved_plans()

    st.title("Life OS")
    st.caption(
        "Hội đồng agent đồng hành cùng một mục tiêu: nghề nghiệp → học tập → "
        "lịch tuần. Mỗi agent có tính cách riêng; giọng điệu thích nghi theo bạn."
    )

    questions = clarifying_questions(profile.goal_summary)
    if questions:
        st.warning(
            "Mục tiêu còn mơ hồ — nên làm rõ trước khi lập kế hoạch:\n\n"
            + "\n".join(f"- {question}" for question in questions)
        )
    else:
        st.success("Mục tiêu đã đủ rõ để lập kế hoạch.")

    if st.button("Lập kế hoạch", type="primary", use_container_width=True):
        try:
            # Đọc kế hoạch cũ để suy ngẫm: nếu người dùng hay trượt việc thì
            # kế hoạch mới sẽ nhẹ hơn. Bỏ qua nếu chưa có gì trong DB.
            past_plans: list = []
            if adapt:
                try:
                    past_plans = persistence.recent_plans(
                        persistence.default_store(), limit=5
                    )
                except Exception:  # noqa: BLE001 - DB lỗi không chặn lập kế hoạch
                    past_plans = []

            with st.status("Hội đồng đang làm việc...", expanded=True) as status:
                plan_result = None
                for node, update in iter_plan(
                    profile,
                    llm=llm_for(offline),
                    program_weeks=weeks,
                    past_plans=past_plans,
                ):
                    st.write(NODE_LABELS.get(node, node))
                    if "plan" in update:
                        plan_result = update["plan"]
                status.update(label="Đã lập xong kế hoạch", state="complete")
            if plan_result is not None:
                st.session_state.plan = plan_result
                # Lưu kế hoạch để có `plan_id` — thẻ ôn tập cần khoá này mới
                # ghi được xuống SQLite. Lỗi DB không được chặn lập kế hoạch.
                try:
                    st.session_state.plan_id = persistence.save_plan(
                        persistence.default_store(), plan_result
                    )
                except Exception:  # noqa: BLE001 - chỉ mất tính bền vững
                    st.session_state.plan_id = None
                if "event" in st.session_state:
                    del st.session_state["event"]
            else:
                st.error("Không nhận được kế hoạch từ đồ thị.")
        except Exception as exc:  # noqa: BLE001 - hiển thị lỗi cho người dùng
            st.error(f"Lỗi khi lập kế hoạch: {exc}")

    plan = st.session_state.get("plan")
    if plan is None:
        st.info("Nhập hồ sơ ở thanh bên rồi bấm **Lập kế hoạch**.")
        return

    render_gaps(plan)
    render_study_plan(plan)
    render_week(plan.first_week)
    render_program(plan)
    render_progress(plan)
    render_review(plan, st.session_state.get("plan_id"))
    render_quiz(plan, profile, offline)
    render_roundtable(plan)
    render_adjust(profile, offline, plan)
    render_team(profile.goal_summary)
    render_reflection(plan)


main()