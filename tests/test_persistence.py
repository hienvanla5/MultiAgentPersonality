"""Test lưu và khôi phục kế hoạch."""

from __future__ import annotations

from lifeos import persistence, progress
from lifeos.graph import create_plan
from lifeos.memory import Store
from lifeos.models import TaskStatus


def _store(tmp_path) -> Store:
    return Store(f"sqlite:///{tmp_path / 'plans.db'}")


def test_save_and_load_roundtrip(fake_llm, profile, tmp_path):
    store = _store(tmp_path)
    plan = create_plan(profile, llm=fake_llm)

    plan_id = persistence.save_plan(store, plan)
    assert plan_id > 0

    loaded = persistence.load_plan(store, plan_id)
    assert loaded is not None
    assert loaded.goal.description == plan.goal.description
    assert len(loaded.weeks) == len(plan.weeks)
    assert loaded.weeks[0].tasks[0].title == plan.weeks[0].tasks[0].title


def test_load_unknown_id_returns_none(tmp_path):
    assert persistence.load_plan(_store(tmp_path), 9999) is None


def test_progress_survives_roundtrip(fake_llm, profile, tmp_path):
    store = _store(tmp_path)
    plan = create_plan(profile, llm=fake_llm)

    task_id = plan.weeks[0].tasks[0].id
    progress.mark_task(plan, task_id, TaskStatus.DONE)
    plan_id = persistence.save_plan(store, plan)

    loaded = persistence.load_plan(store, plan_id)
    assert progress.find_task(loaded, task_id).status == TaskStatus.DONE
    assert progress.program_progress(loaded).overall_pct > 0


def test_update_plan_persists_progress(fake_llm, profile, tmp_path):
    store = _store(tmp_path)
    plan = create_plan(profile, llm=fake_llm)
    plan_id = persistence.save_plan(store, plan)

    task_id = plan.weeks[0].tasks[0].id
    progress.mark_task(plan, task_id, TaskStatus.DONE)
    assert persistence.update_plan(store, plan_id, plan) is True

    reloaded = persistence.load_plan(store, plan_id)
    assert progress.find_task(reloaded, task_id).status == TaskStatus.DONE


def test_update_unknown_plan_returns_false(fake_llm, profile, tmp_path):
    store = _store(tmp_path)
    plan = create_plan(profile, llm=fake_llm)
    assert persistence.update_plan(store, 4242, plan) is False


def test_list_plans_newest_first_with_progress(fake_llm, profile, tmp_path):
    store = _store(tmp_path)
    first = create_plan(profile, llm=fake_llm)
    persistence.save_plan(store, first)

    second = create_plan(profile, llm=fake_llm)
    progress.mark_week(second, 1, TaskStatus.DONE)
    persistence.save_plan(store, second)

    summaries = persistence.list_plans(store)
    assert [s.id for s in summaries] == sorted(
        [s.id for s in summaries], reverse=True
    )
    assert len(summaries) == 2
    assert summaries[0].weeks == len(second.weeks)
    assert summaries[0].progress_pct > 0
    assert summaries[1].progress_pct == 0


def test_list_plans_respects_limit(fake_llm, profile, tmp_path):
    store = _store(tmp_path)
    for _ in range(3):
        persistence.save_plan(store, create_plan(profile, llm=fake_llm))
    assert len(persistence.list_plans(store, limit=2)) == 2


def test_list_plans_empty_store(tmp_path):
    assert persistence.list_plans(_store(tmp_path)) == []


def test_list_plans_skips_corrupt_record(tmp_path):
    store = _store(tmp_path)
    store.save_plan("hỏng", {"khong": "hop le"}, "2026-01-01T00:00:00")
    summaries = persistence.list_plans(store)
    assert len(summaries) == 1
    assert summaries[0].weeks == 0
    assert summaries[0].progress_pct == 0