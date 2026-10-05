"""Giao diện Streamlit cho Life OS.

Chạy: uv run streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from lifeos.clarify import clarifying_questions
from lifeos.demo import DemoLLM
from lifeos.graph import adjust_plan, create_plan
from lifeos.llm import get_llm, has_api_key
from lifeos.models import (
    CommunicationStyle,
    EnergyWindow,
    StrictnessLevel,
    UserProfile,
)

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


def render_sidebar() -> tuple[UserProfile, bool]:
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
    return profile, offline


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


def render_adjust(profile: UserProfile, offline: bool, plan) -> None:
    st.divider()
    st.subheader("5. Lệch kế hoạch? Hội đồng tự điều chỉnh")
    tasks = plan.first_week.tasks if plan.first_week else []
    missed = st.multiselect(
        "Buổi bạn đã trượt", [task.title for task in tasks]
    )
    reason = st.text_input(
        "Lý do", "Deadline gấp ở công việc chính, phải làm thêm buổi tối"
    )
    if st.button("Điều chỉnh kế hoạch", use_container_width=True):
        with st.spinner("Hội đồng đang xem lại..."):
            try:
                new_plan, event = adjust_plan(
                    plan, profile, reason, missed=missed, llm=llm_for(offline)
                )
                st.session_state.plan = new_plan
                st.session_state.event = event
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
    profile, offline = render_sidebar()

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
        with st.spinner("Chiến Lược Gia, Giáo Viên và Huấn Luyện Viên đang làm việc..."):
            try:
                st.session_state.plan = create_plan(profile, llm=llm_for(offline))
                if "event" in st.session_state:
                    del st.session_state["event"]
            except Exception as exc:  # noqa: BLE001 - hiển thị lỗi cho người dùng
                st.error(f"Lỗi khi lập kế hoạch: {exc}")

    plan = st.session_state.get("plan")
    if plan is None:
        st.info("Nhập hồ sơ ở thanh bên rồi bấm **Lập kế hoạch**.")
        return

    render_gaps(plan)
    render_study_plan(plan)
    render_week(plan.first_week)
    render_roundtable(plan)
    render_adjust(profile, offline, plan)


main()