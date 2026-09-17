from app.store.resume import FAILED, PROCESSING, READY, ResumeStore


def _store(tmp_path):
    return ResumeStore(tmp_path / "resume.db")


def test_add_and_get(tmp_path):
    store = _store(tmp_path)
    r = store.add_resume("r-1", "zhangsan.pdf", "data/resumes/zhangsan.pdf", 1024)
    assert r.id == "r-1"
    assert r.status == PROCESSING
    got = store.get_resume("r-1")
    assert got is not None
    assert got.file_name == "zhangsan.pdf"


def test_update_ready_with_points_and_count(tmp_path):
    store = _store(tmp_path)
    store.add_resume("r-1", "a.md", "data/resumes/a.md", 10)
    store.update_ready(
        "r-1",
        '{"basic": {"name": "张三"}, "skills": [], "projects": []}',
        [
            {"category": "项目", "title": "缓存设计", "detail": "说明", "source_snippet": "原文"},
            {"category": "技能", "title": "Redis", "detail": "说明", "source_snippet": "原文"},
        ],
    )
    got = store.get_resume("r-1")
    assert got.status == READY
    assert got.point_count == 2
    assert '"name": "张三"' in got.profile_json
    points = store.list_points("r-1")
    assert len(points) == 2
    assert points[0].category == "项目"
    assert store.count_points("r-1") == 2


def test_update_failed(tmp_path):
    store = _store(tmp_path)
    store.add_resume("r-1", "a.pdf", "data/resumes/a.pdf", 10)
    store.update_failed("r-1", "PDF 无文字层")
    got = store.get_resume("r-1")
    assert got.status == FAILED
    assert "无文字层" in got.error


def test_delete_resume_cascades_points(tmp_path):
    store = _store(tmp_path)
    store.add_resume("r-1", "a.md", "data/resumes/a.md", 10)
    store.update_ready(
        "r-1", "{}", [{"category": "技能", "title": "T", "detail": "D", "source_snippet": "S"}]
    )
    path = store.delete_resume("r-1")
    assert path == "data/resumes/a.md"
    assert store.get_resume("r-1") is None
    assert store.list_points("r-1") == []
    assert store.count_points("r-1") == 0


def test_list_sorted_by_created_desc(tmp_path):
    store = _store(tmp_path)
    store.add_resume("r-1", "a.md", "data/resumes/a.md", 10)
    store.add_resume("r-2", "b.md", "data/resumes/b.md", 10)
    ids = [r.id for r in store.list_resumes()]
    assert ids == ["r-2", "r-1"]
