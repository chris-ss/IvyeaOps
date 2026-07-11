"""Listing 通用后台任务引擎：持久化、失败路径、singleton 去重、SSE 事件流。"""
import asyncio
import json
import time

from app.routers.listing import jobs as J
from app.routers.listing.common import _db


def _cleanup(project_id: str) -> None:
    conn = _db()
    conn.execute("DELETE FROM listing_jobs WHERE project_id = ?", (project_id,))
    conn.commit()
    conn.close()


async def _wait_done(job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = J.get_job(job_id)
        if job and job["status"] in ("done", "failed"):
            return job
        await asyncio.sleep(0.02)
    raise AssertionError("job did not finish in time")


def test_job_success_persists_result_and_progress():
    pid = "jobtest_ok"
    _cleanup(pid)

    async def scenario():
        async def runner(handle):
            handle.update(stage="s1", message="working", progress=0.5)
            return {"answer": 42}

        job = J.start_job("scrape", pid, {"a": 1}, runner)
        assert job["status"] == "running"
        done = await _wait_done(job["id"])
        assert done["status"] == "done"
        assert done["result"] == {"answer": 42}
        assert done["progress"] == 1.0
        assert done["params"] == {"a": 1}

    asyncio.run(scenario())
    _cleanup(pid)


def test_job_failure_records_error():
    pid = "jobtest_fail"
    _cleanup(pid)

    async def scenario():
        async def runner(handle):
            raise RuntimeError("boom boom")

        job = J.start_job("analyze", pid, {}, runner)
        done = await _wait_done(job["id"])
        assert done["status"] == "failed"
        assert "boom boom" in done["error"]

    asyncio.run(scenario())
    _cleanup(pid)


def test_singleton_returns_running_job_instead_of_duplicating():
    pid = "jobtest_singleton"
    _cleanup(pid)

    async def scenario():
        release = asyncio.Event()

        async def runner(handle):
            await release.wait()
            return {}

        first = J.start_job("copy", pid, {}, runner)
        second = J.start_job("copy", pid, {}, runner)
        assert second["id"] == first["id"]  # 同项目同类型不重复起
        release.set()
        await _wait_done(first["id"])
        # 结束后允许再起新任务
        release2 = asyncio.Event()

        async def runner2(handle):
            release2.set()
            return {}

        third = J.start_job("copy", pid, {}, runner2)
        assert third["id"] != first["id"]
        await _wait_done(third["id"])

    asyncio.run(scenario())
    _cleanup(pid)


def test_startup_cleanup_fails_orphan_running_jobs():
    pid = "jobtest_orphan"
    _cleanup(pid)
    conn = _db()
    now = time.time()
    conn.execute(
        "INSERT INTO listing_jobs (id, project_id, kind, status, params, created_at, updated_at) "
        "VALUES ('orphan1', ?, 'plan', 'running', '{}', ?, ?)", (pid, now, now),
    )
    conn.commit()
    conn.close()
    J._startup_cleanup()
    job = J.get_job("orphan1")
    assert job["status"] == "failed"
    assert "重启" in job["error"]
    _cleanup(pid)


def test_sse_stream_emits_progress_then_end():
    pid = "jobtest_sse"
    _cleanup(pid)

    async def scenario():
        gate = asyncio.Event()

        async def runner(handle):
            await gate.wait()
            handle.update(stage="mid", message="halfway", progress=0.5)
            return {"ok": True}

        job = J.start_job("render_set", pid, {}, runner)
        response = await J.job_events(job["id"], _user="t")
        chunks: list[str] = []

        async def consume():
            async for chunk in response.body_iterator:
                chunks.append(chunk if isinstance(chunk, str) else chunk.decode())

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        gate.set()
        await asyncio.wait_for(consumer, timeout=5)
        payloads = [json.loads(c[len("data: "):]) for c in chunks if c.startswith("data: ")]
        assert payloads[0]["status"] == "running"        # 初始状态先行推送
        assert any(p.get("stage") == "mid" for p in payloads)
        assert payloads[-1]["status"] == "done"          # 终态后流关闭

    asyncio.run(scenario())
    _cleanup(pid)
