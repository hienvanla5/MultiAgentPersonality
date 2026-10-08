"""LLM giả để demo offline (không cần API key).

Trả về nội dung mẫu, tất định, cho kịch bản "chuyển sang Data Analyst".
Dùng để chạy thử toàn bộ pipeline và để viết test tích hợp.
"""

from __future__ import annotations

from typing import TypeVar, cast

from pydantic import BaseModel

from .agents.schemas import (
    Critique,
    DecomposedTask,
    GapList,
    Quiz,
    QuizSet,
    Synthesis,
    TaskBreakdown,
)
from .models import (
    ScheduleTask,
    SkillGap,
    StudyModule,
    StudyPlan,
    TaskType,
    WeeklySchedule,
)

_REDUCE_MARKER = "GIẢM TẢI"

TModel = TypeVar("TModel", bound=BaseModel)


class DemoLLM:
    """Hiện thực giao diện LLM bằng dữ liệu mẫu, không gọi mạng."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    # --- giao diện LLM ---

    def structured(
        self, system_prompt: str, user_prompt: str, schema: type[TModel]
    ) -> TModel:
        self.calls.append(schema.__name__)
        handler = {
            "GapList": self._gaps,
            "StudyPlan": self._study_plan,
            "WeeklySchedule": self._week,
            "Critique": self._critique,
            "Synthesis": self._synthesis,
            "Quiz": self._quiz,
            "QuizSet": self._quiz_set,
            "TaskBreakdown": self._task_breakdown,
        }.get(schema.__name__)
        if handler is None:
            raise NotImplementedError(f"DemoLLM chưa hỗ trợ schema: {schema.__name__}")
        # Tra theo tên schema lúc chạy nên không có cách nào để trình kiểm tra
        # kiểu suy ra `TModel`; `cast` nói thẳng điều đó thay vì để `Any` lọt qua.
        return cast(TModel, handler(user_prompt))

    def text(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append("text")
        return (
            "Bạn đang đi đúng hướng — việc vừa đi làm vừa chuyển ngành là khó, "
            "và bạn đã bắt đầu được một tuần rồi. Đừng cố bù hết trong một tối; "
            "chỉ cần giữ đúng 3 buổi tối tuần này là bạn đã thắng. "
            "Tiến độ nhỏ nhưng đều sẽ thắng tiến độ lớn nhưng đứt đoạn."
        )

    # --- nội dung mẫu ---

    def _gaps(self, _prompt: str) -> GapList:
        return GapList(
            gaps=[
                SkillGap(
                    skill="SQL",
                    priority=1,
                    rationale=(
                        "Hầu hết JD Data Analyst yêu cầu JOIN, GROUP BY và "
                        "window function ở mức thành thạo."
                    ),
                    resources=["SQLBolt", "Mode Analytics SQL Tutorial"],
                ),
                SkillGap(
                    skill="Python & pandas",
                    priority=1,
                    rationale=(
                        "Là công cụ làm sạch và biến đổi dữ liệu phổ biến nhất "
                        "trong phỏng vấn kỹ thuật."
                    ),
                    resources=["pandas documentation", "Kaggle Learn Pandas"],
                ),
                SkillGap(
                    skill="Thống kê ứng dụng",
                    priority=2,
                    rationale=(
                        "Cần để đọc kết quả A/B test và tránh kết luận sai "
                        "từ dữ liệu nhiễu."
                    ),
                    resources=["Khan Academy Statistics", "Think Stats"],
                ),
                SkillGap(
                    skill="Trực quan hoá dữ liệu",
                    priority=2,
                    rationale=(
                        "Nhà tuyển dụng đánh giá cao khả năng biến số liệu "
                        "thành biểu đồ dễ hiểu."
                    ),
                    resources=["Storytelling with Data"],
                ),
                SkillGap(
                    skill="Kể chuyện với dữ liệu",
                    priority=3,
                    rationale=(
                        "Phân biệt ứng viên được chọn: giải thích insight cho "
                        "người không chuyên."
                    ),
                    resources=["Storytelling with Data", "Viết portfolio case study"],
                ),
            ]
        )

    def _study_plan(self, _prompt: str) -> StudyPlan:
        return StudyPlan(
            modules=[
                StudyModule(
                    title="SQL nền tảng",
                    duration_hours=20,
                    order=0,
                    depends_on=[],
                    skills_covered=["SQL"],
                ),
                StudyModule(
                    title="Python & pandas cho phân tích dữ liệu",
                    duration_hours=25,
                    order=1,
                    depends_on=[0],
                    skills_covered=["Python & pandas"],
                ),
                StudyModule(
                    title="Thống kê ứng dụng",
                    duration_hours=18,
                    order=2,
                    depends_on=[1],
                    skills_covered=["Thống kê ứng dụng"],
                ),
                StudyModule(
                    title="Trực quan hoá & kể chuyện với dữ liệu",
                    duration_hours=12,
                    order=3,
                    depends_on=[2],
                    skills_covered=["Trực quan hoá dữ liệu", "Kể chuyện với dữ liệu"],
                ),
                StudyModule(
                    title="Dự án portfolio trên bộ dữ liệu thật",
                    duration_hours=30,
                    order=4,
                    depends_on=[1, 3],
                    skills_covered=["Python & pandas", "Kể chuyện với dữ liệu"],
                ),
            ],
            total_weeks=24,
            overview=(
                "6 tháng, ưu tiên SQL và pandas trước vì đây là hai kỹ năng "
                "xuất hiện nhiều nhất trong JD; thống kê và trực quan hoá học "
                "song song ở giai đoạn giữa; tháng cuối dồn cho dự án portfolio."
            ),
        )

    def _week(self, _prompt: str) -> WeeklySchedule:
        return WeeklySchedule(
            week=1,
            tasks=[
                ScheduleTask(
                    title="Học SQL: SELECT, WHERE, JOIN",
                    task_type=TaskType.STUDY,
                    day="Mon",
                    start="20:00",
                    duration_min=60,
                    module_ref="SQL nền tảng",
                ),
                ScheduleTask(
                    title="Luyện SQL trên SQLBolt (bài 1-6)",
                    task_type=TaskType.STUDY,
                    day="Tue",
                    start="20:00",
                    duration_min=60,
                    module_ref="SQL nền tảng",
                ),
                ScheduleTask(
                    title="Cài Python + pandas, đọc CSV đầu tiên",
                    task_type=TaskType.STUDY,
                    day="Wed",
                    start="20:00",
                    duration_min=60,
                    module_ref="Python & pandas cho phân tích dữ liệu",
                ),
                ScheduleTask(
                    title="Ôn tập SQL cách quãng",
                    task_type=TaskType.REVIEW,
                    day="Sat",
                    start="09:00",
                    duration_min=90,
                    module_ref="SQL nền tảng",
                ),
            ],
            summary="",
        )

    def _critique(self, prompt: str) -> Critique:
        if _REDUCE_MARKER in prompt:
            return Critique(
                risks=[
                    "Bạn vẫn đi làm full-time nên tuần nào có việc gấp là dễ đứt nhịp.",
                ],
                overload=False,
                suggestions=[
                    "Giữ nhịp 3 buổi/tuần trong tháng đầu, đừng tăng sớm.",
                    "Đặt buổi ôn tập cố định vào sáng thứ Bảy.",
                ],
                summary=(
                    "Sau khi giảm tải, kế hoạch nằm trong quỹ thời gian và "
                    "khả thi để duy trì."
                ),
            )
        return Critique(
            risks=[
                "Tuần đầu hơi dày so với người vẫn đi làm full-time.",
                "Chưa có buổi ôn tập cách quãng nên kiến thức SQL dễ rơi rụng.",
            ],
            overload=True,
            suggestions=[
                "Giảm khoảng 20% khối lượng trong 2 tuần đầu.",
                "Thêm một buổi ôn tập ngắn vào cuối tuần.",
            ],
            summary=(
                "Kế hoạch đúng hướng nhưng tuần đầu quá dày; nên giảm tải "
                "khoảng 20% trước khi tăng tốc."
            ),
        )

    def _synthesis(self, prompt: str) -> Synthesis:
        if "Điều chỉnh kế hoạch" in prompt:
            return self._adjust_synthesis()
        return Synthesis(
            headline=(
                "Lộ trình 6 tháng sang Data Analyst là khả thi nếu giữ nhịp "
                "đều và không nhồi tuần đầu."
            ),
            key_points=[
                "Ưu tiên SQL và pandas — hai kỹ năng xuất hiện nhiều nhất trong JD.",
                "Giảm tải 20% trong 2 tuần đầu để tạo đà thay vì đứt đoạn.",
                "Tháng cuối dồn cho dự án portfolio vì đó là thứ nhà tuyển dụng xem.",
            ],
            next_actions=[
                "Tối thứ Hai: học SQL SELECT/WHERE/JOIN (60 phút).",
                "Tối thứ Ba: luyện SQLBolt bài 1-6 (60 phút).",
                "Tối thứ Tư: cài Python + pandas, đọc một file CSV (60 phút).",
                "Sáng thứ Bảy: ôn tập cách quãng SQL (90 phút).",
            ],
            message=(
                "Hội đồng thống nhất: hướng đi hợp lý, nhưng tuần đầu cần nhẹ "
                "hơn để bạn không bỏ giữa chừng. Bắt đầu với SQL và pandas — "
                "đây là hai kỹ năng được hỏi nhiều nhất khi phỏng vấn. "
                "Hãy coi 4 buổi dưới đây là cam kết tối thiểu, không phải mục tiêu "
                "tối đa. Hết tháng đầu, chúng ta sẽ xem lại và tăng tốc nếu bạn "
                "thấy ổn."
            ),
        )

    def _adjust_synthesis(self) -> Synthesis:
        return Synthesis(
            headline=(
                "Đã điều chỉnh: tuần này nhẹ hơn để bạn lấy lại nhịp thay vì "
                "cố bù hết."
            ),
            key_points=[
                "Trượt 2 buổi khi có deadline gấp ở công việc là chuyện bình thường.",
                "Không dồn bù vào một tuần — rất dễ dẫn tới bỏ hẳn.",
                "Giữ nguyên thứ tự module, chỉ giãn tiến độ ra một tuần.",
            ],
            next_actions=[
                "Tuần này chỉ cần 3 buổi tối, mỗi buổi 60 phút.",
                "Dành sáng thứ Bảy để ôn lại phần SQL đã trượt.",
                "Chủ nhật: xem lại lịch tuần sau và tự chốt 3 buổi.",
            ],
            message=(
                "Không sao cả — bạn đang đi làm full-time, việc trượt 2 buổi "
                "khi có deadline gấp là hoàn toàn bình thường. Điều quan trọng "
                "là không cố bù hết trong một tuần, vì cách đó thường dẫn tới "
                "bỏ luôn. Hội đồng đã giãn tiến độ ra một tuần và giảm nhẹ khối "
                "lượng: tuần này bạn chỉ cần 3 buổi tối. Thứ tự học không đổi, "
                "nên bạn không mất gì cả."
            ),
        )

    def _task_breakdown(self, prompt: str) -> TaskBreakdown:
        """Phân rã mẫu cho kịch bản "chuyển sang Data Analyst".

        Cố ý **khác** quy tắc cố định trong `team._rule_tasks`: chỉ có 4 nhiệm
        vụ và không có nhiệm vụ `risk-review`, nên agent `critic` không được
        mời. Nhờ vậy nhìn vào demo là thấy ngay đường LLM có thật sự chạy hay
        không, và thấy nhóm co giãn theo mục tiêu.
        """
        return TaskBreakdown(
            tasks=[
                DecomposedTask(
                    id="doc-jd",
                    description=(
                        "Đọc 10 tin tuyển Data Analyst để chốt kỹ năng nào "
                        "thật sự được hỏi nhiều"
                    ),
                    skill="gap-analysis",
                    priority=1,
                    effort=0.3,
                ),
                DecomposedTask(
                    id="lo-trinh",
                    description="Xếp thứ tự học SQL, thống kê, rồi pandas",
                    skill="curriculum",
                    priority=1,
                    effort=0.4,
                ),
                DecomposedTask(
                    id="lich-tuan",
                    description="Chia lộ trình thành các buổi tối 90 phút",
                    skill="scheduling",
                    priority=2,
                    effort=0.4,
                ),
                DecomposedTask(
                    id="giu-dong-luc",
                    description="Viết lời nhắc cho những tuần dễ bỏ nhất",
                    skill="motivation",
                    priority=3,
                    effort=0.1,
                ),
            ]
        )

    def _quiz_set(self, _prompt: str) -> QuizSet:
        base = self._quiz("")
        extras = [
            Quiz(
                question=(
                    "Muốn đếm số đơn hàng theo từng tháng trong bảng 'orders' "
                    "(cột order_date), bạn dùng cách nào?"
                ),
                options=[
                    "GROUP BY tháng của order_date",
                    "ORDER BY order_date",
                    "WHERE order_date = tháng",
                    "SELECT DISTINCT order_date",
                ],
                answer_index=0,
                explanation=(
                    "Cần gom nhóm theo tháng rồi đếm, nên phải GROUP BY biểu thức "
                    "tháng của order_date kèm COUNT(*)."
                ),
            ),
            Quiz(
                question=(
                    "Bảng 'orders' có nhiều dòng trùng customer_id. Muốn mỗi khách "
                    "chỉ hiện một lần, bạn làm gì?"
                ),
                options=[
                    "SELECT DISTINCT customer_id",
                    "SELECT COUNT(customer_id)",
                    "DELETE các dòng trùng",
                    "Thêm WHERE customer_id IS NOT NULL",
                ],
                answer_index=0,
                explanation=(
                    "DISTINCT loại bỏ giá trị trùng khi truy vấn, không cần sửa "
                    "dữ liệu gốc."
                ),
            ),
        ]
        return QuizSet(questions=[base, *extras])

    def _quiz(self, _prompt: str) -> Quiz:
        return Quiz(
            question=(
                "Bạn cần ghép bảng 'orders' với bảng 'customers' theo customer_id "
                "để lấy tên khách hàng cho mọi đơn. Dùng phép JOIN nào?"
            ),
            options=["INNER JOIN", "LEFT JOIN", "CROSS JOIN", "UNION"],
            answer_index=1,
            explanation=(
                "LEFT JOIN giữ lại mọi đơn hàng kể cả khi không tìm thấy khách "
                "hàng tương ứng, nên không làm mất dữ liệu đơn."
            ),
        )
