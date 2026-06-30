"""Listing Generator — proxy to imgflow backend + AI copywriting + skill-enhanced analysis."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import mimetypes
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import settings
from app.core.security import require_user
from app.services.skill_repo import get_skill

router = APIRouter()

DB_PATH = settings.data_dir / "listing.sqlite3"
IMAGES_DIR = settings.data_dir / "listing_images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

def _imgflow_base() -> str:
    from app.core import hub_settings
    url = hub_settings.get("imgflow_url") or "http://127.0.0.1:3001"
    return str(url).rstrip("/") + "/api"


_COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")


def _imgflow_dir() -> Optional[Path]:
    """Locate the amazon-image-workflow project dir (the Docker 采集服务). Honours
    the optional `imgflow_dir` setting, else looks for it next to / under the
    IvyeaOps install root. Returns None when not found."""
    from app.core import hub_settings
    candidates: list[Path] = []
    configured = hub_settings.get("imgflow_dir")
    if configured:
        candidates.append(Path(str(configured)))
    # runtime_root() resolves to the exe's dir when frozen (Windows x64) and the
    # repo root from source — using __file__.parents[3] would point inside the
    # PyInstaller _MEIPASS temp dir for the exe and never find the shipped folder.
    from app.core.version import runtime_root
    root = runtime_root()
    candidates += [root / "amazon-image-workflow", root.parent / "amazon-image-workflow",
                   Path(__file__).resolve().parents[3] / "amazon-image-workflow"]
    for d in candidates:
        try:
            if d.is_dir() and any((d / f).exists() for f in _COMPOSE_FILES):
                return d
        except Exception:
            continue
    return None


_DOCKER_DL = "https://www.docker.com/products/docker-desktop/"


def _docker_bin() -> Optional[str]:
    """Find the docker CLI. shutil.which covers the normal case; we also probe
    Docker Desktop's standard install path so a Docker that was installed *after*
    IvyeaOps started (PATH not refreshed in our process) is still found without
    forcing a restart."""
    import shutil
    found = shutil.which("docker")
    if found:
        return found
    for p in (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe",
        Path(os.environ.get("ProgramW6432", r"C:\Program Files")) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe",
    ):
        try:
            if p.is_file():
                return str(p)
        except Exception:
            continue
    return None


def _docker_running(docker: str) -> bool:
    """True when the Docker daemon is up (`docker info` succeeds). Docker Desktop
    can be installed but not started — compose would then fail with a daemon
    error, so we check first to give a clear 'start Docker Desktop' message."""
    import subprocess
    from app.core.proc import no_window_kwargs
    try:
        r = subprocess.run([docker, "info"], capture_output=True, text=True,
                           timeout=12, **no_window_kwargs())
        return r.returncode == 0
    except Exception:
        return False


@router.get("/imgflow/status")
async def imgflow_status(_u: str = Depends(require_user)):
    """Report whether the 采集服务 is reachable, its dir is found, and Docker is
    installed + running — drives the 'start collection service' button in the UI."""
    d = _imgflow_dir()
    reachable = False
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            r = await client.get(_imgflow_base())
            reachable = r.status_code < 500
    except Exception:
        reachable = False
    docker = _docker_bin()
    return {
        "reachable": reachable,
        "dir": str(d) if d else "",
        "docker_installed": bool(docker),
        "docker_running": bool(docker) and _docker_running(docker),
    }


@router.post("/imgflow/start")
def imgflow_start(_u: str = Depends(require_user)):
    """One-click start of the local Docker 采集服务. Only brings up the `backend`
    service (+ its postgres dependency) — the listing board talks to :3001 and
    doesn't need the workflow's own Next.js frontend, so we skip that build.
    Runs detached, logging to data/imgflow-start.log (the --build can take
    minutes, so we never block)."""
    import subprocess
    from app.core.proc import no_window_kwargs

    d = _imgflow_dir()
    if not d:
        raise HTTPException(400, "未找到 amazon-image-workflow 目录。请把该项目放在 IvyeaOps "
                                 "同级目录，或在「系统配置」设置 imgflow_dir 指向它，再试。")
    docker = _docker_bin()
    if not docker:
        raise HTTPException(400, f"未检测到 Docker。这个「完整主图组」采集服务是一套 Docker 应用，"
                                 f"请先安装 Docker Desktop（{_DOCKER_DL}）。装完启动它（等托盘鲸鱼图标变绿），"
                                 f"若仍提示未检测到，重启一次 IvyeaOps 让其识别 Docker，再点此按钮。")
    if not _docker_running(docker):
        raise HTTPException(400, "检测到 Docker 已安装，但 Docker 引擎未运行。请先启动 Docker Desktop，"
                                 "等托盘鲸鱼图标变绿（不再转圈）后再点此按钮。")

    log_path = settings.data_dir / "imgflow-start.log"
    try:
        logf = open(log_path, "ab")
        kw = dict(no_window_kwargs())
        if os.name == "nt":  # detach on Windows so stopping the app won't kill the build
            kw["creationflags"] = kw.get("creationflags", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        else:
            kw["start_new_session"] = True
        # `backend` pulls in its depends_on (postgres) automatically; skipping the
        # frontend service makes the first build much faster.
        subprocess.Popen([docker, "compose", "up", "-d", "--build", "backend"],
                         cwd=str(d), stdout=logf, stderr=subprocess.STDOUT, **kw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"启动采集服务失败：{exc}") from exc
    return {
        "ok": True,
        "dir": str(d),
        "log": str(log_path),
        "detail": "采集服务正在后台启动（docker compose up -d --build backend），首次构建可能需要几分钟"
                  "（拉取 postgres 镜像 + 构建后端）。完成后重新「采集ASIN数据」即可拿到完整主图组。",
    }


# ─── Native Amazon scrape (no Docker) ──────────────────────────────────────────
# The full main-image set lives in the product page's inline JSON as "hiRes"
# entries. Fetch the page with curl — its TLS fingerprint passes Amazon's anti-bot
# where httpx/undici is blocked, and curl ships with Windows 10/11 + every Linux.
# This makes the full image set work WITHOUT the amazon-image-workflow Docker
# stack; that service is now just an optional fallback for when curl is blocked.

_REAL_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_MKT_DOMAIN = {
    "US": "amazon.com", "UK": "amazon.co.uk", "DE": "amazon.de", "JP": "amazon.co.jp",
    "FR": "amazon.fr", "IT": "amazon.it", "ES": "amazon.es", "CA": "amazon.ca",
    "AU": "amazon.com.au", "MX": "amazon.com.mx", "IN": "amazon.in", "NL": "amazon.nl",
    "SE": "amazon.se", "PL": "amazon.pl", "AE": "amazon.ae", "SG": "amazon.sg",
}


def _amazon_domain(marketplace: str) -> str:
    return _MKT_DOMAIN.get((marketplace or "US").upper(), "amazon.com")


def _parse_amazon_html(html_text: str) -> dict:
    """Extract title / bullets / full main-image set from raw Amazon product HTML.
    Images come from the inline "hiRes" (then "large") JSON, not the DOM thumbnails
    (which are injected by JS post-load and absent from static HTML)."""
    import html as _html
    images: list[str] = []
    seen: set[str] = set()
    for pat in (r'"hiRes"\s*:\s*"(https?://[^"\\]+)"', r'"large"\s*:\s*"(https?://[^"\\]+)"'):
        if images:
            break
        for m in re.finditer(pat, html_text):
            u = m.group(1)
            if u not in seen:
                seen.add(u)
                images.append(u)
            if len(images) >= 7:
                break
    if not images:
        m = re.search(r'id="landingImage"[^>]*data-old-hires="(https?://[^"]+)"', html_text) \
            or re.search(r'id="landingImage"[^>]*src="(https?://[^"]+)"', html_text)
        if m:
            images.append(m.group(1))

    tm = re.search(r'id="productTitle"[^>]*>(.*?)</', html_text, re.S)
    title = _html.unescape(re.sub(r"\s+", " ", tm.group(1)).strip()) if tm else ""

    bullets: list[str] = []
    fb = re.search(r'id="feature-bullets"(.*?)</ul>', html_text, re.S)
    if fb:
        for bm in re.finditer(r'class="a-list-item[^"]*"[^>]*>(.*?)</span>', fb.group(1), re.S):
            t = _html.unescape(re.sub(r"<[^>]+>", "", bm.group(1)))
            t = re.sub(r"\s+", " ", t).strip()
            if t and t not in bullets:
                bullets.append(t)

    return {"title": title, "bullets": bullets[:5], "description": "", "imageUrls": images}


async def _scrape_amazon_native(asin: str, marketplace: str, attempts: int = 5) -> Optional[dict]:
    """Fetch the Amazon product page via curl and parse the full main-image set.
    Returns None when curl is unavailable or EVERY attempt hits an anti-bot
    challenge / captcha / image-less page — callers then fall back to sorftime.

    Amazon's anti-bot is intermittent: the same IP gets the full ~1.5MB page for
    one request and a ~2-5KB stub for the next, so we retry a few times before
    giving up. A blocked response is tiny and returns almost instantly, so the
    retries add little latency. Tested empirically: richer browser headers AND a
    newer Chrome UA both make the block WORSE, so we deliberately keep the
    request minimal (UA only) — do not "improve" the headers here.

    Uses a synchronous subprocess.run in a worker thread (NOT
    asyncio.create_subprocess_exec): the async variant needs a ProactorEventLoop
    on Windows and silently raised NotImplementedError under uvicorn's loop there,
    so EVERY Windows scrape fell back to the 1-image source. subprocess.run works
    regardless of the event loop — this is the project's Windows-safe pattern.

    Anti-bot busting via a per-scrape COOKIE JAR (-c/-b): a cold curl request is
    erratically served Amazon's ~5KB challenge stub, but once any request sets
    session cookies the following requests reliably pass. So we carry cookies
    across the retry attempts (the challenge itself seeds them) — verified to turn
    a flaky 'block/ok/block/block' pattern into 'block→ok→ok→ok'."""
    import shutil
    import subprocess
    import logging
    import os
    import tempfile
    from app.core.proc import no_window_kwargs
    curl = shutil.which("curl")
    if not curl:
        logging.warning("[scrape-native] curl 不在 PATH 上 — 无法本机直连采集 (asin=%s)", asin)
        return None
    url = f"https://www.{_amazon_domain(marketplace)}/dp/{asin}"
    fd, jar = tempfile.mkstemp(prefix="ivyea_ck_", suffix=".txt")
    os.close(fd)
    args = [curl, "-sS", "-L", "--max-time", "25", "--compressed",
            "-A", _REAL_UA, "-c", jar, "-b", jar, url]
    try:
        for i in range(attempts):
            try:
                cp = await asyncio.to_thread(
                    subprocess.run, args,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30,
                    **no_window_kwargs())
                out = cp.stdout or b""
            except Exception:
                out = b""
            html_text = (out or b"").decode("utf-8", "replace")
            blocked = (
                len(html_text) < 50_000  # anti-bot stub, not the real product page
                or bool(re.search(r"Type the characters you see in this image", html_text, re.I))
                or bool(re.search(r"we just need to make sure you're not a robot", html_text, re.I))
            )
            n_imgs = 0
            if not blocked:
                parsed = _parse_amazon_html(html_text)
                n_imgs = len(parsed.get("imageUrls", []))
                if n_imgs:
                    logging.info("[scrape-native] %s 第%d次成功: %dB, %d图", asin, i + 1, len(html_text), n_imgs)
                    return parsed
            logging.info("[scrape-native] %s 第%d次未果: %dB blocked=%s imgs=%d", asin, i + 1, len(html_text), blocked, n_imgs)
            if i < attempts - 1:
                await asyncio.sleep(2.0)  # brief backoff — blocks are often transient
        return None
    finally:
        try:
            os.remove(jar)
        except OSError:
            pass


def _apimart_key() -> str:
    """Return configured Apimart key, empty when unset. Image-generation
    callers should surface a clear 'not configured' error rather than
    falling back to a hardcoded shared key (those got banned upstream)."""
    from app.core import hub_settings
    val = hub_settings.get("apimart_key")
    return str(val) if val else ""


def _apimart_base() -> str:
    from app.core import hub_settings
    val = hub_settings.get("apimart_base")
    return str(val) if val else "https://api.apimart.ai/v1"


# ─── SQLite ───────────────────────────────────────────────────────────────────

def _db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS listing_projects (
        id TEXT PRIMARY KEY,
        asin TEXT NOT NULL,
        marketplace TEXT DEFAULT 'US',
        imgflow_project_id TEXT,
        status TEXT DEFAULT 'created',
        title TEXT,
        bullets TEXT,
        search_terms TEXT,
        aplus_copy TEXT,
        scrape_data TEXT,
        analysis_data TEXT,
        image_slots TEXT,
        created_at REAL,
        updated_at REAL
    )""")
    conn.commit()
    return conn

_db().close()

# Migration: add columns if missing
for _col in [
    "image_slots TEXT", "templates TEXT", "copy_result TEXT", "copy_job_id TEXT",
    "highlights TEXT", "shot_plan TEXT", "creative_sets TEXT",
]:
    try:
        conn = _db()
        conn.execute(f"ALTER TABLE listing_projects ADD COLUMN {_col}")
        conn.commit()
        conn.close()
    except Exception:
        pass


# ─── Models ───────────────────────────────────────────────────────────────────

class CreateProjectReq(BaseModel):
    asin: str
    marketplace: str = "US"
    supplier_url: Optional[str] = None

class GenerateCopyReq(BaseModel):
    type: str
    context: Optional[str] = None

class ProductInfoReq(BaseModel):
    product_name: Optional[str] = None
    description: Optional[str] = None
    selling_points: Optional[str] = None
    target_audience: Optional[str] = None

class ImageGenReq(BaseModel):
    prompt: str
    slot: str
    size: str = "1024x1024"
    reference_urls: list[str] = []
    reference_mode: str = "product"  # product | template (ref 1 = product, ref 2 = layout only)
    use_reference: bool = True       # scene/result 图传 False → 不强塞产品,生成纯场景


class ImageTaskStatusReq(BaseModel):
    task_id: str
    slot: str
    size: str = "1024x1024"


class PlanImageSetReq(BaseModel):
    target_count: int = 0           # 0 = let the AI pick (5–8); else exact count
    color_scheme: str = ""
    language: str = "en"            # callout language hint (for typography)
    deliverable: str = "gallery"    # gallery | aplus; both use the same engine
    visual_tone: str = "natural"    # natural | studio | editorial
    brief: str = ""


class OverlayCalloutReq(BaseModel):
    url: str                        # the rendered (text-free) image to typeset onto
    callout: str = ""
    headline: str = ""              # big top poster line (套图标题)
    text_pos: str = "bottom-center"
    color: str = "#FFFFFF"
    supporting_text: str = ""
    eyebrow: str = ""
    proof: str = ""
    layout_style: str = "editorial"
    accent_color: str = "#4F8CFF"
    theme: str = "auto"


class PrepareAssetReq(BaseModel):
    url: str
    size: str = "1600x1600"
    mode: str = "contain"
    background: str = "#FFFFFF"


class CompositeProductReq(BaseModel):
    background_url: str
    product_url: str
    size: str = "1600x1600"
    text_zone: str = "top-left"
    product_scale: float = 0.52


class RenderBlueprintReq(BaseModel):
    blueprint: str
    scene_urls: list[str] = []
    product_url: str
    size: str = "1600x1600"
    accent_color: str = "#66C85A"
    labels: list[str] = []


class ReviewRenderReq(BaseModel):
    url: str
    size: str = "1600x1600"
    slot: str = ""
    role: str = ""
    shot_type: str = ""
    layout_blueprint: str = ""
    eyebrow: str = ""
    headline: str = ""
    callout: str = ""
    supporting_text: str = ""
    proof: str = ""
    source_url: str = ""
    show_product: bool = True
    product_fidelity_anchors: list[str] = []


class ReviewSetReq(BaseModel):
    deliverable: str = "gallery"


# ─── Project CRUD ─────────────────────────────────────────────────────────────

@router.get("/projects")
def list_projects(_user: str = Depends(require_user)):
    conn = _db()
    rows = conn.execute(
        "SELECT id, asin, marketplace, status, title, created_at, updated_at "
        "FROM listing_projects ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/projects")
async def create_project(body: CreateProjectReq, _user: str = Depends(require_user)):
    pid = str(uuid.uuid4())[:8]
    now = time.time()
    # Try to create an imgflow project for auto-scraping. If the 采集 service
    # isn't running (no Docker / not deployed), fall back to a LOCAL-ONLY project
    # so the user can still fill product info manually + upload images + run AI
    # analysis / copy / prompts. Only the "auto-scrape competitor" step needs it.
    imgflow_id = None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{_imgflow_base()}/projects", json={
                "asin": body.asin, "marketplace": body.marketplace,
                "supplierUrl": body.supplier_url or "",
            })
        if resp.status_code in (200, 201):
            data = resp.json()
            imgflow_id = data.get("id") or data.get("project", {}).get("id")
    except httpx.RequestError:
        imgflow_id = None  # 采集服务不可达 → 本地项目

    conn = _db()
    conn.execute(
        "INSERT INTO listing_projects (id,asin,marketplace,imgflow_project_id,status,created_at,updated_at) VALUES (?,?,?,?,'created',?,?)",
        (pid, body.asin, body.marketplace, str(imgflow_id or ""), now, now)
    )
    conn.commit()
    conn.close()
    return {"id": pid, "imgflow_id": imgflow_id, "asin": body.asin,
            "scrape_available": imgflow_id is not None}


@router.get("/projects/{project_id}")
def get_project(project_id: str, _user: str = Depends(require_user)):
    conn = _db()
    row = conn.execute("SELECT * FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "project not found")
    result = dict(row)
    # Read-time migration keeps saved projects safe after quality rules evolve.
    # Existing bad renders remain visible as history, but internal copy is
    # stripped and their missing render QA blocks commercial approval.
    if result.get("creative_sets"):
        try:
            sets = json.loads(result["creative_sets"])
            scrape_data = json.loads(result["scrape_data"]) if result.get("scrape_data") else {}
            migrated = {}
            for key, value in sets.items():
                if isinstance(value, dict):
                    normalized = _normalize_shot_plan(
                        value, len(value.get("images") or []),
                        "aplus" if key == "aplus" else "gallery",
                    )
                    migrated[key] = _bind_reference_templates(
                        normalized, project_id, scrape_data,
                        "aplus" if key == "aplus" else "gallery",
                    )
            result["creative_sets"] = json.dumps(migrated, ensure_ascii=False)
        except Exception:
            pass
    if result.get("copy_result"):
        try:
            copy_payload = json.loads(result["copy_result"])
        except Exception:
            copy_payload = result["copy_result"]
        repaired_copy = _parse_copy_result(copy_payload)
        if repaired_copy:
            result["copy_result"] = json.dumps(repaired_copy, ensure_ascii=False)
    return result


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, _user: str = Depends(require_user)):
    conn = _db()
    conn.execute("DELETE FROM listing_projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── Scrape (enhanced: saves reference images) ───────────────────────────────

@router.post("/projects/{project_id}/scrape")
async def scrape(project_id: str, _user: str = Depends(require_user)):
    conn = _db()
    row = conn.execute("SELECT asin, marketplace, imgflow_project_id FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)
    asin = row["asin"]
    marketplace = row["marketplace"] or "US"
    imgflow_id = row["imgflow_project_id"]

    data = {}

    # 0) Native curl scrape — returns the FULL main-image set with no Docker / no
    #    extra service. This is the primary path now; curl ships with Windows 10+/
    #    Linux and works from the user's residential IP.
    native_ok = False
    try:
        nd = await _scrape_amazon_native(asin, marketplace)
        if nd and nd.get("imageUrls"):
            data = nd
            native_ok = True
    except Exception:
        pass

    # 1) Optional: imgflow scrape (amazon-image-workflow on :3001) — only used as a
    #    fallback now, for users who run the Docker service and where curl was
    #    blocked by anti-bot.
    imgflow_ok = False
    if not native_ok and imgflow_id:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(f"{_imgflow_base()}/scrape/{imgflow_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    imgflow_ok = bool(data.get("imageUrls") or data.get("images"))
        except Exception:
            pass

    # 2) If imgflow returned empty data, fall back to sorftime product_detail.
    #    NOTE: sorftime only carries ONE (white-background) main image, so this
    #    path can never recover the full set — the UI surfaces a hint to enable
    #    the scrape service (see `scrape_source` below).
    has_title = bool(data.get("title"))
    has_bullets = bool(data.get("bullets"))
    if not has_title and not has_bullets:
        try:
            from app.services import sorftime_service
            import re as _re
            async with sorftime_service._make_client() as client:
                _, raw, err = await sorftime_service._safe_call(
                    client, "product_detail",
                    {"asin": asin, "amzSite": marketplace}, 1,
                )
                if raw and not err and isinstance(raw, str):
                    # Parse structured text: "标题：xxx\n主图：xxx\n产品描述：xxx"
                    title_m = _re.search(r'标题[：:]\s*(.+)', raw)
                    if title_m:
                        data["title"] = title_m.group(1).strip()
                    img_m = _re.search(r'主图[：:]\s*(https?://\S+)', raw)
                    if img_m:
                        data["imageUrls"] = [img_m.group(1).strip()]
                    desc_m = _re.search(r'产品描述[：:]\s*(.+?)(?:\r?\n\r?\n|\r?\n[^\u4e00-\u9fff])', raw, _re.DOTALL)
                    if desc_m:
                        desc_text = desc_m.group(1).strip()
                        # Split by <br> or newlines into bullets
                        parts = _re.split(r'<br>|\n', desc_text)
                        parts = [p.strip() for p in parts if p.strip()]
                        if parts:
                            data["bullets"] = parts[:5]
                            data["description"] = desc_text
        except Exception:
            pass

    # Extract image URLs as reference images
    image_urls = data.get("imageUrls") or data.get("images") or []
    if image_urls:
        data["reference_images"] = image_urls

    # Tell the frontend where the data came from. The Docker-service hint only
    # shows on the sorftime fallback (i.e. native curl scrape was blocked).
    data["scrape_source"] = (
        "native" if native_ok else
        "imgflow" if imgflow_ok else
        "sorftime" if image_urls else "none"
    )
    # The full main-image set is available from native scrape or the imgflow service.
    data["full_images_available"] = native_ok or imgflow_ok

    conn = _db()
    conn.execute(
        "UPDATE listing_projects SET scrape_data = ?, status = 'scraped', updated_at = ? WHERE id = ?",
        (json.dumps(data, ensure_ascii=False), time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return data


# ─── Product Info (manual) ────────────────────────────────────────────────────

@router.post("/projects/{project_id}/product-info")
def save_product_info(project_id: str, body: ProductInfoReq, _user: str = Depends(require_user)):
    conn = _db()
    row = conn.execute("SELECT scrape_data FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404)
    existing = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    existing["manual"] = {
        "product_name": body.product_name or "",
        "description": body.description or "",
        "selling_points": body.selling_points or "",
        "target_audience": body.target_audience or "",
    }
    conn.execute(
        "UPDATE listing_projects SET scrape_data = ?, updated_at = ? WHERE id = ?",
        (json.dumps(existing, ensure_ascii=False), time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── Image Slots Persistence ──────────────────────────────────────────────────

@router.post("/projects/{project_id}/image-slots")
def save_image_slots(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Save image slot data (prompts, urls, sizes) for cross-device sync."""
    conn = _db()
    row = conn.execute("SELECT id FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404)
    conn.execute(
        "UPDATE listing_projects SET image_slots = ?, updated_at = ? WHERE id = ?",
        (json.dumps(body, ensure_ascii=False), time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── Image Upload & Reference ─────────────────────────────────────────────────

@router.post("/projects/{project_id}/upload-image")
async def upload_product_image(project_id: str, file: UploadFile = File(...), _user: str = Depends(require_user)):
    """Upload a product reference image."""
    conn = _db()
    row = conn.execute("SELECT id FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    proj_dir = IMAGES_DIR / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "img.jpg").suffix or ".jpg"
    fname = f"{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
    dest = proj_dir / fname
    content = await file.read()
    dest.write_bytes(content)

    # Add to scrape_data.uploaded_images
    conn = _db()
    row = conn.execute("SELECT scrape_data FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    existing = json.loads(row["scrape_data"]) if row and row["scrape_data"] else {}
    uploaded = existing.get("uploaded_images", [])
    uploaded.append(str(dest))
    existing["uploaded_images"] = uploaded
    white_check = _white_background_score(content)
    if white_check.get("ready"):
        existing["white_product_source"] = f"/api/listing/images/{project_id}/{fname}"
        existing["white_product_source_check"] = {"url": existing["white_product_source"], **white_check}
    conn.execute(
        "UPDATE listing_projects SET scrape_data = ?, updated_at = ? WHERE id = ?",
        (json.dumps(existing, ensure_ascii=False), time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return {"path": str(dest), "filename": fname}


@router.get("/projects/{project_id}/reference-images")
def get_reference_images(project_id: str, _user: str = Depends(require_user)):
    """Get all reference images (scraped URLs + uploaded files)."""
    conn = _db()
    row = conn.execute("SELECT scrape_data FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)
    data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    recommended = _cached_white_product_source(data)
    # Return uploaded images as serving URLs (not raw file paths)
    uploaded_paths = data.get("uploaded_images", [])
    uploaded_urls = []
    for p in uploaded_paths:
        path_obj = Path(p)
        if path_obj.exists():
            uploaded_urls.append({
                "filename": path_obj.name,
                "url": f"/api/listing/images/{project_id}/{path_obj.name}",
                "white_ready": f"/api/listing/images/{project_id}/{path_obj.name}" == recommended,
            })
    return {
        "scraped": data.get("reference_images", []),
        "uploaded": uploaded_urls,
        "white_product_source": recommended,
        "white_product_source_check": data.get("white_product_source_check") or {},
    }


@router.delete("/projects/{project_id}/uploaded-image/{filename}")
def delete_uploaded_image(project_id: str, filename: str, _user: str = Depends(require_user)):
    """Delete an uploaded reference image."""
    path = IMAGES_DIR / project_id / filename
    if path.exists():
        path.unlink()
    # Remove from scrape_data
    conn = _db()
    row = conn.execute("SELECT scrape_data FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    if row:
        data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
        uploaded = [p for p in data.get("uploaded_images", []) if not p.endswith(f"/{filename}")]
        data["uploaded_images"] = uploaded
        if str(data.get("white_product_source") or "").endswith(f"/{filename}"):
            data["white_product_source"] = ""
            data["white_product_source_check"] = {"ready": False, "reason": "deleted"}
        conn.execute(
            "UPDATE listing_projects SET scrape_data=?, updated_at=? WHERE id=?",
            (json.dumps(data, ensure_ascii=False), time.time(), project_id),
        )
        conn.commit()
    conn.close()
    return {"ok": True}


# ─── AI Provider Fallback Chain ───────────────────────────────────────────────


async def _call_ai(prompt: str, max_tokens: int = 2000, web_search: bool = True) -> str:
    """Generate text via the standard fallback chain:
    Hermes → 全局兜底大模型 → Codex → Claude.

    Listing AI is a pure text engine (the prompt forbids tools/commands), so it
    rides the shared ``run_text_chain`` orchestrator — the exact same chain every
    other board uses, gaining the global fallback model and Claude automatically.
    """
    from app.services import ai_synthesis_service

    task_prompt = (
        "你正在作为 Listing 生成板块的纯文本生成引擎。"
        "禁止执行命令、禁止读写文件、禁止修改系统、禁止调用工具；只根据提示词内容返回最终文本。\n\n"
        + prompt
    )
    if not web_search:
        task_prompt = "不要联网搜索，不要调用工具，只基于下面提供的信息回答。\n\n" + task_prompt
    task_prompt = (
        f"{task_prompt}\n\n"
        "输出要求：直接输出最终内容，不要解释调用过程，不要添加 Markdown 代码块。"
    )

    # Use the user's configured provider order (text_ai_providers — application-model-first
    # by default). Hermes is slow for big generations but the long-request path
    # is sized for it (frontend 15-min axios timeout + nginx 900s on the listing
    # generate endpoints), so a slow hermes run completes instead of being cut.
    # (apimart is image-gen only and is already excluded from the text chain.)
    try:
        _provider, text = await ai_synthesis_service.run_text_chain(task_prompt)
        return text
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"AI 调用失败（Hermes / 全局兜底 / Codex / Claude 均不可用）：{e}")


async def _review_single_prompt(
    initial_prompt: str,
    slot_label: str,
    slot_size: str,
    color_scheme: str = "",
) -> str:
    """Self-check and optimize one generated image prompt — cosmetic fixes only, no invented content."""
    color_rule = (
        f"\n- MUST keep the color scheme '{color_scheme}' if already present; do not remove it."
        if color_scheme and color_scheme.strip().lower() != "auto" else ""
    )
    review_prompt = f"""You are a prompt EDITOR. Your ONLY job is cosmetic syntax improvements — you must NOT invent or change any facts.

SLOT: {slot_label}  |  CANVAS: {slot_size or "not specified"}

━━━ ABSOLUTE PROHIBITIONS (violation = output the draft unchanged) ━━━
• DO NOT add, change, or remove any reference image URL ("Reference: https://..." lines must appear verbatim)
• DO NOT modify the product's physical description — keep every color, material, shape, size, and feature exactly as written
• DO NOT invent any spec, feature, or scene detail that is not already present in the draft
• DO NOT change what the image is supposed to show or its scene/setting{color_rule}

━━━ ALLOWED FIXES (cosmetic only) ━━━
1. LIGHTING: Replace vague phrases ("good lighting", "bright light") with a concrete rig description ONLY if you can infer it from the existing scene context — e.g., white-background studio → "3-point studio lighting, 45° softbox key, fill reflector"
2. CANVAS: If "{slot_size}" is not already mentioned in the draft, append a sentence like "Compose for {slot_size} canvas." at the end
3. FILLER REMOVAL: Remove hollow adjectives ("beautiful", "stunning", "perfect", "amazing") — do NOT replace them with invented specifics, just remove them
4. COMPOSITION: If no camera angle is specified, add one neutral descriptor (e.g., "eye-level hero angle") that fits the existing scene

DRAFT PROMPT:
{initial_prompt}

OUTPUT: Edited prompt text only. If no valid fix is needed, return the draft unchanged. No prefix, no explanation."""

    try:
        reviewed = await _call_ai(review_prompt, max_tokens=1000, web_search=False)
        return reviewed.strip() if reviewed.strip() else initial_prompt
    except Exception:
        return initial_prompt


async def _review_batch_prompts(
    prompts: dict,
    slot_details: list,
    color_scheme: str = "",
) -> dict:
    """Batch self-check and optimize all generated prompts in a single AI call."""
    if not prompts:
        return prompts

    slot_map = {s["id"]: s for s in slot_details}
    color_rule = (
        f"\n- MANDATORY: Maintain the '{color_scheme}' color scheme throughout all prompts."
        if color_scheme and color_scheme.strip().lower() != "auto" else ""
    )

    prompts_block = "\n\n".join(
        f'SLOT: {sid}\nLABEL: {slot_map.get(sid, {}).get("label", sid)}\n'
        f'CANVAS: {slot_map.get(sid, {}).get("size", "")}\nDRAFT:\n{txt}'
        for sid, txt in prompts.items()
    )
    slot_ids_json = ", ".join(f'"{s}":"improved_prompt_here"' for s in prompts)

    review_prompt = f"""You are a prompt EDITOR reviewing {len(prompts)} image prompts. Your ONLY job is cosmetic syntax fixes — you must NOT invent or change any facts.

━━━ ABSOLUTE PROHIBITIONS (violation = output that prompt unchanged) ━━━
• DO NOT add, change, or remove any reference image URL ("Reference: https://..." lines must appear verbatim in every prompt that already has them)
• DO NOT modify the product's physical description — keep every color, material, shape, size, and feature exactly as written
• DO NOT invent any spec, feature, or scene detail that is not already present in the draft
• DO NOT change what any image is supposed to show or its scene/setting{color_rule}

━━━ ALLOWED FIXES (cosmetic only, apply to every prompt) ━━━
1. LIGHTING: Replace vague phrases ("good lighting", "bright light") with a concrete rig description ONLY if inferable from the existing scene context
2. CANVAS: If the slot's canvas size is not already mentioned, append a sentence like "Compose for <size> canvas." at the end
3. FILLER REMOVAL: Remove hollow adjectives ("beautiful", "stunning", "perfect", "amazing") — do NOT replace with invented specifics, just remove them
4. COMPOSITION: If no camera angle is specified, add one neutral descriptor that fits the existing scene

DRAFT PROMPTS:
{prompts_block}

OUTPUT FORMAT (valid JSON, no other text):
{{"prompts":{{{slot_ids_json}}}}}"""

    try:
        content = await _call_ai(review_prompt, max_tokens=8000, web_search=False)
        result = _parse_json_response(content)
        if result and isinstance(result.get("prompts"), dict):
            reviewed = result["prompts"]
            return {
                sid: str(reviewed[sid]).strip()
                if reviewed.get(sid) and str(reviewed[sid]).strip()
                else orig
                for sid, orig in prompts.items()
            }
    except Exception:
        pass

    return prompts


def _reference_images(scrape_data: dict) -> list[str]:
    refs = scrape_data.get("reference_images") or scrape_data.get("imageUrls") or []
    if isinstance(refs, str):
        return [refs]
    return [str(x) for x in refs if str(x).strip()] if isinstance(refs, list) else []


def _slot_purpose(slot_id: str, label: str) -> str:
    key = slot_id.lower()
    if key == "main":
        return "pure white Amazon main image, product centered, no text, shopper can inspect the full product"
    if key.startswith("sub1"):
        return "lifestyle scene showing the primary use case and buyer outcome"
    if key.startswith("sub2"):
        return "feature detail image with a clean reserved area for later benefit copy"
    if key.startswith("sub3"):
        return "size, scale, specification, or usage clarity image"
    if key.startswith("sub4"):
        return "multi-angle, structure, technology, or material detail image"
    if key.startswith("sub5"):
        return "package, accessories, kit contents, or value summary image"
    if key.startswith("sub6"):
        return "multi-scenario benefit summary image"
    if "banner" in key:
        return "Premium A+ hero banner with brand-level composition"
    if "compare" in key or key.endswith("_4"):
        return "A+ comparison, trust, specification, or advantage module"
    if "brand" in key:
        return "brand story and trust-building A+ module"
    return f"{label or slot_id} product image module"


def _fallback_image_prompt(
    slot_id: str,
    label: str,
    size: str,
    row,
    scrape_data: dict,
    analysis_data: dict,
    color_scheme: str = "",
    template_hint: str = "",
) -> str:
    src = _copy_source(row, scrape_data, analysis_data)
    refs = _reference_images(scrape_data)
    ref = refs[0] if refs else "no reference image available"
    product_lock = _clean_text(
        analysis_data.get("product_lock")
        or f"{src['title']} exactly as shown in the reference image; keep the real shape, color, materials, proportions, logo placement, and included accessories unchanged."
    )
    features = src["usp"] + src["bullets"]
    feature = _clean_text(features[0]) if features else _clean_text(src["description"] or src["title"])
    canvas = size or ("1400x1400 or larger square" if slot_id == "main" else "configured slot size")
    purpose = _slot_purpose(slot_id, label)
    color_line = f" Use a {color_scheme} palette for backgrounds, props, lighting, and typography." if color_scheme else ""
    template_line = f" Adapt this template direction without copying unsupported claims: {template_hint[:420]}." if template_hint else ""
    text_rule = "no words, letters, numbers, badges, icons, UI overlays or watermarks"
    return (
        f"{product_lock} Reference: {ref}. Create a {purpose} for slot \"{label or slot_id}\". "
        f"Target canvas: {canvas}; compose specifically for this size and orientation. "
        f"Image goal: communicate {feature[:220]}. "
        f"Use commercial Amazon product photography with accurate product rendering, controlled studio lighting, natural shadows, sharp focus, realistic materials, and clean premium composition.{color_line} "
        f"Composition: product remains visually dominant, with deliberate low-detail negative space for later typography; render {text_rule}. "
        f"For A+ desktop modules use a wide 1464x600 layout when requested; for mobile modules use a compact 600x450 layout when requested. "
        f"Do not invent specs, certifications, accessories, colors, or features not present in the product data. {template_line}".strip()
    )


def _fallback_prompts_for_slots(row, scrape_data: dict, analysis_data: dict, slot_details: list[dict], color_scheme: str = "", template_hint: str = "") -> dict:
    prompts = {}
    for s in slot_details:
        prompts[s["id"]] = _fallback_image_prompt(
            s["id"],
            s.get("label") or s["id"],
            s.get("size") or "",
            row,
            scrape_data,
            analysis_data,
            color_scheme,
            template_hint,
        )
    return {
        "product_lock": analysis_data.get("product_lock") or _copy_source(row, scrape_data, analysis_data)["title"],
        "visual_style": analysis_data.get("visual_style") or "Premium Amazon commercial photography with consistent product appearance.",
        "prompts": prompts,
        "fallback": True,
        "warning": "Hermes/Codex 当前不可用，已用本地规则生成可编辑图片提示词；恢复额度后可重新智能生成。",
    }


def _fallback_template_content(content: str) -> str:
    text = content.strip()
    text = re.sub(r"https?://\S+", "{reference_url}", text)
    text = re.sub(r"\b(#[0-9a-fA-F]{3,8})\b", "{color_scheme}", text)
    if "{product_lock}" not in text:
        text = "{product_lock}\nReference: {reference_url}\n" + text
    if "{visual_style}" not in text:
        text += "\nVisual style: {visual_style}. Color direction: {color_scheme}."
    return text


def _fallback_analysis(row, scrape_data: dict, analysis_data: dict) -> dict:
    src = _copy_source(row, scrape_data, analysis_data)
    features = src["usp"] + src["bullets"] or [src["description"] or src["title"]]
    return {
        "usp": [f[:120] for f in features[:3]],
        "target_audience": src["audience"],
        "scenarios": ["Primary product use case", "Everyday comparison shopping", "Gift, home, work, travel, or category-relevant use"],
        "keywords": (src["keywords"] + _keywords_from_text(" ".join([src["title"], src["description"], " ".join(src["bullets"])])))[:15],
        "image_strategy": {
            "main": "Show the exact product clearly on a pure white Amazon-ready background.",
            "sub1": "Show the primary buyer outcome in context.",
            "sub2": "Highlight the strongest feature with concise callouts.",
            "sub3": "Clarify size, use, or compatibility from available data.",
            "sub4": "Show details, structure, or material quality.",
            "sub5": "Show included items or value summary.",
            "sub6": "Close with scenarios, trust, or benefit summary.",
        },
        "cosmo_score": "local-fallback",
        "optimization_suggestions": ["补充真实规格和卖点", "上传清晰参考图", "恢复 Hermes/Codex 后重新运行智能分析"],
    }


# ─── Skill-Enhanced AI Analysis ───────────────────────────────────────────────

def _load_skill_knowledge() -> str:
    """Load relevant skill knowledge for analysis prompts."""
    parts = []
    try:
        creative = get_skill("amazon/amazon-listing-creative")
        parts.append(f"[LISTING CREATIVE STRATEGY]\n{creative.content_body[:3000]}")
    except Exception:
        pass
    try:
        audit = get_skill("amazon/amazon-asin-cosmo-rufus-audit")
        parts.append(f"[ASIN AUDIT METHODOLOGY]\n{audit.content_body[:2000]}")
    except Exception:
        pass
    return "\n\n".join(parts)


# ─── Vision: analyze ALL product images (scraped + uploaded) ──────────────────
# The vision providers cap each call at 4 images, so we batch and aggregate.

_VISION_BATCH = 4


async def _img_datauri_from_url(url: str) -> Optional[str]:
    """Download an image URL and return a base64 data-URI, or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=10), follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
        ct = (r.headers.get("content-type") or "").split(";")[0].strip()
        if not ct.startswith("image/"):
            ct = mimetypes.guess_type(url)[0] or "image/jpeg"
        return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"
    except Exception:
        return None


def _img_datauri_from_path(path_str: str) -> Optional[str]:
    """Read a local uploaded image and return a base64 data-URI, or None."""
    try:
        p = Path(path_str)
        if not p.is_file():
            return None
        ct = mimetypes.guess_type(str(p))[0] or "image/jpeg"
        return f"data:{ct};base64,{base64.b64encode(p.read_bytes()).decode()}"
    except Exception:
        return None


async def _collect_vision(prompt: str, images_b64: list[str]) -> str:
    """Run the vision fallback chain and collect its text output."""
    from app.services import ai_synthesis_service
    parts: list[str] = []
    async for prov, chunk in ai_synthesis_service.stream_vision(prompt, images_b64):
        if prov != "error":
            parts.append(chunk)
    return "".join(parts).strip()


async def _analyze_all_images(scrape_data: dict) -> str:
    """Vision-analyze EVERY scraped + uploaded image and return an aggregated
    "图片卖点清单" used downstream by analysis / copy / image-prompt generation.

    Returns "" when no images or no vision model is configured.
    """
    from app.services import ai_synthesis_service
    if not ai_synthesis_service.has_vision_capability():
        return ""

    images: list[str] = []
    for url in _reference_images(scrape_data):
        d = await _img_datauri_from_url(url)
        if d:
            images.append(d)
    for path_str in scrape_data.get("uploaded_images", []) or []:
        d = _img_datauri_from_path(path_str)
        if d:
            images.append(d)
    if not images:
        return ""

    total = len(images)
    batch_notes: list[str] = []
    for i in range(0, total, _VISION_BATCH):
        batch = images[i:i + _VISION_BATCH]
        lo, hi = i + 1, i + len(batch)
        prompt = (
            f"这是某亚马逊产品的第 {lo}-{hi} 张图片（共 {total} 张）。请逐张分析并提取：\n"
            "① 体现的核心卖点 / 功能点；② 视觉风格 / 构图 / 配色；"
            "③ 使用场景 / 目标人群；④ 可直接复用到文案与图片提示词的要点。\n"
            "用简洁中文分点输出，每张图前标注其序号。"
        )
        try:
            text = await _collect_vision(prompt, batch)
        except Exception:
            text = ""
        if text:
            batch_notes.append(f"【图 {lo}-{hi}】\n{text}")

    if not batch_notes:
        return ""

    combined = "\n\n".join(batch_notes)
    # Aggregate the per-batch notes into one de-duplicated, prioritized list.
    try:
        summary = await _call_ai(
            "以下是对一组产品图片逐批的视觉分析。请汇总成一份『图片卖点清单』："
            "去重合并、按重要度排序，明确列出可用于 Listing 文案与图片提示词的"
            "卖点、视觉风格与使用场景。\n\n" + combined,
            web_search=False,
        )
        return (summary or "").strip() or combined
    except Exception:
        return combined


async def _analyze_reference_templates(scrape_data: dict) -> list[dict]:
    """Reverse-engineer each collected gallery image into a reusable shot brief.

    This is intentionally separate from generic product analysis: sequence and
    per-image composition must survive so the planner cannot assign an in-box
    message to a usage-summary template (or similar structural mismatches).
    """
    from app.services import ai_synthesis_service
    refs = _reference_images(scrape_data)[:8]
    if len(refs) < 2 or not ai_synthesis_service.has_vision_capability():
        return []
    images: list[tuple[int, str]] = []
    for index, url in enumerate(refs, 1):
        data_uri = await _img_datauri_from_url(url)
        if data_uri:
            images.append((index, data_uri))
    story: list[dict] = []
    allowed_types = _SHOT_TYPES - {"aplus_banner"}
    for offset in range(0, len(images), _VISION_BATCH):
        batch = images[offset:offset + _VISION_BATCH]
        indices = [item[0] for item in batch]
        prompt = f"""你是电商视觉总监。下面是亚马逊套图中的原始第 {indices[0]}–{indices[-1]} 张。
逐张反推设计逻辑，不评价产品好坏。只返回 JSON：
{{"templates":[{{"index":1,"role":"简短中文角色","shot_type":"white_main|hero_feature|lifestyle|detail|comparison|specs|in_box|trust","layout_blueprint":"white_bundle|media_proof_split|connectivity_diagram|environmental_proof|coverage_diagram|speed_comparison|day_night_split|use_case_mosaic","buyer_question":"这张图回答的购买问题","visual_structure":"主体位置/大小、镜头类型、分栏或网格、背景层次、视觉动线","text_zone":"top-left|top-center|top-right|center-left|center-right|bottom-left|bottom-center|bottom-right","information_density":"low|medium|high"}}]}}
要求：index 必须使用原始序号 {indices}；识别图片实际内容，不套固定七张模板；忽略图中的品牌文案措辞，提取可迁移的销售任务和版式结构。"""
        try:
            parsed = _strip_json(await _collect_vision(prompt, [item[1] for item in batch])) or {}
        except Exception:
            parsed = {}
        for item in parsed.get("templates", []) if isinstance(parsed, dict) else []:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            if index not in indices:
                continue
            shot_type = str(item.get("shot_type") or "hero_feature").strip().lower()
            if shot_type not in allowed_types:
                shot_type = "hero_feature"
            text_zone = str(item.get("text_zone") or "top-left")
            if text_zone not in _TEXT_ZONES:
                text_zone = "top-left"
            blueprint = str(item.get("layout_blueprint") or "").strip()
            if blueprint not in _LAYOUT_BLUEPRINTS:
                blueprint = _DEFAULT_BLUEPRINT_ORDER[min(index - 1, len(_DEFAULT_BLUEPRINT_ORDER) - 1)]
            story.append({
                "index": index,
                "role": _clean_text(item.get("role"))[:24],
                "shot_type": shot_type,
                "layout_blueprint": blueprint,
                "buyer_question": _clean_text(item.get("buyer_question"))[:160],
                "visual_structure": _clean_text(item.get("visual_structure"))[:500],
                "text_zone": text_zone,
                "information_density": str(item.get("information_density") or "medium")[:12],
            })
    return sorted(story, key=lambda item: item["index"])


def _fallback_product_visual_profile(product_context: str) -> dict:
    """Build a category-aware visual identity when the vision call is unavailable.

    The profile describes how the physical product behaves in an image.  It is
    deliberately not a gallery template: a soft towel, an occupied tent and a
    rigid camera require different scale cues, contact physics and useful shots.
    """
    text = str(product_context or "").lower()
    if re.search(r"\b(towel|bath towel|hand towel|washcloth|microfiber cloth)\b|毛巾|浴巾", text):
        return {
            "category_family": "towel / soft home textile",
            "object_behavior": "soft_goods",
            "form_and_scale": "Flexible rectangular textile shown folded, draped or naturally handled; thickness and edge finish must stay credible.",
            "materials_and_finish": ["visible weave or pile", "soft compressible volume", "real stitched edges"],
            "product_colours": ["preserve the exact textile colour from the reference"],
            "supporting_palette": ["#F4F0E8", "#D8C7B5", "#8A6F56", "#4E5B4B", "#282622"],
            "fidelity_anchors": ["exact colour", "weave or pile character", "border and stitching", "set quantity", "true proportions"],
            "natural_interactions": ["folding", "draping", "drying", "gentle hand contact", "stacked storage"],
            "scene_families": ["quiet bathroom", "linen shelf", "spa-like but lived-in home", "pool or travel bag when supported"],
            "visual_opportunities": ["tactile macro", "layered folds", "absorbency context without fake test data", "colour-coordinated stack", "human scale cue"],
            "avoid": ["rigid floating slab", "impossible folds", "plastic fibres", "invented embroidery", "luxury marble cliché"],
        }
    if re.search(r"\b(tent|camping tent|backpacking tent|canopy|shelter)\b|帐篷|天幕", text):
        return {
            "category_family": "tent / spatial outdoor gear",
            "object_behavior": "spatial_gear",
            "form_and_scale": "Large occupiable shelter whose panel geometry, poles, doors, windows, guy lines and footprint define product identity.",
            "materials_and_finish": ["tensioned technical fabric", "credible seams", "real poles and stakes", "ground contact"],
            "product_colours": ["preserve every fabric and pole colour block from the reference"],
            "supporting_palette": ["#E9E3D6", "#A7AD8C", "#667151", "#B97645", "#252A23"],
            "fidelity_anchors": ["exact silhouette", "panel and door count", "pole architecture", "window placement", "colour blocking", "capacity and packed items only when supported"],
            "natural_interactions": ["pitching", "entering", "resting inside", "ventilating", "packing"],
            "scene_families": ["real campsite", "forest clearing", "open grassland", "car-camping pitch", "interior sleeping setup"],
            "visual_opportunities": ["environmental hero", "human scale", "interior spatial view", "setup sequence", "weather readiness", "packed-versus-pitched story"],
            "avoid": ["changing the tent architecture", "impossible interior volume", "missing guy lines", "floating shelter", "extreme fantasy landscape"],
        }
    if re.search(r"\b(camera|trail cam|action camera|security camera)\b|相机|摄像机|监控", text):
        return {
            "category_family": "camera / compact rigid device",
            "object_behavior": "rigid_device",
            "form_and_scale": "Compact precision device; controls, lenses, screens, ports and mounting orientation are identity-critical.",
            "materials_and_finish": ["real glass optics", "controlled matte surfaces", "precise seams", "credible screen reflections"],
            "product_colours": ["preserve the exact body, lens, control and logo colours from the reference"],
            "supporting_palette": ["#EEF1F3", "#C8D0D6", "#657581", "#6E8D72", "#22292E"],
            "fidelity_anchors": ["lens count and position", "body silhouette", "buttons and ports", "screen and logo placement", "mounting hardware", "included quantity"],
            "natural_interactions": ["mounting", "handheld operation", "field use", "screen review", "packing"],
            "scene_families": ["category-appropriate field location", "restrained technical studio", "real use environment", "gear preparation surface"],
            "visual_opportunities": ["precision hero", "operational close-up", "credible use scale", "captured-result context", "day/night context when supported"],
            "avoid": ["extra lenses", "invented ports", "fake app UI", "oversized device", "neon technology effects"],
        }
    return {
        "category_family": "general consumer product",
        "object_behavior": "category_specific",
        "form_and_scale": "Infer the real product's rigidity, scale, contact points and normal orientation from the white-background source.",
        "materials_and_finish": ["physically accurate material", "credible surface response", "real construction details"],
        "product_colours": ["preserve every exact product colour from the reference"],
        "supporting_palette": ["#F2EFE9", "#D7D0C5", "#8A7967", "#66736B", "#292A28"],
        "fidelity_anchors": ["silhouette", "proportions", "colour", "material", "visible controls or construction", "included quantity"],
        "natural_interactions": ["normal handling", "primary real-world use", "storage or setup"],
        "scene_families": ["real home, workplace or outdoor setting appropriate to the category", "restrained studio"],
        "visual_opportunities": ["material detail", "human scale", "primary use", "benefit-led hero", "configuration or storage"],
        "avoid": ["generic pedestal ad", "impossible physics", "invented features", "decorative AI effects", "unrelated luxury props"],
    }


def _normalise_product_visual_profile(value: dict, fallback: dict) -> dict:
    if not isinstance(value, dict):
        return fallback
    result = dict(fallback)
    for key in ("category_family", "object_behavior", "form_and_scale"):
        cleaned = _clean_text(value.get(key))
        if cleaned:
            result[key] = cleaned[:500]
    for key in (
        "materials_and_finish", "product_colours", "supporting_palette",
        "fidelity_anchors", "natural_interactions", "scene_families", "visual_opportunities", "avoid",
    ):
        items = value.get(key)
        if isinstance(items, list):
            cleaned = [_clean_text(item)[:220] for item in items if _clean_text(item)]
            if cleaned:
                result[key] = cleaned[:10]
    return result


async def _analyze_product_visual_identity(
    scrape_data: dict, product_context: str, white_source: str,
) -> dict:
    """Stage 1 of visual planning: understand this product before designing shots."""
    fallback = _fallback_product_visual_profile(product_context)
    from app.services import ai_synthesis_service
    if not ai_synthesis_service.has_vision_capability():
        return fallback

    candidates: list[str] = []
    for value in [white_source, *_reference_images(scrape_data)[:4]]:
        value = str(value or "").strip()
        if value and value not in candidates:
            candidates.append(value)
    images: list[str] = []
    # User uploads are deliberate product truth and take priority even when the
    # background is not pure white. Feed them to visual identity analysis before
    # scraped gallery images.
    for path_str in (scrape_data.get("uploaded_images") or [])[:2]:
        data_uri = _img_datauri_from_path(str(path_str))
        if data_uri and data_uri not in images:
            images.append(data_uri)
    for value in candidates[:4]:
        data_uri: Optional[str] = None
        if value.startswith("data:"):
            data_uri = value
        elif value.startswith("/api/listing/images/"):
            rel = value.split("/api/listing/images/", 1)[1].split("?", 1)[0]
            parts = [part for part in rel.split("/") if part and part not in {".", ".."}]
            if len(parts) >= 2:
                data_uri = _img_datauri_from_path(str(IMAGES_DIR / parts[0] / parts[-1]))
        else:
            data_uri = await _img_datauri_from_url(value)
        if data_uri and data_uri not in images:
            images.append(data_uri)
    if not images:
        return fallback

    prompt = f"""You are stage 1 of an ecommerce visual-director pipeline. Analyze the PHYSICAL PRODUCT before any gallery is designed.
Image 1 is the white-background product truth when available. Other images are evidence of use and features only.

PRODUCT FACTS:
{product_context[:9000]}

Return JSON only:
{{"category_family":"specific product family","object_behavior":"soft_goods|rigid_device|spatial_gear|wearable|furniture|consumable|other",
"form_and_scale":"physical form, orientation, flexibility and real scale behaviour",
"materials_and_finish":["visible material/finish"],
"product_colours":["exact product colours and colour blocking visible in the references"],
"supporting_palette":["five product-compatible #RRGGBB colours for background, surface, supporting tone, accent and deep neutral"],
"fidelity_anchors":["details that must remain exactly unchanged"],
"natural_interactions":["physically normal ways people/environment contact the product"],
"scene_families":["real settings that reveal value"],
"visual_opportunities":["category-specific photographic ideas, not fixed layouts"],
"avoid":["category-specific visual mistakes and AI failure modes"]}}

Be concrete. A towel must be treated as flexible textile, a tent as occupiable architecture, and a camera as a rigid precision device.
Do not design image slots, do not copy the collected gallery's composition, and do not infer unsupported specifications."""
    try:
        parsed = _strip_json(await _collect_vision(prompt, images)) or {}
    except Exception:
        parsed = {}
    return _normalise_product_visual_profile(parsed, fallback)


@router.post("/projects/{project_id}/ai-analyze")
async def ai_analyze(project_id: str, _user: str = Depends(require_user)):
    """Run skill-enhanced AI analysis + imgflow deep analysis (COSMO/Rufus/SIF)."""
    conn = _db()
    row = conn.execute("SELECT * FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    product_context = _build_product_context(row, scrape_data, {})
    skill_knowledge = _load_skill_knowledge()

    # 0. Vision-analyze EVERY scraped + uploaded image into a selling-point list,
    #    reused downstream by copy + image-prompt generation (stored on the project).
    image_insights = await _analyze_all_images(scrape_data)

    # 1. Call imgflow deep analysis (COSMO/Rufus/SIF/Sorftime)
    imgflow_analysis = {}
    imgflow_id = row["imgflow_project_id"]
    if imgflow_id:
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(f"{_imgflow_base()}/analysis/{imgflow_id}")
                if resp.status_code == 200:
                    imgflow_analysis = resp.json()
        except Exception:
            pass

    # 2. Skill-enhanced AI analysis
    prompt = f"""你是Amazon产品分析专家。基于以下专业知识和产品信息，进行深度分析。

## 专业知识参考
{skill_knowledge[:4000]}

## 产品信息
{product_context}

## 产品图片视觉分析（采集 + 上传的全部图片）
{image_insights or "（未配置视觉模型或暂无图片）"}

## imgflow深度分析数据
{json.dumps(imgflow_analysis, ensure_ascii=False)[:2000] if imgflow_analysis else "未获取到"}

请输出结构化分析（JSON格式）：
{{
  "usp": ["核心卖点1", "核心卖点2", "核心卖点3"],
  "target_audience": "目标受众描述",
  "scenarios": ["使用场景1", "使用场景2", "使用场景3"],
  "keywords": ["关键词1", "关键词2", ...最多15个],
  "image_strategy": {{
    "main": "主图策略建议",
    "sub1": "副图1策略(USP概览)",
    "sub2": "副图2策略(对比图)",
    "sub3": "副图3策略(场景图)",
    "sub4": "副图4策略(技术/细节)",
    "sub5": "副图5策略(效果展示)",
    "sub6": "副图6策略(包装/配件)"
  }},
  "cosmo_score": "基于分析的COSMO评分估计(0-100)",
  "optimization_suggestions": ["建议1", "建议2", "建议3"]
}}

直接输出JSON，不要其他文字。"""

    fallback_used = False
    warning = None
    try:
        content = await _call_ai(prompt, max_tokens=3000)
    except HTTPException as e:
        structured = _fallback_analysis(row, scrape_data, {})
        content = json.dumps(structured, ensure_ascii=False)
        fallback_used = True
        warning = f"AI 当前不可用（Hermes/全局兜底/Codex/Claude 均失败），已使用本地规则生成基础分析。原因：{str(e.detail)[:220]}"

    # Merge imgflow data with AI analysis
    combined = {"ai_analysis": content, "imgflow": imgflow_analysis, "image_insights": image_insights}
    if fallback_used:
        combined["fallback"] = True
        combined["warning"] = warning
    try:
        parsed = json.loads(content.strip().strip("```json").strip("```"))
        combined["structured"] = parsed
    except Exception:
        combined["structured"] = None

    conn = _db()
    conn.execute(
        "UPDATE listing_projects SET analysis_data = ?, status = 'analyzed', updated_at = ? WHERE id = ?",
        (json.dumps(combined, ensure_ascii=False), time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return combined


# ─── Proxy: imgflow analysis (legacy) ────────────────────────────────────────

@router.post("/projects/{project_id}/analyze")
async def analyze(project_id: str, _user: str = Depends(require_user)):
    conn = _db()
    row = conn.execute("SELECT imgflow_project_id FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)
    imgflow_id = row["imgflow_project_id"]
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(f"{_imgflow_base()}/analysis/{imgflow_id}")
        if resp.status_code != 200:
            raise HTTPException(502, f"analysis failed: {resp.text}")
        data = resp.json()
    conn = _db()
    conn.execute(
        "UPDATE listing_projects SET analysis_data = ?, status = 'analyzed', updated_at = ? WHERE id = ?",
        (json.dumps(data, ensure_ascii=False), time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return data


# ─── Copy Generation ──────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/copy")
async def generate_copy(project_id: str, body: GenerateCopyReq, _user: str = Depends(require_user)):
    conn = _db()
    row = conn.execute("SELECT * FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    analysis_data = json.loads(row["analysis_data"]) if row["analysis_data"] else {}
    product_context = _build_product_context(row, scrape_data, analysis_data)
    # Fold the all-image vision selling-points (from ai-analyze) into the context
    # so every copy variant is grounded in what the product images actually show.
    _img_sp = analysis_data.get("image_insights", "")
    if _img_sp:
        product_context = f"{product_context}\n\n## 图片卖点（对采集+上传全部图片的视觉分析）\n{_img_sp}"

    prompts = {
        "title": f"""你是Amazon Listing优化专家。生成3个优化后的产品标题候选。
要求（亚马逊2026-07-27新规）：每个标题**不超过75个字符（含空格）**，所有分类统一上限。
结构：品牌 + 产品类型 + 1-2个最核心关键词/特性，前80字符内前置产品类型与主关键词（手机端友好）。
不要堆砌关键词、不要塞规格清单——次要关键词放到「商品亮点」和五点里。Title Case，英文输出。
产品信息：
{product_context}
{f"额外要求：{body.context}" if body.context else ""}
输出3个标题，数字编号，每个单独一行。每个标题后用括号标注字符数，如 (62 chars)。""",

        "highlights": f"""你是Amazon Listing优化专家。生成「商品亮点 Product Highlights」（亚马逊2026-07-27新增字段）。
要求：
- 一行短语串，**总长度不超过125个字符（含空格）**。
- 用「产品特性/优势」的**短语**，不是完整句子；多个短语用英文逗号 ", " 分隔。
- 覆盖材质、核心功能、使用场景、兼容性等关键信息（参考示例：Non-stick, Food Grade, Heat Resistant 220°C, Fits Ninja Crispi）。
- 该字段**可被搜索**，自然嵌入与标题不重复的核心关键词。
- 仅当标题<75字符时前台展示，所以要言之有物、信息密度高。英文输出。
产品信息：
{product_context}
{f"额外要求：{body.context}" if body.context else ""}
直接输出一行亮点短语串，并在末尾用括号标注字符数，如 (118 chars)。""",

        "bullets": f"""你是Amazon Listing优化专家。生成5条Bullet Points（五点描述，新规下保持不变）。
要求：大写关键词开头(如 PREMIUM QUALITY:)，每条150-250字符，英文输出。
覆盖产品细节、使用场景、材质说明、注意事项、售后信息。
产品信息：
{product_context}
{f"额外要求：{body.context}" if body.context else ""}""",

        "search_terms": f"""你是Amazon SEO专家。生成后台搜索词。
要求：≤250字节，不重复标题词，空格分隔，英文输出。
产品信息：
{product_context}
直接输出搜索词。""",

        "aplus": f"""你是Amazon A+内容策划专家。生成A+ Content文案。
输出：1.品牌故事 2.横幅标题 3.三个特性模块 4.对比图文案 5.三个场景描述。英文输出。
产品信息：
{product_context}
{f"额外要求：{body.context}" if body.context else ""}""",
    }

    if body.type not in prompts:
        raise HTTPException(400, f"type must be one of: {list(prompts.keys())}")

    fallback_used = False
    warning = None
    try:
        content = await _call_ai(prompts[body.type])
    except HTTPException as e:
        detail = str(e.detail)
        content = _fallback_copy(body.type, row, scrape_data, analysis_data)
        fallback_used = True
        warning = f"AI 当前不可用（Hermes/全局兜底/Codex/Claude 均失败），已使用本地规则生成一版可编辑文案。原因：{detail[:220]}"

    field_map = {"title": "title", "bullets": "bullets", "search_terms": "search_terms", "aplus": "aplus_copy", "highlights": "highlights"}
    conn = _db()
    conn.execute(
        f"UPDATE listing_projects SET {field_map[body.type]} = ?, updated_at = ? WHERE id = ?",
        (content, time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return {"type": body.type, "content": content, "fallback": fallback_used, "warning": warning}


# ─── 套图美术指导:结构化、自适应的 shot plan ──────────────────────────────────

_DEFAULT_ROLES = ["主图", "核心利益", "真实使用", "关键细节", "对比证明", "规格/兼容", "包装清单", "信任收口"]
_APLUS_ROLES = ["品牌首屏", "核心利益", "使用方式", "技术/细节", "信任收口"]

# A production-oriented visual vocabulary.  Legacy names are accepted and
# normalized so existing projects continue to load, but new plans no longer
# force a product-less fantasy scene.
_SHOT_TYPES = {
    "white_main", "hero_feature", "lifestyle", "detail", "comparison",
    "specs", "in_box", "trust", "aplus_banner",
}
_LEGACY_SHOT_TYPE = {"feature": "hero_feature", "scene": "lifestyle"}
_DEFAULT_TYPE_ORDER = [
    "white_main", "hero_feature", "lifestyle", "detail",
    "comparison", "specs", "in_box", "trust",
]
_APLUS_TYPE_ORDER = ["aplus_banner", "hero_feature", "lifestyle", "detail", "trust"]
_TEXT_ZONES = {
    "top-left", "top-center", "top-right", "center-left", "center-right",
    "bottom-left", "bottom-center", "bottom-right",
}
_LAYOUT_STYLES = {"editorial", "minimal", "split", "proof", "grid"}
_LAYOUT_BLUEPRINTS = {
    "white_bundle", "media_proof_split", "connectivity_diagram",
    "environmental_proof", "coverage_diagram", "speed_comparison",
    "day_night_split", "use_case_mosaic",
}
_DEFAULT_BLUEPRINT_ORDER = [
    "white_bundle", "media_proof_split", "connectivity_diagram",
    "environmental_proof", "coverage_diagram", "speed_comparison",
    "day_night_split", "use_case_mosaic",
]
_BLUEPRINT_PANEL_COUNTS = {
    "white_bundle": 0, "media_proof_split": 2, "connectivity_diagram": 1,
    "environmental_proof": 1, "coverage_diagram": 1,
    "speed_comparison": 1, "day_night_split": 2, "use_case_mosaic": 6,
}
# The studio now renders every planned card through the image model.  Keeping
# this set empty is important: review_render must compare generated main/in-box
# images with the product truth instead of treating them as untouched pixels.
_SOURCE_LOCKED_TYPES: set[str] = set()
_INTERNAL_PUBLIC_COPY_RE = re.compile(
    r"\b(approved copy|approved title|product facts?|claim(?:s)?|image should|"
    r"do not fabricate|source material|evidence|supported by|supports? (?:the|this))\b",
    re.I,
)
_HYPE_PROMPT_RE = re.compile(
    r"\b(neon|cyber|sci[- ]?fi|light trails?|floating (?:glass )?panels?|"
    r"hologra(?:m|phic)|futuristic platform|epic cinematic|hyperreal fantasy|"
    r"10,?000 commercial|national geographic style)\b",
    re.I,
)


def _ground_render_prompt(value: str) -> str:
    """Remove known prompt habits that systematically create synthetic ad art."""
    text = str(value or "").strip()
    replacements = {
        r"\bno neon(?: light trails?)?\b": "avoid stylized lighting",
        r"\bno floating (?:glass )?panels?\b": "avoid decorative overlays",
        r"\bneon light trails?\b": "subtle practical light",
        r"\bneon\b": "stylized colored lighting",
        r"\blight trails?\b": "natural motion blur",
        r"\bcyber(?:punk)?\b": "contemporary",
        r"\bsci[- ]?fi\b": "contemporary",
        r"\bfloating (?:glass )?panels?\b": "clean negative space",
        r"\bhologra(?:m|phic)\w*\b": "subtle graphic depth",
        r"\bfuturistic platform\b": "simple real surface",
        r"\bepic cinematic\b": "natural editorial",
        r"\bhyperreal fantasy\b": "realistic photography",
        r"\b(?:a )?\$?10,?000 commercial photoshoot\b": "restrained ecommerce photography",
        r"\bnational geographic style\b": "documentary photography",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text, flags=re.I)
    return re.sub(r"\s{2,}", " ", text).strip()


def _remove_legacy_textless_directions(value: str) -> str:
    """Remove obsolete 'generate a blank plate' instructions before compiling
    an exact-text final-artwork prompt.

    Existing projects and the deterministic fallback can contain these phrases.
    Keeping them beside the new copy contract gives the image model mutually
    exclusive instructions and is a major source of missing or garbled type.
    """
    text = str(value or "")
    patterns = (
        r"[^.\n]*(?:typography|copy|text)\s+(?:is|will be)\s+(?:added|typeset)\s+(?:later|separately)[^.\n]*[.\n]?",
        r"[^.\n]*(?:reserve|keep)\s+[^.\n]*(?:for later typography|for separately typeset copy)[^.\n]*[.\n]?",
        r"[^.\n]*render\s+no\s+(?:added\s+marketing\s+)?(?:copy|text|words|letters)[^.\n]*[.\n]?",
        r"[^.\n]*\bno\s+(?:added\s+)?(?:text|words|letters|marketing copy)\b[^.\n]*[.\n]?",
        r"[^.\n]*no\s+words,?\s+no\s+icons[^.\n]*[.\n]?",
    )
    for pattern in patterns:
        text = re.sub(pattern, " ", text, flags=re.I)
    return re.sub(r"\s{2,}", " ", text).strip()


def _public_text(value, limit: int) -> Optional[str]:
    """Keep only concise shopper-facing copy; internal chain-of-thought is never art."""
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text or _INTERNAL_PUBLIC_COPY_RE.search(text):
        return None
    return text[:limit].rstrip()


def _public_proof(value) -> Optional[str]:
    from app.services.listing_typography import public_proof
    return public_proof(str(value or "")) or None


def _clamped_float(value, default: float, low: float, high: float) -> float:
    try:
        return max(low, min(float(value), high))
    except (TypeError, ValueError):
        return default


def _readable_accent(value: str) -> str:
    text = str(value or "#67C95B").strip().lstrip("#")
    if len(text) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        return "#67C95B"
    rgb = [int(text[index:index + 2], 16) for index in (0, 2, 4)]
    peak = max(rgb)
    if peak < 150:
        factor = 185 / max(1, peak)
        rgb = [min(230, round(channel * factor)) for channel in rgb]
    return "#" + "".join(f"{channel:02X}" for channel in rgb)


_DEFAULT_SET_PALETTES = {
    "soft_goods": ["#F4F0E8", "#D8C7B5", "#8A6F56", "#4E5B4B", "#282622"],
    "spatial_gear": ["#E9E3D6", "#A7AD8C", "#667151", "#B97645", "#252A23"],
    "rigid_device": ["#EEF1F3", "#C8D0D6", "#657581", "#6E8D72", "#22292E"],
    "category_specific": ["#F2EFE9", "#D7D0C5", "#8A7967", "#66736B", "#292A28"],
}


def _normalise_set_style(style: dict, product_profile: dict) -> dict:
    """Create one concrete, reusable colour grammar for the whole set."""
    source = dict(style) if isinstance(style, dict) else {}
    behaviour = _clean_text(product_profile.get("object_behavior")) or "category_specific"
    requested = " ".join(str(source.get(key) or "") for key in ("palette", "direction"))
    profile_palette = product_profile.get("supporting_palette") or []
    requested += " " + " ".join(str(value) for value in profile_palette)
    colours: list[str] = []
    for value in re.findall(r"#[0-9a-fA-F]{6}\b", requested):
        upper = value.upper()
        if upper not in colours:
            colours.append(upper)
    defaults = _DEFAULT_SET_PALETTES.get(behaviour, _DEFAULT_SET_PALETTES["category_specific"])
    for value in defaults:
        if len(colours) >= 5:
            break
        if value not in colours:
            colours.append(value)
    colours = colours[:5]
    product_colours = [
        _clean_text(value) for value in (product_profile.get("product_colours") or [])
        if _clean_text(value)
    ][:5]
    source.update({
        "direction": _clean_text(source.get("direction")) or (
            f"Product-led {behaviour.replace('_', ' ')} commercial photography with realistic materials"
        ),
        "palette": (
            f"background {colours[0]}; surface {colours[1]}; supporting tone {colours[2]}; "
            f"brand accent {colours[3]}; deep neutral {colours[4]}"
        ),
        "palette_hex": colours,
        "product_colours": product_colours,
        "lighting": _clean_text(source.get("lighting")) or "soft directional key light with consistent neutral white balance",
        "materials": _clean_text(source.get("materials")) or "real category-appropriate materials with restrained supporting props",
        "type_system": _clean_text(source.get("type_system")) or "clean high-contrast ecommerce typography",
        "accent_color": _readable_accent(source.get("accent_color") or colours[3]),
    })
    return source


def _replace_prompt_section(prompt: str, name: str, content: str) -> str:
    """Replace a canonical prompt section so repeated saves never grow prompts."""
    pattern = rf"\s*\[{re.escape(name)}\].*?\[/{re.escape(name)}\]\s*"
    base = re.sub(pattern, " ", str(prompt or ""), flags=re.I | re.S).strip()
    return _ground_render_prompt(f"{base}\n[{name}] {content.strip()} [/{name}]")


def _set_colour_prompt(style: dict, shot_type: str) -> str:
    palette = str(style.get("palette") or "")
    product_colours = ", ".join(style.get("product_colours") or []) or "the exact colours visible in the reference"
    if shot_type == "white_main":
        application = (
            "Amazon main-image exception: use a pure #FFFFFF seamless background with neutral light and a natural soft shadow. "
            "Do not tint the white background or recolour the product."
        )
    else:
        application = (
            "Use these same colours naturally across the background, supporting surface, restrained props, ambient grade and integrated typography. "
            "Not every colour must appear in every frame; preserve the same white balance and visual family without making the set look templated."
        )
    return (
        f"One locked colour system for the entire image set: {palette}. Lighting: {style.get('lighting')}. "
        f"Material direction: {style.get('materials')}. Product colours are immutable ({product_colours}) and are not replaced by the set palette. "
        f"{application}"
    )


_BLUEPRINT_PANEL_DIRECTIONS = {
    "media_proof_split": ["primary subject in a crisp daylight scene", "secondary subject showing a different supported capture mode"],
    "connectivity_diagram": ["realistic category use environment with clear space for a product and phone diagram"],
    "environmental_proof": ["realistic adverse-weather category environment with a believable mounting surface"],
    "coverage_diagram": ["wide elevated environment with open foreground for field-of-view rays"],
    "speed_comparison": ["fast-moving category subject frozen sharply in a natural environment"],
    "day_night_split": ["category subject in low-light monochrome night conditions", "same category subject in clean daylight conditions"],
    "use_case_mosaic": [
        "primary wildlife observation scenario", "secondary professional outdoor scenario",
        "farm or property protection scenario", "camping safety scenario", "home or garden monitoring scenario",
        "plant growth or small-area monitoring scenario",
    ],
}


def _complete_panel_prompts(blueprint: str, prompts: list[str], scene: str) -> list[str]:
    count = _BLUEPRINT_PANEL_COUNTS.get(blueprint, 1)
    if count <= 0:
        return []
    clean = [_ground_render_prompt(value) for value in prompts if _ground_render_prompt(value)][:count]
    directions = _BLUEPRINT_PANEL_DIRECTIONS.get(blueprint) or ["realistic category-appropriate scene"]
    while len(clean) < count:
        direction = directions[min(len(clean), len(directions) - 1)]
        clean.append(
            f"Create only a realistic commercial photograph for this panel: {direction}. "
            f"Context: {scene or 'category-appropriate real environment'}. Natural light, believable perspective, "
            "real materials and restrained color. Leave deliberate negative space for later graphics. "
            "Do not show the sellable product, text, letters, numbers, logos, icons, UI, diagrams or watermarks."
        )
    return clean


def _infer_layout_blueprint(item: dict, index: int, shot_type: str) -> str:
    explicit = str(item.get("layout_blueprint") or "").strip()
    if explicit in _LAYOUT_BLUEPRINTS:
        return explicit
    facts = " ".join(str(item.get(key) or "") for key in (
        "headline", "supporting_text", "proof", "selling_point", "buyer_question", "evidence", "scene",
    )).lower()
    if shot_type in {"white_main", "in_box"}:
        return "white_bundle"
    if re.search(r"\b(wi[ -]?fi|bluetooth|app control|remote app)\b", facts) and not re.search(r"\b(no app|no wi[ -]?fi)\b", facts):
        return "connectivity_diagram"
    if re.search(r"\b(night vision|low[- ]?glow|infrared|\d+\s*nm|day (?:or|and) night)\b", facts):
        return "day_night_split"
    if re.search(r"\b(0\.\d+\s*s|trigger speed|burst|fast[- ]?moving|response time)\b", facts):
        return "speed_comparison"
    if re.search(r"\b(ip\d{2}|waterproof|weatherproof|rain|snow|dust|mud|temperature)\b", facts):
        return "environmental_proof"
    if re.search(r"\b(\d+\s*°(?!\s*[fc])|\d+\s*degree|detection angle|pir|field of view|coverage)\b", facts):
        return "coverage_diagram"
    if re.search(r"\b(\d+\s*(?:mp|k)|photo|video|resolution|image quality|detail)\b", facts):
        return "media_proof_split"
    if re.search(r"\b(use cases?|scenarios?|wildlife|hunting|farm|camping|home security|garden|monitoring)\b", facts):
        return "use_case_mosaic"
    return {
        "hero_feature": "media_proof_split", "comparison": "speed_comparison",
        "specs": "coverage_diagram", "lifestyle": "use_case_mosaic",
        "detail": "environmental_proof", "trust": "environmental_proof",
    }.get(shot_type, _DEFAULT_BLUEPRINT_ORDER[min(index, len(_DEFAULT_BLUEPRINT_ORDER) - 1)])


def _template_blueprint_is_supported(blueprint: str, image: dict, index: int) -> bool:
    if blueprint not in {"connectivity_diagram", "coverage_diagram", "speed_comparison", "day_night_split"}:
        return True
    facts_only = {**image, "layout_blueprint": ""}
    inferred = _infer_layout_blueprint(facts_only, index, str(image.get("shot_type") or "hero_feature"))
    return inferred == blueprint


def _strip_json(text: str):
    """Best-effort pull a JSON object out of an LLM reply (strip fences/prose)."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t[:4].lower() == "json":
            t = t[4:]
    i, j = t.find("{"), t.rfind("}")
    if i != -1 and j > i:
        t = t[i:j + 1]
    for cand in (t, text):
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None


def _parse_copy_result(value) -> Optional[dict]:
    """Parse generated listing copy and repair a narrow class of model JSON slips.

    Copy is a structured product surface. A single malformed bullet must not
    collapse the entire UI into a raw JSON dump.
    """
    if isinstance(value, dict):
        if value.get("titles") or value.get("bullets_a") or value.get("bullets_b"):
            return value
        value = value.get("raw")
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    candidates = [text]
    # Common provider slip: ["Bullet heading": body" instead of
    # "[Bullet heading]: body". Repair the affected line only.
    candidates.append(re.sub(
        r'(?m)^(\s*)\["([^"\n]+)":\s*([^"\n]*)"(,?)$',
        r'\1"[\2]: \3"\4', text,
    ))
    candidates.append(text.replace("“", '"').replace("”", '"'))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue
    return None


def _creative_plan_quality(images: list[dict], deliverable: str) -> dict:
    """Deterministic strategy QA.  This intentionally does not claim the rendered
    pixels are commercially safe; product fidelity remains a human delivery gate."""
    issues: list[dict] = []

    def add(code: str, message: str, severity: str = "warning") -> None:
        issues.append({"code": code, "message": message, "severity": severity})

    if not images:
        add("empty", "方案中没有可生成的分镜", "error")
    if deliverable == "gallery" and images:
        main = images[0]
        if main.get("shot_type") != "white_main" or main.get("text_on_image"):
            add("main_compliance", "首图必须是纯白底、无文字主图", "error")
        if not 5 <= len(images) <= 8:
            add("gallery_count", "商品套图建议保留 5–8 张", "warning")
    seen_points: set[str] = set()
    seen_concepts: set[str] = set()
    seen_cameras: set[str] = set()
    for idx, image in enumerate(images):
        point = str(image.get("selling_point") or "").strip().lower()
        if point and point in seen_points:
            add("duplicate_story", f"第 {idx + 1} 张与其他分镜重复表达同一卖点")
        seen_points.add(point)
        if image.get("asset_mode") == "generate":
            concept = re.sub(r"\s+", " ", str(image.get("visual_concept") or "").strip().lower())
            camera = re.sub(r"\s+", " ", str(image.get("camera_direction") or "").strip().lower())
            treatment = str(image.get("product_treatment") or "").strip()
            if not concept or not camera or not treatment:
                add("missing_art_direction", f"第 {idx + 1} 张缺少独立视觉概念、镜头或产品物理处理说明", "error")
            if concept and concept in seen_concepts:
                add("duplicate_visual_concept", f"第 {idx + 1} 张重复使用同一视觉概念", "error")
            if camera and camera in seen_cameras:
                add("duplicate_camera_direction", f"第 {idx + 1} 张重复使用同一镜头构图", "error")
            seen_concepts.add(concept)
            seen_cameras.add(camera)
        if _HYPE_PROMPT_RE.search(str(image.get("render_prompt") or "")):
            add("ai_aesthetic", f"第 {idx + 1} 张仍包含容易产生 AI 感的夸张场景词", "error")
        if len(str(image.get("headline") or "")) > 48:
            add("headline_length", f"第 {idx + 1} 张标题偏长，手机端可读性较差")
        for field in ("headline", "eyebrow", "supporting_text", "proof", "callout"):
            if _INTERNAL_PUBLIC_COPY_RE.search(str(image.get(field) or "")):
                add("internal_copy", f"第 {idx + 1} 张把内部审核说明写进了消费者文案", "error")
                break
        public_copy = [
            str(image.get(field) or "").strip()
            for field in ("eyebrow", "headline", "callout", "supporting_text", "proof")
            if str(image.get(field) or "").strip()
        ]
        if image.get("text_on_image"):
            prompt = str(image.get("render_prompt") or "")
            if not public_copy:
                add("missing_artwork_copy", f"第 {idx + 1} 张启用了图上文字但没有可生成的公开文案", "error")
            elif "[FINAL ARTWORK COPY]" not in prompt or any(value not in prompt for value in public_copy):
                add("copy_not_compiled", f"第 {idx + 1} 张公开文案尚未完整编译进最终生图提示词", "error")
        if image.get("proof") and not _public_proof(image.get("proof")):
            add("invalid_public_proof", f"第 {idx + 1} 张的证明数字不是简短、可公开的事实", "error")
        expected_size = "1464x600" if deliverable == "aplus" else "1600x1600"
        if image.get("size") != expected_size:
            add("canvas_mismatch", f"第 {idx + 1} 张画布必须统一为 {expected_size}", "error")
        if image.get("asset_mode") != "generate":
            add("direct_generation_required", f"第 {idx + 1} 张未使用统一的模型直出策略", "error")
        if not image.get("product_source_url"):
            add("product_pending", f"第 {idx + 1} 张需要上传或采集的产品真值图，禁止无参考生成", "error")
        if image.get("requires_source"):
            add("missing_evidence", f"第 {idx + 1} 张依赖未提供的真实证据，应换成有事实支撑的直出画面", "error")
        if idx and not image.get("evidence"):
            add("missing_claim_source", f"第 {idx + 1} 张缺少卖点依据")
        if image.get("final_url"):
            render_qa = image.get("render_qa") if isinstance(image.get("render_qa"), dict) else {}
            if not render_qa:
                add("render_unreviewed", f"第 {idx + 1} 张尚未通过成图质检", "error")
            elif render_qa.get("ready") is not True:
                add("render_failed", f"第 {idx + 1} 张成图质检未通过", "error")
    error_count = sum(i["severity"] == "error" for i in issues)
    score = max(0, 100 - error_count * 22 - (len(issues) - error_count) * 6)
    return {
        "score": score,
        "ready": not error_count and bool(images),
        "issues": issues,
        "note": "策略、公开文案、画布和已生成图片的质检结果；生成图还需通过产品一致性硬门槛并由人工终审。",
    }


def _normalize_shot_plan(plan: dict, target_count: int, deliverable: str = "gallery") -> dict:
    """Clamp/repair an LLM visual plan into the shape used by the studio."""
    deliverable = "aplus" if deliverable == "aplus" else "gallery"
    plan_style = plan.get("style") if isinstance(plan.get("style"), dict) else {}
    product_profile = plan.get("product_profile") if isinstance(plan.get("product_profile"), dict) else {}
    if not product_profile and _clean_text(plan.get("product_lock")):
        product_profile = _fallback_product_visual_profile(_clean_text(plan.get("product_lock")))
    profile_anchors = [
        _clean_text(value) for value in (product_profile.get("fidelity_anchors") or [])
        if _clean_text(value)
    ][:8]
    profile_opportunities = [
        _clean_text(value) for value in (product_profile.get("visual_opportunities") or []) if _clean_text(value)
    ]
    profile_interactions = [
        _clean_text(value) for value in (product_profile.get("natural_interactions") or []) if _clean_text(value)
    ]
    default_cameras = [
        "eye-level three-quarter hero with accurate scale",
        "close three-quarter feature view with selective depth of field",
        "honest human-scale use view with natural contact",
        "macro detail connected to the complete product context",
        "slightly elevated comparison view with clear spatial hierarchy",
        "orthographic configuration view with realistic perspective",
        "wide environmental view with deliberate negative space",
        "alternate-side trust close with restrained depth",
    ]
    plan_style = _normalise_set_style(plan_style, product_profile)
    creative_brief = _clean_text(plan.get("creative_brief"))
    artwork_language = _clean_text(plan.get("language")) or "en"
    raw = plan.get("images") if isinstance(plan, dict) else None
    accent_candidates = [
        str(item.get("accent_color")) for item in (raw or [])
        if isinstance(item, dict) and str(item.get("accent_color") or "").strip()
    ]
    set_accent_raw = str(plan_style.get("accent_color") or (
        max(set(accent_candidates), key=accent_candidates.count) if accent_candidates else "#4F8CFF"
    ))
    clean: list[dict] = []
    for i, it in enumerate(raw or []):
        if not isinstance(it, dict):
            continue
        rp = _ground_render_prompt(str(it.get("render_prompt") or ""))
        if not rp:
            continue
        callout = _public_text(it.get("callout"), 90)
        headline = _public_text(it.get("headline"), 48)
        supporting_text = _public_text(it.get("supporting_text"), 90)
        eyebrow = _public_text(it.get("eyebrow"), 24)
        proof = _public_proof(it.get("proof"))
        stype = str(it.get("shot_type") or "").strip().lower()
        stype = _LEGACY_SHOT_TYPE.get(stype, stype)
        if stype not in _SHOT_TYPES:
            order = _APLUS_TYPE_ORDER if deliverable == "aplus" else _DEFAULT_TYPE_ORDER
            stype = order[i] if i < len(order) else "hero_feature"
        # Direct-generation policy: every card is built around the verified
        # product reference. Result-only fantasy scenes are no longer planned.
        show_product = True
        text_zone = str(it.get("text_zone") or it.get("text_pos") or "top-left")
        if text_zone not in _TEXT_ZONES:
            text_zone = "top-left"
        layout_style = str(it.get("layout_style") or "editorial")
        if layout_style not in _LAYOUT_STYLES:
            layout_style = "editorial"
        roles = _APLUS_ROLES if deliverable == "aplus" else _DEFAULT_ROLES
        role = str(it.get("role") or roles[min(i, len(roles) - 1)])
        if deliverable == "gallery" and i == 0:
            role = "主图"
        text_on_image = bool(it.get(
            "text_on_image", bool(callout or headline or supporting_text or eyebrow or proof),
        )) and not (deliverable == "gallery" and i == 0)
        opportunity = profile_opportunities[i % len(profile_opportunities)] if profile_opportunities else f"product-specific {stype}"
        interaction = profile_interactions[i % len(profile_interactions)] if profile_interactions else "natural real-world use"
        visual_concept = _clean_text(it.get("visual_concept")) or f"{opportunity} for {role}"
        camera_direction = _clean_text(it.get("camera_direction")) or default_cameras[i % len(default_cameras)]
        product_treatment = _clean_text(it.get("product_treatment")) or (
            f"{_clean_text(product_profile.get('form_and_scale')) or 'accurate real-world scale and orientation'}; {interaction}"
        )
        asset_mode = "generate"
        anchor_text = ", ".join(profile_anchors) or "silhouette, proportions, colour, material, visible construction, markings and included quantity"
        behaviour = _clean_text(product_profile.get("object_behavior")) or "category-specific physical behaviour"
        treatment = product_treatment
        product_lock = _clean_text(plan.get("product_lock"))
        rp = _replace_prompt_section(
            rp,
            "PRODUCT IDENTITY LOCK",
            f"REFERENCE IMAGE 1 is the only immutable product truth. {product_lock + '. ' if product_lock else ''}"
            f"Preserve exactly: {anchor_text}. Physical behaviour: {behaviour}. Product treatment: "
            f"{treatment or 'natural real-world orientation, scale and contact'}. Change only the environment, camera, "
            "composition, lighting, supporting design and explicitly requested artwork copy. Do not redesign, recolour, "
            "relabel, simplify, crop away, add or remove any product part, "
            "opening, control, accessory or unit. Preserve existing logos, labels and printed product markings exactly where visible.",
        )
        layout_direction = (
            f"Build a deliberate {layout_style} hierarchy with the primary copy group in the {text_zone} area and keep "
            "that area visually calm enough for immediate reading."
            if text_on_image else
            "Use the full canvas for a clean product-led composition with no reserved caption or empty text plate."
        )
        rp = _replace_prompt_section(
            rp,
            "SHOT DESIGN",
            f"Role: {role}; shot type: {stype}; product-specific visual concept: {visual_concept}. "
            f"Camera and composition: {camera_direction}. Scene: {_clean_text(it.get('scene')) or opportunity}. "
            f"Physical product interaction: {product_treatment}. {layout_direction}",
        )
        rp = _replace_prompt_section(rp, "SET COLOR SYSTEM", _set_colour_prompt(plan_style, stype))
        rp = _replace_prompt_section(
            rp,
            "USER CREATIVE DIRECTION",
            (
                f"Highest-priority creative requirement after product identity, factual accuracy and marketplace rules: "
                f"{creative_brief}. Follow it for audience, mood, scene, emphasis, exclusions and design character. "
                if creative_brief else
                "No additional manual creative requirement was supplied; follow the product-specific set direction. "
            ) + f"The requested language for added artwork copy is {artwork_language}.",
        )
        if text_on_image:
            rp = _remove_legacy_textless_directions(rp)
            exact_copy = {
                key: value for key, value in (
                    ("eyebrow", eyebrow), ("headline", headline), ("callout", callout),
                    ("supporting_text", supporting_text), ("proof", proof),
                ) if value
            }
            copy_contract = json.dumps(exact_copy, ensure_ascii=False)
            rp = _replace_prompt_section(
                rp,
                "FINAL ARTWORK COPY",
                f"This is final pixel artwork, not a blank background. Render every string in this JSON exactly once and "
                f"character-for-character: {copy_contract}. Do not translate, paraphrase, abbreviate, add, omit or repeat any "
                f"character. Use {plan_style.get('type_system')} with clean commercial kerning and a clear hierarchy: eyebrow "
                f"small, headline dominant, supporting text secondary, proof prominent only when present. Place the complete "
                f"copy group in the {text_zone} zone using the {layout_style} layout language. Keep all type inside an 8% safe "
                "margin, high contrast, unobstructed, correctly spelled and readable at mobile thumbnail size. Integrate the "
                "typography into the composition as intentional final design, never as a pasted caption or placeholder.",
            )
        else:
            rp = _replace_prompt_section(
                rp,
                "FINAL ARTWORK COPY",
                "This artwork intentionally contains no added marketing copy. Do not render headlines, captions, letters, "
                "numbers, badges, icons, diagrams, app UI or watermarks.",
            )
        rp = _replace_prompt_section(
            rp,
            "OUTPUT SAFETY",
            "Do not invent additional copy, claims, certifications, logos, labels, icons, badges, diagrams, app UI or "
            "watermarks. The exact public copy in FINAL ARTWORK COPY is the only added text allowed. Product labels and "
            "markings already visible in the reference are part of the immutable product and must remain unchanged.",
        )
        background_prompt = ""
        expected_size = "1464x600" if deliverable == "aplus" else "1600x1600"
        layout_blueprint = ""
        panel_prompts: list[str] = []
        graphic_labels = [
            _public_text(value, 34) for value in (it.get("graphic_labels") or [])
            if _public_text(value, 34)
        ][:6]
        if not graphic_labels:
            graphic_labels = [value for value in (
                proof,
                _public_text(supporting_text, 34),
            ) if value][:6]
        accent_color = set_accent_raw
        fact_text = " ".join(str(it.get(key) or "") for key in ("scene", "headline", "evidence", "selling_point")).lower()
        if accent_color.upper() == "#4F8CFF" and re.search(r"\b(outdoor|forest|wildlife|hunting|garden|farm|nature)\b", fact_text):
            accent_color = "#67C95B"
        accent_color = _readable_accent(accent_color)
        versions = [v for v in (it.get("versions") or []) if isinstance(v, dict)][-8:]
        base_url = str(it.get("base_url") or "")
        final_url = str(it.get("final_url") or "")
        render_qa = it.get("render_qa") if isinstance(it.get("render_qa"), dict) else None
        human_reviewed = bool(it.get("human_reviewed", False)) and bool((render_qa or {}).get("ready"))
        clean.append({
            "slot": str(it.get("slot") or (("main" if i == 0 else f"sub{len(clean)}") if deliverable == "gallery" else f"aplus_{len(clean) + 1}")),
            "role": role,
            "shot_type": stype,
            "show_product": show_product,
            "angle": str(it.get("angle") or ""),
            "scene": str(it.get("scene") or ""),
            "selling_point": (str(it.get("selling_point")).strip() or None) if it.get("selling_point") else None,
            "buyer_question": str(it.get("buyer_question") or ""),
            "evidence": str(it.get("evidence") or ""),
            "headline": headline,
            "callout": callout,
            "supporting_text": supporting_text,
            "eyebrow": eyebrow,
            "proof": proof,
            "text_on_image": text_on_image,
            "text_pos": text_zone,  # legacy consumer alias
            "text_zone": text_zone,
            "layout_style": layout_style,
            "layout_blueprint": layout_blueprint,
            "panel_prompts": panel_prompts,
            "graphic_labels": graphic_labels,
            "theme": str(it.get("theme") or "auto"),
            "accent_color": accent_color,
            "composition": str(it.get("composition") or ""),
            "visual_concept": visual_concept,
            "camera_direction": camera_direction,
            "product_treatment": product_treatment,
            "asset_mode": asset_mode,
            "manual_template": False,
            "requires_source": False,
            "source_requirement": "使用上传图优先的产品真值参考；仅允许改变场景、镜头、构图、光线、辅助设计和指定图上文案",
            "source_url": "",
            "product_source_url": str(it.get("product_source_url") or ""),
            "template_url": "",
            "template_index": 0,
            "template_analysis": None,
            "background_prompt": background_prompt,
            "product_scale": _clamped_float(it.get("product_scale"), .52, .24, .72),
            "acceptance_criteria": [str(v) for v in (it.get("acceptance_criteria") or []) if str(v).strip()][:6],
            "size": expected_size,
            "render_prompt": rp,
            "base_url": base_url,
            "final_url": final_url,
            "versions": versions,
            "render_qa": render_qa,
            "auto_retry_count": 1 if it.get("auto_retry_count") else 0,
            "last_retry_guidance": [
                str(value) for value in (it.get("last_retry_guidance") or []) if str(value).strip()
            ][:6],
            "human_reviewed": human_reviewed,
        })
    if clean and deliverable == "gallery":  # 第一张永远是纯白底无字主图
        clean[0].update(slot="main", role="主图", shot_type="white_main", show_product=True,
                        text_on_image=False, callout=None, headline=None, supporting_text=None,
                        eyebrow=None, proof=None, text_zone="top-left", text_pos="top-left",
                        layout_style="minimal", layout_blueprint="",
                        panel_prompts=[], graphic_labels=[], requires_source=False, asset_mode="generate",
                        source_requirement="以上传或采集主图为不可变产品真值，模型直接生成合规纯白底主图")
    clean = clean[:target_count] if target_count and target_count > 0 else clean[:8]
    normalized = {
        "deliverable": deliverable,
        "planning_mode": "adaptive_direct_text",
        "style": plan_style,
        "product_profile": product_profile,
        "product_lock": str(plan.get("product_lock") or "").strip(),
        "story": str(plan.get("story") or "").strip(),
        "creative_brief": creative_brief,
        "language": artwork_language,
        "template_mode": False,
        "product_source_url": str(plan.get("product_source_url") or ""),
        "template_images": [],
        "template_story": [],
        "images": clean,
        "set_qa": plan.get("set_qa") if isinstance(plan.get("set_qa"), dict) else None,
    }
    if normalized["style"] is not None:
        normalized["style"]["accent_color"] = clean[0]["accent_color"] if clean else _readable_accent(set_accent_raw)
    normalized["quality"] = _creative_plan_quality(clean, deliverable)
    return normalized


def _white_metrics_ready(metrics: dict, *, allow_legacy_bundle: bool = False) -> bool:
    """Return whether measured pixels describe a usable white ecommerce source.

    A normal product photo leaves a mostly-white border.  Large bundles are a
    legitimate second shape: the items can touch one canvas edge and occupy most
    of the frame while the white background is still one continuous region that
    spans the other three sides.  Keeping these as separate acceptance paths
    avoids lowering the normal white-border threshold for bright lifestyle art.
    """
    border = float(metrics.get("border_white") or 0)
    overall = float(metrics.get("overall_white") or 0)
    connected = float(metrics.get("edge_connected_white") or 0)
    white_sides = int(metrics.get("white_sides") or 0)
    classic_white_main = border >= .62 and overall >= .30
    connected_bundle = overall >= .34 and connected >= .30 and white_sides >= 3
    # Reports written before edge-connectivity was introduced cannot be
    # re-scored without downloading the image again.  Only the first scraped
    # gallery image may use this narrow migration path; callers control that
    # condition with allow_legacy_bundle.
    legacy_bundle = (
        allow_legacy_bundle and "edge_connected_white" not in metrics
        and border >= .30 and overall >= .35
    )
    return classic_white_main or connected_bundle or legacy_bundle


def _white_background_score(raw: bytes) -> dict:
    """Identify a white-background ecommerce source, including dense bundles."""
    from PIL import Image
    try:
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        image.thumbnail((240, 240))
    except Exception:
        return {"ready": False, "score": 0, "border_white": 0, "overall_white": 0}
    width, height = image.size
    if width < 20 or height < 20:
        return {"ready": False, "score": 0, "border_white": 0, "overall_white": 0}
    pixels = image.load()
    margin_x, margin_y = max(2, width // 12), max(2, height // 12)

    def is_white(pixel) -> bool:
        return min(pixel) >= 238 and max(pixel) - min(pixel) <= 16

    total = white = border_total = border_white = 0
    white_mask = bytearray(width * height)
    for y in range(height):
        for x in range(width):
            value = pixels[x, y]
            pixel_white = is_white(value)
            white_mask[y * width + x] = int(pixel_white)
            total += 1
            white += int(pixel_white)
            if x < margin_x or x >= width - margin_x or y < margin_y or y >= height - margin_y:
                border_total += 1
                border_white += int(pixel_white)
    overall_ratio = white / max(1, total)
    border_ratio = border_white / max(1, border_total)

    # Count the strict-white region connected to the outside of the canvas.
    # This distinguishes a genuine white sweep surrounding a dense bundle from
    # disconnected pale labels, screens, clouds or highlights inside a scene.
    seen = bytearray(total)
    stack: list[int] = []

    def seed(index: int) -> None:
        if white_mask[index] and not seen[index]:
            seen[index] = 1
            stack.append(index)

    for x in range(width):
        seed(x)
        seed((height - 1) * width + x)
    for y in range(height):
        seed(y * width)
        seed(y * width + width - 1)
    connected_white = 0
    while stack:
        index = stack.pop()
        connected_white += 1
        x = index % width
        for neighbor in (
            index - width if index >= width else -1,
            index + width if index < total - width else -1,
            index - 1 if x else -1,
            index + 1 if x < width - 1 else -1,
        ):
            if neighbor >= 0 and white_mask[neighbor] and not seen[neighbor]:
                seen[neighbor] = 1
                stack.append(neighbor)
    connected_ratio = connected_white / max(1, total)
    side_ratios = (
        sum(white_mask[x] for x in range(width)) / width,
        sum(white_mask[(height - 1) * width + x] for x in range(width)) / width,
        sum(white_mask[y * width] for y in range(height)) / height,
        sum(white_mask[y * width + width - 1] for y in range(height)) / height,
    )
    white_sides = sum(ratio >= .55 for ratio in side_ratios)
    legacy_score = (border_ratio * .68 + overall_ratio * .32) * 100
    connected_score = (connected_ratio * .55 + (white_sides / 4) * .45) * 100
    metrics = {
        "score": round(max(legacy_score, connected_score)),
        "border_white": round(border_ratio, 3),
        "overall_white": round(overall_ratio, 3),
        "edge_connected_white": round(connected_ratio, 3),
        "white_sides": white_sides,
        "side_white": [round(ratio, 3) for ratio in side_ratios],
    }
    return {
        "ready": _white_metrics_ready(metrics),
        **metrics,
    }


def _cached_white_product_source(scrape_data: dict) -> str:
    selected = str(scrape_data.get("white_product_source") or "").strip()
    if selected:
        return selected
    check = scrape_data.get("white_product_source_check")
    candidates = check.get("candidates") if isinstance(check, dict) else []
    valid: list[tuple[int, dict]] = []
    for index, item in enumerate(candidates or []):
        if not isinstance(item, dict):
            continue
        allow_legacy = index == 0 and item.get("kind") == "scraped"
        if _white_metrics_ready(item, allow_legacy_bundle=allow_legacy):
            valid.append((index, item))
    # Uploaded product truth wins.  Otherwise preserve Amazon gallery order:
    # the first qualifying image is the main source, not a later infographic
    # that happens to contain more white pixels.
    valid.sort(key=lambda pair: (pair[1].get("kind") != "uploaded", pair[0]))
    return str(valid[0][1].get("url") or "") if valid else ""


async def _detect_white_product_source(project_id: str, scrape_data: dict) -> tuple[str, list[dict]]:
    candidates: list[tuple[str, str]] = []
    for path_str in scrape_data.get("uploaded_images", []) or []:
        path_obj = Path(path_str)
        if path_obj.exists():
            candidates.append((f"/api/listing/images/{project_id}/{path_obj.name}", "uploaded"))
    for url in scrape_data.get("reference_images") or scrape_data.get("imageUrls") or []:
        if str(url).strip():
            candidates.append((str(url), "scraped"))

    async def inspect(url: str, kind: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                raw = await _fetch_image_bytes(client, url)
            metrics = _white_background_score(raw)
        except Exception:
            metrics = {"ready": False, "score": 0, "border_white": 0, "overall_white": 0}
        return {"url": url, "kind": kind, **metrics}

    report = await asyncio.gather(*(inspect(url, kind) for url, kind in candidates)) if candidates else []
    valid = [(index, item) for index, item in enumerate(report) if item.get("ready")]
    valid.sort(key=lambda pair: (pair[1].get("kind") != "uploaded", pair[0]))
    return (str(valid[0][1]["url"]) if valid else ""), report


def _auto_product_source(project_id: str, scrape_data: dict) -> str:
    """Choose the one source that passed white-background verification.

    Uploaded files are not automatically trusted: a lifestyle or infographic
    upload is useful evidence but is not the clean product identity anchor this
    workflow requires. upload_product_image stores a passing upload as the
    selected white_product_source, so deliberate verified uploads still win.
    """
    return _cached_white_product_source(scrape_data)


def _bind_reference_templates(plan: dict, project_id: str, scrape_data: dict,
                              deliverable: str) -> dict:
    """Bind one uploaded-first product truth to every directly generated card."""
    product_source = _auto_product_source(project_id, scrape_data)
    images = plan.get("images") if isinstance(plan.get("images"), list) else []
    plan["product_source_url"] = product_source
    plan["template_images"] = []
    plan["template_story"] = []
    plan["template_mode"] = False

    for image in images:
        if not isinstance(image, dict):
            continue
        previous_product = str(image.get("product_source_url") or "")

        def invalidate_render() -> None:
            if image.get("final_url"):
                history = list(image.get("versions") or [])
                history.append({
                    "url": image.get("final_url"), "base_url": image.get("base_url") or "",
                    "render_qa": image.get("render_qa"), "created_at": "invalidated-by-source-migration",
                })
                image["versions"] = history[-8:]
            image["base_url"] = ""
            image["final_url"] = ""
            image["render_qa"] = None
            image["human_reviewed"] = False

        # One production path only: whole-image generation from the immutable
        # product truth. Existing renders survive a strategy migration; they are
        # invalidated only when an already-bound truth source actually changes.
        image["asset_mode"] = "generate"
        image["show_product"] = True
        image["requires_source"] = False
        image["source_url"] = ""
        image["source_requirement"] = "以上传图优先的产品真值为高保真参考；仅改变场景、镜头、构图、光线、辅助设计和指定图上文案"
        image["product_source_url"] = product_source
        image["template_index"] = 0
        image["template_url"] = ""
        image["template_analysis"] = None
        image["layout_blueprint"] = ""
        image["panel_prompts"] = []
        image["manual_template"] = False
        if image.get("final_url") and previous_product and previous_product != product_source:
            invalidate_render()

    plan["quality"] = _creative_plan_quality(images, deliverable)
    return plan


def _shot_plan_fallback(row, scrape_data: dict, analysis_data: dict, target_count: int,
                        color_scheme: str, deliverable: str = "gallery",
                        product_profile: Optional[dict] = None) -> dict:
    """LLM JSON unparsable → build a usable structured plan from the deterministic
    slot helpers so the user still gets a set (never a hard error)."""
    deliverable = "aplus" if deliverable == "aplus" else "gallery"
    n = target_count if target_count and target_count > 0 else (5 if deliverable == "aplus" else 7)
    slot_ids = (["main"] + [f"sub{i}" for i in range(1, n)] if deliverable == "gallery"
                else [f"aplus_{i + 1}" for i in range(n)])
    fallback_size = "1464x600" if deliverable == "aplus" else "1600x1600"
    details = [{"id": s, "label": s, "size": fallback_size} for s in slot_ids]
    try:
        prompts = _fallback_prompts_for_slots(row, scrape_data, analysis_data, details, color_scheme=color_scheme)
    except Exception:
        prompts = {}
    bullets = [ln[2:] for ln in _approved_copy(row).splitlines() if ln.startswith("- ")][:n]
    profile = product_profile if isinstance(product_profile, dict) and product_profile else _fallback_product_visual_profile(
        _build_product_context(row, scrape_data, analysis_data)
    )
    opportunities = [str(value) for value in (profile.get("visual_opportunities") or []) if str(value).strip()]
    scenes = [str(value) for value in (profile.get("scene_families") or []) if str(value).strip()]
    interactions = [str(value) for value in (profile.get("natural_interactions") or []) if str(value).strip()]
    anchors = [str(value) for value in (profile.get("fidelity_anchors") or []) if str(value).strip()]
    avoid = [str(value) for value in (profile.get("avoid") or []) if str(value).strip()]
    camera_directions = [
        "eye-level environmental hero with a clear foreground-to-background path",
        "close tactile three-quarter view with selective depth of field",
        "honest human-scale use view with natural contact and posture",
        "overhead or orthographic configuration view only when physically useful",
        "quiet editorial wide shot with asymmetrical negative space",
        "macro construction detail anchored to the complete product context",
        "alternate-side use view that does not repeat the hero angle",
    ]
    imgs = []
    for i, s in enumerate(slot_ids):
        sp = bullets[i - 1] if i > 0 and i - 1 < len(bullets) else None
        order = _APLUS_TYPE_ORDER if deliverable == "aplus" else _DEFAULT_TYPE_ORDER
        stype = order[i] if i < len(order) else "hero_feature"
        has_copy = bool(sp) and (deliverable == "aplus" or i > 0)
        role = (_APLUS_ROLES if deliverable == "aplus" else _DEFAULT_ROLES)[
            min(i, len(_APLUS_ROLES if deliverable == "aplus" else _DEFAULT_ROLES) - 1)
        ]
        headline = " ".join(sp.split()[:6]) if has_copy else None
        callout = " ".join(sp.split()[6:14]) if has_copy and len(sp.split()) > 6 else None
        base_prompt = str(prompts.get(s) or (
            "Realistic ecommerce product photograph in a physically plausible everyday setting, "
            "natural materials, restrained color, soft directional light, accurate scale and contact shadow, "
            "a deliberate commercial layout with clear information hierarchy, no stylized effects or levitating objects."
        ))
        opportunity = opportunities[i % len(opportunities)] if opportunities else "category-specific primary use"
        visual_concept = f"{opportunity} for {role}"
        scene = scenes[i % len(scenes)] if scenes else "a real category-appropriate environment"
        interaction = interactions[i % len(interactions)] if interactions else "normal real-world use"
        camera = camera_directions[i % len(camera_directions)]
        identity = ", ".join(anchors[:6]) or "silhouette, proportions, colour, material and visible construction"
        avoid_text = ", ".join(avoid[:4]) or "invented features, impossible physics and decorative AI effects"
        rp = _ground_render_prompt(
            f"{base_prompt} Product family: {profile.get('category_family') or 'consumer product'}; physical behaviour: "
            f"{profile.get('object_behavior') or 'category-specific'}. Visual concept: {opportunity}. Scene: {scene}. "
            f"Natural interaction: {interaction}. Camera: {camera}. Reproduce the reference product without changing "
            f"{identity}. Avoid {avoid_text}. Leave enough visual calm for an integrated, readable final design."
        )
        imgs.append({
            "slot": s, "role": role,
            "shot_type": stype, "angle": "", "scene": "", "selling_point": sp,
            "buyer_question": "", "evidence": sp or "",
            "headline": headline, "callout": callout, "supporting_text": None,
            "text_on_image": bool(headline or callout), "text_zone": "top-left",
            "layout_style": "editorial", "composition": camera,
            "visual_concept": visual_concept, "camera_direction": camera,
            "product_treatment": f"{profile.get('form_and_scale') or 'Natural real-world scale'}; {interaction}",
            "asset_mode": "generate", "requires_source": False,
            "acceptance_criteria": ["产品外观与参考图一致", "尺度和阴影自然", "手机端文字可读"],
            "size": "1464x600" if deliverable == "aplus" else "1600x1600",
            "render_prompt": rp,
        })
    return _normalize_shot_plan({
        "images": imgs,
        "style": {"palette": color_scheme} if color_scheme else {},
        "product_lock": analysis_data.get("product_lock", ""),
        "product_profile": profile, "planning_mode": "adaptive_direct_text",
    }, n, deliverable)


def _persist_shot_plan(project_id: str, plan: dict, deliverable: str = "gallery") -> None:
    try:
        conn = _db()
        row = conn.execute("SELECT creative_sets FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
        sets = {}
        if row and row["creative_sets"]:
            try:
                sets = json.loads(row["creative_sets"])
            except Exception:
                sets = {}
        deliverable = "aplus" if deliverable == "aplus" else "gallery"
        sets[deliverable] = plan
        if deliverable == "gallery":
            conn.execute(
                "UPDATE listing_projects SET creative_sets=?, shot_plan=?, updated_at=? WHERE id=?",
                (json.dumps(sets, ensure_ascii=False), json.dumps(plan, ensure_ascii=False), time.time(), project_id),
            )
        else:
            conn.execute(
                "UPDATE listing_projects SET creative_sets=?, updated_at=? WHERE id=?",
                (json.dumps(sets, ensure_ascii=False), time.time(), project_id),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass


@router.post("/projects/{project_id}/plan-image-set")
async def plan_image_set(project_id: str, body: PlanImageSetReq, _user: str = Depends(require_user)):
    """Plan either a gallery or A+ set through the same evidence-led engine."""
    conn = _db()
    row = conn.execute("SELECT * FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)
    scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    analysis_data = json.loads(row["analysis_data"]) if row["analysis_data"] else {}
    product_context = _build_product_context(row, scrape_data, analysis_data)
    ref_images = scrape_data.get("reference_images", []) or scrape_data.get("imageUrls", [])
    ref_text = "\n".join(ref_images[:3]) if ref_images else "(no reference images)"
    try:
        white_source, white_report = await asyncio.wait_for(
            _detect_white_product_source(project_id, scrape_data), timeout=120,
        )
    except Exception:
        white_source, white_report = "", []
    scrape_data["white_product_source"] = white_source
    scrape_data["white_product_source_check"] = {
        "ready": bool(white_source),
        "selected": white_source,
        "candidates": white_report,
    }
    try:
        update_conn = _db()
        update_conn.execute(
            "UPDATE listing_projects SET scrape_data=?, updated_at=? WHERE id=?",
            (json.dumps(scrape_data, ensure_ascii=False), time.time(), project_id),
        )
        update_conn.commit()
        update_conn.close()
    except Exception:
        pass
    try:
        product_profile = await asyncio.wait_for(
            _analyze_product_visual_identity(scrape_data, product_context, white_source), timeout=150,
        )
    except Exception:
        product_profile = _fallback_product_visual_profile(product_context)
    product_profile_text = json.dumps(product_profile, ensure_ascii=False, indent=2)
    uploaded_count = len(scrape_data.get("uploaded_images", []) or [])
    img_sp = analysis_data.get("image_insights", "")
    approved = _approved_copy(row)
    color_directive = _color_directive(body.color_scheme, analysis_data)
    deliverable = "aplus" if body.deliverable == "aplus" else "gallery"
    max_count = 6 if deliverable == "aplus" else 8
    n = max(0, min(int(body.target_count or 0), max_count))
    count_rule = (
        f"Produce EXACTLY {n} modules." if n else
        ("Produce 4–6 A+ modules." if deliverable == "aplus" else "Choose 5–8 images; default to 7 when the facts support it.")
    )
    deliverable_rules = (
        "A+ modules use a wide 1464x600 canvas. Build one brand story across a banner, primary benefit, "
        "usage/education, detail or comparison, and trust close. Do not create a white Amazon main image."
        if deliverable == "aplus" else
        "The first image is the Amazon white main image. The remaining images form a mobile-first sales story."
    )

    prompt = f"""You are a senior ecommerce creative director planning a commercially usable Amazon {deliverable} set. {count_rule}

This is a production brief, not a prompt-writing showcase. Every decision must be restrained, physically plausible,
supported by product facts, and useful to a shopper. {deliverable_rules}

## PRODUCT INFO
{product_context}

## APPROVED LISTING COPY (the source of truth for exact on-image text)
{approved or "(none — derive concise callouts from the bullets/selling points above)"}

## REFERENCE IMAGES
{ref_text}
The verified white-background image is the only product-identity truth. Other collected images are evidence for visible
features and normal use only. Do not copy their composition, grid, camera angle, background, typography or gallery order.
Design a new art direction from the current product's physical behaviour and buyer decisions.
Uploaded product assets available: {uploaded_count}. Scraped ASIN references available: {len(ref_images)}.

## PRODUCT VISUAL IDENTITY — STAGE 1 ANALYSIS
{product_profile_text}
Treat this profile as a physical design constraint. The category, object behaviour, material response, normal interaction,
scale cues and fidelity anchors must drive every shot. A flexible textile must fold and compress naturally; an occupiable
shelter must have credible footprint and interior scale; a precision device must preserve controls, openings and geometry.
Do not reduce unrelated categories to the same product-on-pedestal composition.

## VISUAL ANALYSIS (selling points / style / scenes from scraped + uploaded images)
{img_sp or "(not available)"}

## STORY AND SHOT TYPES
Use different jobs rather than repeating the product in the same pose:
- white_main: pure #FFFFFF, complete purchased set, product fills 80–90%, no text (gallery image 1 only)
- hero_feature: product in a restrained studio or plausible context, one primary benefit
- lifestyle: product used naturally at correct scale; believable hand/body/environment relationships
- detail: macro or close crop of a real visible material, control, interface, or construction detail
- comparison: only when the supplied facts support a fair comparison; never fabricate a test result
- specs: size, compatibility, capacity, or configuration using supplied facts
- in_box: exact included items, no invented accessories
- trust: care, material, certification, warranty, or brand close only when supported
- aplus_banner: wide brand opening for A+ only

## DYNAMIC ART DIRECTION — STAGE 2
- Invent a distinct visual concept for every image from the product profile and that image's buyer question.
- Vary camera height, lens feel, crop, subject scale, depth, lighting logic and product interaction across the set.
- Composition must follow the product: drape/fold/stack soft goods, show credible occupied scale and ground contact for
  spatial gear, and use precise close views or operational handling for rigid devices.
- Use one coherent brand world across the set without repeating one layout. The set should feel designed, not templated.
- Design the typography and image as one final composition. Use clear type hierarchy, intentional alignment and enough
  visual calm for legibility; avoid generic floating cards unless the requested design specifically needs one.
- The model may integrate the exact reference product into a realistic scene. It may not redesign, relabel or simplify it.

## USER CREATIVE DIRECTION — HIGHEST PRIORITY AFTER FACTS AND PRODUCT IDENTITY
- Tone requested by the user: {body.visual_tone}.
- Manual requirement: {body.brief or "none"}.
- Follow the manual requirement for style, audience, mood, scenes, emphasis and exclusions. It may not override the exact
  product reference, supplied facts, Amazon main-image rules or claim safety.

## ART DIRECTION
- Prefer a real studio, home, workplace, outdoors, or other category-appropriate location with ordinary materials.
- Use believable perspective, product scale, contact shadow, reflection, depth of field, and time-of-day lighting.
- Derive ONE product-specific set palette from the reference product's exact colours, material, category and positioning.
  style.palette must define five concrete #RRGGBB colours with roles: background, surface, supporting tone, brand accent,
  and deep neutral. Reuse that same colour grammar, white balance and lighting family in every image.
- Apply the shared palette naturally to backgrounds, supporting surfaces, restrained props, ambient grade and typography.
  Do not recolour the product and do not force all five colours into every frame. Gallery white_main keeps #FFFFFF.
- Never use neon light trails, sci-fi spaces, holograms, floating glass panels, fantasy panoramas, impossible scene mashups,
  levitating products, fake interfaces, or generic "cinematic luxury" decoration.
- Product appearance, labels, ports, controls, proportions, color, texture, logo, accessories, and quantities must not change.

## COPY AND EVIDENCE
- Each image answers one buyer_question and cites an evidence string from the approved copy/product facts.
- headline is 2–5 words; supporting_text is optional and no longer than 9 words. Do not paste a whole bullet.
- evidence and source_requirement are INTERNAL production notes and must never appear on the artwork.
- proof is optional PUBLIC copy and may only be a short numeric fact such as "8K/30fps", "120MP" or "2 Batteries".
  Never put phrases such as "approved copy supports", "product facts", "image should" or claim-review explanations in proof.
- For every non-main image with text_on_image=true, render_prompt must contain the final exact strings and instruct the
  image model to draw them directly into the final pixels. Text is not added later by code.
- Use the requested artwork language: {body.language}. Keep every public string concise so the image model can spell it reliably.
- If a claim would require a sample, before/after, lab test, certificate, screenshot or measured proof that is not supplied,
  omit that claim and design a different supported product-led image. AI must not generate fake evidence.
- text_zone must be deliberately low-detail negative space: top-left/top-center/top-right/center-left/center-right/
  bottom-left/bottom-center/bottom-right.

## OUTPUT — valid JSON only
{{"deliverable":"{deliverable}",
 "style":{{"direction":"product-specific art direction","palette":"background #RRGGBB; surface #RRGGBB; supporting tone #RRGGBB; brand accent #RRGGBB; deep neutral #RRGGBB","lighting":"one shared lighting family","materials":"category-specific real materials","type_system":"...","accent_color":"#RRGGBB"}},
 "story":"one sentence describing the set's sales narrative",
 "product_lock":"strict appearance description and explicit things that must not change",
 "images":[
   {{"slot":"...","role":"...","shot_type":"...","buyer_question":"...","selling_point":"...",
    "evidence":"exact supporting fact or approved-copy phrase","headline":"...","eyebrow":"...",
    "supporting_text":"...","proof":"...","text_on_image":true,"text_zone":"top-left",
    "layout_style":"editorial|minimal|split|proof|grid","theme":"auto","accent_color":"#RRGGBB",
    "show_product":true,"angle":"...","scene":"...","composition":"...","asset_mode":"generate",
    "visual_concept":"one category-specific art idea","camera_direction":"lens, height, crop, depth and subject scale",
    "product_treatment":"how the unchanged product contacts, folds, mounts, opens, is occupied or is handled",
    "requires_source":false,"source_requirement":"","acceptance_criteria":["...","..."],
    "size":"{'1464x600' if deliverable == 'aplus' else '1600x1600'}",
    "render_prompt":"180–280 words: final-pixel instruction containing exact product identity, category physics, scene, camera, light, shared design system, exact public copy strings, type hierarchy and placement"}}
 ]}}

## HARD RULES
- Every module uses asset_mode="generate", show_product=true and requires_source=false. The model directly generates the
  whole image with the uploaded-first product truth attached at high input fidelity. Do not request source, composite,
  template or blueprint modes.
- Do not invent claims, certifications, dimensions, accessories, UI, screenshots, or results.
- A generated image is not proof. Omit evidence-dependent modules that cannot be supported by supplied product facts.
- Gallery white_main is also generated directly: pure #FFFFFF, complete product/set, no added text, with the same immutable
  reference-product identity. in_box may only show quantities and accessories visibly supported by the reference/product facts.
- Never use a fixed blueprint name, a collected-image template, a generic feature-card grid, or the same composition twice.
- Each render_prompt must explicitly preserve the profile's fidelity anchors and describe believable category physics.
- Write a genuinely different visual_concept, camera_direction and product_treatment for every module.
- Every non-main render_prompt explicitly says the named public copy strings are the only added text, must appear exactly
  once and character-for-character, and forbids all unrequested copy, invented claims, extra logos, badges and watermarks.
- Gallery white_main remains the only forced text-free frame.
{color_directive}
{_FIDELITY_RULE}
"""
    try:
        # The shared provider chain may otherwise stack several 5–10 minute
        # provider timeouts. A visual brief must resolve inside the UI request
        # budget; deterministic fallback remains editable and evidence-safe.
        raw = await asyncio.wait_for(
            _call_ai(prompt, max_tokens=4000, web_search=False),
            timeout=240,
        )
    except (HTTPException, asyncio.TimeoutError):
        raw = ""
    parsed = _strip_json(raw)
    if parsed and isinstance(parsed.get("images"), list) and parsed["images"]:
        parsed["product_profile"] = product_profile
        parsed["planning_mode"] = "adaptive_direct_text"
        parsed["creative_brief"] = body.brief
        parsed["language"] = body.language
        parsed["template_story"] = []
        parsed["template_images"] = []
        plan = _normalize_shot_plan(parsed, n, deliverable)
        used_fallback = not plan["images"]
    else:
        used_fallback = True
    if used_fallback:
        plan = _shot_plan_fallback(
            row, scrape_data, analysis_data, n, body.color_scheme, deliverable, product_profile,
        )
        plan["creative_brief"] = body.brief
        plan["language"] = body.language
        plan["template_story"] = []
        plan["template_images"] = []
        # The deterministic fallback still compiles the user's manual brief and
        # artwork language into every final prompt instead of silently dropping
        # the highest-priority creative input when the planner is unavailable.
        plan = _normalize_shot_plan(plan, n, deliverable)
    plan = _bind_reference_templates(plan, project_id, scrape_data, deliverable)
    _persist_shot_plan(project_id, plan, deliverable)
    _persist_visual_anchor(project_id, row, {"product_lock": plan.get("product_lock"),
                                             "visual_style": json.dumps(plan.get("style") or {}, ensure_ascii=False)})
    return {"ok": True, "plan": plan, "fallback": used_fallback}


@router.post("/projects/{project_id}/creative-set")
async def save_creative_set(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Persist storyboard edits, generated URLs, versions and review state."""
    conn = _db()
    row = conn.execute("SELECT id FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "project not found")
    deliverable = "aplus" if body.get("deliverable") == "aplus" else "gallery"
    raw_plan = body.get("plan") if isinstance(body.get("plan"), dict) else {}
    target_count = len(raw_plan.get("images") or [])
    plan = _normalize_shot_plan(raw_plan, target_count, deliverable)
    _persist_shot_plan(project_id, plan, deliverable)
    return {"ok": True, "plan": plan}


# ─── Generate ALL Prompts at Once (unified style) ─────────────────────────────

@router.post("/projects/{project_id}/generate-all-prompts")
async def generate_all_prompts(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Generate image prompts using 8-step methodology in a single AI call."""
    conn = _db()
    row = conn.execute("SELECT * FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    analysis_data = json.loads(row["analysis_data"]) if row["analysis_data"] else {}
    product_context = _build_product_context(row, scrape_data, analysis_data)

    ref_images = scrape_data.get("reference_images", []) or scrape_data.get("imageUrls", [])
    ref_urls_text = "\n".join(ref_images[:3]) if ref_images else "No reference images."
    img_sp = analysis_data.get("image_insights", "")

    sizes = body.get("sizes", {})
    if isinstance(sizes, dict) and "sizes" in sizes:
        sizes = sizes["sizes"]
    color_scheme = body.get("color_scheme", "")
    all_slots = [
        ("main", "白底主图"), ("sub1", "副图1"), ("sub2", "副图2"), ("sub3", "副图3"),
        ("sub4", "副图4"), ("sub5", "副图5"), ("sub6", "副图6"),
        ("aplus_banner", "A+横幅"), ("aplus_1", "A+模块1"), ("aplus_2", "A+模块2"),
        ("aplus_3", "A+模块3"), ("aplus_4", "A+对比"), ("brand_story", "品牌故事"),
    ]

    color_directive = _color_directive(color_scheme, analysis_data)
    approved = _approved_copy(row)
    approved_block = (f"\n\n## APPROVED LISTING COPY (claim evidence only; typography is added separately)\n{approved}"
                      if approved else "")

    prompt = f"""You are an Amazon listing image strategist. Complete ALL steps below in one response.

IMPORTANT: Do NOT use web search. Do NOT look up any information online. Work ONLY with the product information provided below. Respond immediately with the JSON output.

## PRODUCT INFO
{product_context}{approved_block}

## REFERENCE IMAGES (only source of truth for product appearance)
{ref_urls_text}

## VISUAL ANALYSIS OF ALL IMAGES (selling points / style / scenes extracted from EVERY scraped + uploaded image)
{img_sp or "(not available — no vision model configured or no images)"}

## STEPS TO FOLLOW:
1. IDENTIFY product appearance from reference images (shape, color, material, features, accessories)
2. Determine CATEGORY and top 5 BUYER CONCERNS before purchase
3. Assign each of 7 main images a DIFFERENT sales task solving one buyer concern
4. Write PRODUCT LOCK: strict appearance description + what NOT to add/change
5. Choose VISUAL STYLE based on category buyer psychology
6. Write 13 PROMPTS (120-180 words each) with structure below

## VISUAL QUALITY RULES (apply to EVERY prompt):
- Use a plausible camera position and lens perspective; do not add camera-brand name dropping.
- Match light direction, contact shadow, reflections, product scale and depth of field to a real physical set.
- Use ordinary category-appropriate materials and a restrained palette with one subtle accent.
- Preserve surface texture without inventing condensation, damage, ports, labels or accessories.
- Reserve a low-detail negative-space region for typography; do not ask the image model to draw text.
- Never use neon trails, holograms, sci-fi sets, floating glass panels, levitating products or fantasy scene mashups.
{color_directive}
{_TEXT_RULE}
{_FIDELITY_RULE}

## CRITICAL RULES:
- Main image: pure white background, product 85%, no text, studio lighting that reveals every texture
- Every prompt MUST start with the product appearance description (same across all 13)
- Do NOT invent specs not in product info
- For images with text: reserve clean negative space; text is typeset separately after generation
- Keep product consistent across ALL images
- Each scene must look physically believable and useful to a shopper, not artificially expensive

## OUTPUT FORMAT (valid JSON, no other text):
{{"product_lock":"strict appearance description and prohibitions","visual_style":"style + color palette + why","category":"exact Amazon category","buyer_concerns":["c1","c2","c3","c4","c5"],"prompts":{{"main":"prompt...","sub1":"prompt...","sub2":"prompt...","sub3":"prompt...","sub4":"prompt...","sub5":"prompt...","sub6":"prompt...","aplus_banner":"prompt...","aplus_1":"prompt...","aplus_2":"prompt...","aplus_3":"prompt...","aplus_4":"prompt...","brand_story":"prompt..."}}}}"""

    try:
        content = await _call_ai(prompt, max_tokens=16000, web_search=False)
    except HTTPException:
        slot_details = _slot_details_from_body(body, [sid for sid, _ in all_slots])
        return _fallback_prompts_for_slots(row, scrape_data, analysis_data, slot_details, color_scheme)
    result = _parse_json_response(content)

    if not result or not result.get("prompts"):
        return {"raw": content[:2000], "error": "Failed to parse response"}

    # Save product_lock to DB
    if result.get("product_lock"):
        conn = _db()
        existing = json.loads(row["analysis_data"]) if row["analysis_data"] else {}
        existing["product_lock"] = result["product_lock"]
        existing["visual_style"] = result.get("visual_style", "")
        existing["category"] = result.get("category", "")
        conn.execute(
            "UPDATE listing_projects SET analysis_data = ?, updated_at = ? WHERE id = ?",
            (json.dumps(existing, ensure_ascii=False), time.time(), project_id)
        )
        conn.commit()
        conn.close()

    return result


# ─── Separate Generation Endpoints ────────────────────────────────────────────

MAIN_SLOTS = ["main", "sub1", "sub2", "sub3", "sub4", "sub5", "sub6"]
APLUS_SLOTS = [
    "aplus_banner_desktop", "aplus_banner_mobile",
    "aplus_1_desktop", "aplus_1_mobile",
    "aplus_2_desktop", "aplus_2_mobile",
    "aplus_3_desktop", "aplus_3_mobile",
    "aplus_compare_desktop", "aplus_compare_mobile",
    "brand_story_desktop", "brand_story_mobile",
]


def _slot_details_from_body(body: dict, default_slots: list[str]) -> list[dict]:
    """Normalize dynamic frontend slot config while keeping legacy defaults."""
    raw_slots = body.get("slots")
    if isinstance(raw_slots, list) and raw_slots:
        details = []
        for item in raw_slots:
            if isinstance(item, str):
                sid = item.strip()
                if sid:
                    details.append({"id": sid, "label": sid, "size": ""})
            elif isinstance(item, dict):
                sid = str(item.get("id", "")).strip()
                if sid:
                    details.append({
                        "id": sid,
                        "label": str(item.get("label") or sid).strip(),
                        "size": str(item.get("size") or "").strip(),
                    })
        if details:
            return details

    sizes = body.get("sizes", {})
    if isinstance(sizes, dict) and "sizes" in sizes:
        sizes = sizes["sizes"]
    if not isinstance(sizes, dict):
        sizes = {}
    return [{"id": sid, "label": sid, "size": str(sizes.get(sid, "")).strip()} for sid in default_slots]


def _color_directive(color_scheme: str, analysis_data: dict) -> str:
    """Color instruction shared by all prompt builders.

    - explicit scheme  → lock to it across every slot
    - empty / 'auto'   → reuse a palette already locked on the project, else
                         tell the model to pick ONE palette and emit exact hex codes
    Keeping the palette identical across slots (and across single-slot
    regeneration) is what stops the color drift between generated images.
    """
    cs = (color_scheme or "").strip()
    saved = str((analysis_data or {}).get("palette") or (analysis_data or {}).get("visual_style") or "").strip()
    if cs and cs.lower() != "auto":
        return (f"- MANDATORY COLOR PALETTE: Use '{cs}' as the dominant palette for EVERY image — same "
                f"backgrounds, props, lighting and color grading. Express it as 4-6 explicit HEX codes in "
                f"visual_style and reuse those exact codes in every prompt.")
    if saved:
        return (f"- MANDATORY COLOR PALETTE (locked for consistency): {saved}\n  Reuse these EXACT colors in "
                f"every prompt. Do not introduce a new dominant color.")
    return ("- COLOR PALETTE: Choose ONE cohesive palette for the whole set, express it as 4-6 explicit HEX "
            "codes inside visual_style, and apply that SAME hex palette to EVERY image so the set looks unified.")


# Reproduce the real product instead of re-imagining it. The reference photos are
# sent to the image model as actual image inputs at generation time, so URLs in the
# text prompt are useless noise and are explicitly forbidden here.
_FIDELITY_RULE = (
    "- PRODUCT FIDELITY: The real product photos are supplied to the image model directly as image inputs. "
    "Reproduce the product EXACTLY as shown there — identical shape, proportions, colors, materials, logos and "
    "any text printed on the product. Do NOT redesign, recolor, relabel or restyle the product itself; only "
    "change the background, scene, props and lighting. Never put a URL inside the prompt."
)

# Typography is a deterministic post-process.  Image prompts reserve space but do
# not ask a generative model to spell marketing copy.
_TEXT_RULE = (
    "- TYPOGRAPHY SPACE: Do not render marketing text, letters, numbers, icons, badges or UI in the generated image. "
    "Reserve a deliberate low-detail negative-space region for copy that will be typeset separately. "
    "The white-background main image must have no copy and no decorative graphics."
)


def _persist_visual_anchor(project_id: str, row, result: dict) -> None:
    """Save product_lock / visual_style / palette onto the project's analysis_data
    so later single-slot regenerations reuse the same product description and colors."""
    if not isinstance(result, dict):
        return
    lock = str(result.get("product_lock") or "").strip()
    style = str(result.get("visual_style") or "").strip()
    if not lock and not style:
        return
    try:
        conn = _db()
        cur = conn.execute("SELECT analysis_data FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
        existing = json.loads(cur["analysis_data"]) if cur and cur["analysis_data"] else {}
        if lock:
            existing["product_lock"] = lock
        if style:
            existing["visual_style"] = style
            existing["palette"] = style
        conn.execute(
            "UPDATE listing_projects SET analysis_data = ?, updated_at = ? WHERE id = ?",
            (json.dumps(existing, ensure_ascii=False), time.time(), project_id),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


async def _generate_prompts_for_slots(project_id: str, slots: list[str], body: dict):
    """Shared logic for generating prompts for a subset of slots."""
    conn = _db()
    row = conn.execute("SELECT * FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    analysis_data = json.loads(row["analysis_data"]) if row["analysis_data"] else {}
    product_context = _build_product_context(row, scrape_data, analysis_data)

    ref_images = scrape_data.get("reference_images", []) or scrape_data.get("imageUrls", [])
    ref_urls_text = "\n".join(ref_images[:3]) if ref_images else "No reference images."
    img_sp = analysis_data.get("image_insights", "")

    slot_details = _slot_details_from_body(body, slots)
    slot_ids = [s["id"] for s in slot_details]
    slot_text = "\n".join(
        f'- {s["id"]}: label="{s["label"]}", target_canvas="{s["size"] or "not specified"}"'
        for s in slot_details
    )

    color_scheme = body.get("color_scheme", "")
    color_directive = _color_directive(color_scheme, analysis_data)
    locked_product = str(analysis_data.get("product_lock") or "").strip()
    locked_hint = (f"\n## EXISTING PRODUCT LOCK (reuse this exact description, do not contradict it)\n{locked_product}"
                   if locked_product else "")
    approved = _approved_copy(row)
    approved_block = (f"\n\n## APPROVED LISTING COPY (claim evidence only; typography is added separately)\n{approved}"
                      if approved else "")

    slots_json = ", ".join(f'"{s}":"prompt..."' for s in slot_ids)

    prompt = f"""You are an Amazon listing image strategist. Generate prompts ONLY for these slots: {', '.join(slot_ids)}.

IMPORTANT: Do NOT use web search. Work ONLY with the product information provided below.

## PRODUCT INFO
{product_context}
{locked_hint}{approved_block}

## REFERENCE IMAGES (the real product — supplied to the image model as image inputs)
{ref_urls_text}

## VISUAL ANALYSIS OF ALL IMAGES (selling points / style / scenes from EVERY scraped + uploaded image)
{img_sp or "(not available)"}

## TARGET SLOTS, LABELS, AND CANVAS SIZES
{slot_text}

## VISUAL QUALITY RULES (apply to EVERY prompt):
- Use plausible perspective, accurate scale, contact shadows and consistent light direction.
- Choose a real category-appropriate environment with restrained color and ordinary materials.
- Preserve the product's visible texture and geometry without inventing details.
- Reserve quiet negative space for separately typeset copy.
- Avoid neon, sci-fi, holograms, floating panels, levitation and impossible scene mashups.
{color_directive}
{_TEXT_RULE}
{_FIDELITY_RULE}

## CRITICAL RULES:
- Main image (if included): pure white background, product 85%, no text
- Every prompt MUST start with the product appearance description (identical wording across all slots)
- Each prompt MUST be composed for its target_canvas size. Mention the exact canvas size and layout orientation inside the prompt.
- For Amazon main images, use a high-resolution square canvas suitable for 1400x1400+ delivery when requested.
- For Premium A+ modules, respect desktop 1464x600 and mobile 600x450 layouts when requested.
- Do NOT invent specs not in product info
- Each scene must look physically believable and useful to a shopper

## OUTPUT FORMAT (valid JSON, no other text):
{{"product_lock":"strict appearance description","visual_style":"style + the 4-6 HEX color palette used everywhere","prompts":{{{slots_json}}}}}"""

    try:
        content = await _call_ai(prompt, max_tokens=8000, web_search=False)
    except HTTPException:
        return _fallback_prompts_for_slots(row, scrape_data, analysis_data, slot_details, color_scheme)
    result = _parse_json_response(content)

    if not result or not result.get("prompts"):
        raise HTTPException(502, f"提示词生成失败，AI没有返回可用JSON: {content[:500]}")

    # Persist the product lock + palette so single-slot regeneration and later
    # batches reuse the SAME product description and colors (consistency anchor).
    _persist_visual_anchor(project_id, row, result)

    prompts = result.get("prompts", {})
    if isinstance(prompts, dict):
        cleaned = {sid: str(prompts[sid]).strip() for sid in slot_ids if sid in prompts and str(prompts[sid]).strip()}
        if cleaned:
            reviewed = await _review_batch_prompts(cleaned, slot_details, color_scheme)
            result["prompts"] = reviewed
            return result

    raise HTTPException(502, f"提示词生成失败，AI没有返回当前图片位的提示词: {content[:500]}")


@router.post("/projects/{project_id}/generate-main-prompts")
async def generate_main_prompts(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Generate prompts for 7 main images only (main + sub1-sub6)."""
    return await _generate_prompts_for_slots(project_id, MAIN_SLOTS, body)


@router.post("/projects/{project_id}/generate-aplus-prompts")
async def generate_aplus_prompts(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Generate prompts for 6 A+ images only (aplus_banner + aplus_1-4 + brand_story)."""
    return await _generate_prompts_for_slots(project_id, APLUS_SLOTS, body)


# ─── Template CRUD ─────────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/templates")
async def create_template(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Upload a prompt text and have AI convert it to a reusable template."""
    conn = _db()
    row = conn.execute("SELECT id, templates FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404)

    name = body.get("name", "Untitled")
    content = body.get("content", "")
    if not content:
        conn.close()
        raise HTTPException(400, "content is required")

    # Use AI to convert specific prompt into a generic template
    ai_prompt = f"""Convert the following product image prompt into a REUSABLE TEMPLATE by replacing specific details with placeholders.

Replace:
- Specific product descriptions → {{product_lock}}
- Reference URLs → {{reference_url}}
- Visual style descriptions → {{visual_style}}
- Color scheme/palette mentions → {{color_scheme}}

Keep the structure, composition instructions, lighting, and camera settings intact.
Output ONLY the template text with placeholders, nothing else.

ORIGINAL PROMPT:
{content}"""

    fallback_used = False
    warning = None
    try:
        template_content = await _call_ai(ai_prompt, max_tokens=2000, web_search=False)
    except HTTPException as e:
        template_content = _fallback_template_content(content)
        fallback_used = True
        warning = f"Hermes/Codex 当前不可用，模板已按本地规则保存；恢复额度后可重新保存为 AI 泛化模板。原因：{str(e.detail)[:220]}"

    templates = json.loads(row["templates"]) if row["templates"] else []
    template_entry = {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "content": template_content.strip(),
        "original": content,
        "created_at": time.time(),
        "fallback": fallback_used,
        "warning": warning,
    }
    templates.append(template_entry)

    conn.execute(
        "UPDATE listing_projects SET templates = ?, updated_at = ? WHERE id = ?",
        (json.dumps(templates, ensure_ascii=False), time.time(), project_id)
    )
    conn.commit()
    conn.close()
    return template_entry


@router.get("/projects/{project_id}/templates")
def list_templates(project_id: str, _user: str = Depends(require_user)):
    """Get all templates for a project."""
    conn = _db()
    row = conn.execute("SELECT templates FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)
    return json.loads(row["templates"]) if row["templates"] else []


@router.post("/projects/{project_id}/apply-template")
async def apply_template(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Apply a template intelligently to one slot or a full slot group."""
    conn = _db()
    row = conn.execute("SELECT * FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    template_id = body.get("template_id")
    slot = body.get("slot", "main")
    target_group = body.get("target_group", "main")
    color_scheme = body.get("color_scheme", "natural tones")
    if not template_id:
        raise HTTPException(400, "template_id is required")

    templates = json.loads(row["templates"]) if row["templates"] else []
    template = next((t for t in templates if t["id"] == template_id), None)
    if not template:
        raise HTTPException(404, "template not found")

    analysis_data = json.loads(row["analysis_data"]) if row["analysis_data"] else {}
    scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    ref_images = scrape_data.get("reference_images", []) or scrape_data.get("imageUrls", [])
    product_context = _build_product_context(row, scrape_data, analysis_data)

    filled = template.get("content", "")
    filled = filled.replace("{product_lock}", analysis_data.get("product_lock", "product as shown in reference"))
    filled = filled.replace("{reference_url}", ref_images[0] if ref_images else "")
    filled = filled.replace("{visual_style}", analysis_data.get("visual_style", "professional product photography"))
    filled = filled.replace("{color_scheme}", color_scheme or "natural tones")

    default_main_defs = {
        "main": "Amazon main image: pure white background, product 85%, no text.",
        "sub1": "Lifestyle or use-case image.",
        "sub2": "Detail or key feature image.",
        "sub3": "Size, specification, or scale image.",
        "sub4": "Multi-angle, technology, or structure image.",
        "sub5": "Package, accessories, or what-is-in-the-box image.",
        "sub6": "Multi-scenario, benefits, or closing sales image.",
    }
    default_aplus_defs = {
        "aplus_banner": "Wide A+ hero banner.",
        "aplus_banner_desktop": "Premium A+ hero banner for desktop, wide 1464x600 layout.",
        "aplus_banner_mobile": "Premium A+ hero banner for mobile, compact 600x450 layout.",
        "aplus_1": "A+ module 1, primary feature.",
        "aplus_1_desktop": "A+ module 1 desktop version, primary feature in 1464x600 layout.",
        "aplus_1_mobile": "A+ module 1 mobile version, same feature adapted to 600x450 layout.",
        "aplus_2": "A+ module 2, secondary feature.",
        "aplus_2_desktop": "A+ module 2 desktop version, secondary feature in 1464x600 layout.",
        "aplus_2_mobile": "A+ module 2 mobile version, same feature adapted to 600x450 layout.",
        "aplus_3": "A+ module 3, tertiary feature.",
        "aplus_3_desktop": "A+ module 3 desktop version, tertiary feature in 1464x600 layout.",
        "aplus_3_mobile": "A+ module 3 mobile version, same feature adapted to 600x450 layout.",
        "aplus_4": "A+ comparison, trust, specs, or advantage module.",
        "aplus_compare_desktop": "A+ comparison, trust, specs, or advantage module for desktop 1464x600 layout.",
        "aplus_compare_mobile": "A+ comparison, trust, specs, or advantage module for mobile 600x450 layout.",
        "brand_story": "Brand story or final trust-building module.",
        "brand_story_desktop": "Brand story or final trust-building module for desktop 1464x600 layout.",
        "brand_story_mobile": "Brand story or final trust-building module for mobile 600x450 layout.",
    }
    default_defs = default_aplus_defs if target_group == "aplus" else default_main_defs
    default_slots = list(default_defs.keys())
    target_slot_details = _slot_details_from_body(body, default_slots)
    slot_defs = {
        s["id"]: f'{s["label"]}; target canvas {s["size"] or "not specified"}; {default_defs.get(s["id"], "")}'
        for s in target_slot_details
    }

    slot_lines = "\n".join(f"- {k}: {v}" for k, v in slot_defs.items())
    ref_text = "\n".join(ref_images[:3]) if ref_images else "No reference image URL available."

    ai_prompt = f"""You are an Amazon listing image prompt strategist.

Apply the user's reusable template to the CURRENT PRODUCT. Do NOT paste the template verbatim.

## CURRENT PRODUCT DATA
{product_context}

## PRODUCT LOCK
{analysis_data.get("product_lock", "Describe the product exactly as shown in reference images. Do not change appearance.")}

## VISUAL STYLE
{analysis_data.get("visual_style", "Professional Amazon product photography.")}

## REFERENCE IMAGES
{ref_text}

## TARGET SLOT GROUP
{target_group}

## AVAILABLE SLOTS
{slot_lines}

## REQUESTED SLOT
{slot}

## FILLED TEMPLATE TO ANALYZE
{filled}

## TASK
1. First decide whether the template describes a single image or a multi-image set / full A+ sequence.
2. If it is a multi-image set, split and adapt it across the relevant available slots. For a full A+ poster/template, create separate prompts for aplus_banner, aplus_1, aplus_2, aplus_3, aplus_4, and brand_story when possible.
3. If it is a single-image template, adapt it only to the requested slot.
4. Every output prompt must be for GPT Image generation, not instructions about the template itself.
5. Use real current product data, product_lock, visual_style, color scheme, and reference images.
6. Keep product appearance consistent. Do not invent unsupported specs.
7. For each prompt: 100-220 words, include the reference image URL when available, include clear composition/lighting/text instructions.
8. Respect each slot's target canvas and orientation. For Premium A+ desktop use 1464x600 when configured; for mobile use 600x450 when configured.
9. If the user's template is a full A+ desktop/mobile system, distribute it across all configured A+ desktop and mobile slots instead of putting everything into one prompt.
10. Do not output placeholder braces like {{product_lock}} or {{reference_url}}.

## OUTPUT FORMAT
Return valid JSON only:
{{"mode":"single_or_multi","prompts":{{"slot_id":"adapted prompt text"}}}}"""

    try:
        content = await _call_ai(ai_prompt, max_tokens=12000, web_search=False)
    except HTTPException:
        result = _fallback_prompts_for_slots(row, scrape_data, analysis_data, target_slot_details, color_scheme, filled)
        prompts = result["prompts"]
        return {
            "slot": slot,
            "prompt": prompts.get(slot, next(iter(prompts.values()))),
            "prompts": prompts,
            "mode": "fallback_multi" if len(prompts) > 1 else "fallback_single",
            "fallback": True,
            "warning": result["warning"],
        }
    result = _parse_json_response(content)
    prompts = result.get("prompts") if isinstance(result, dict) else None
    if isinstance(prompts, dict):
        cleaned = {k: str(v).strip() for k, v in prompts.items() if k in slot_defs and str(v).strip()}
        if cleaned:
            return {"slot": slot, "prompt": cleaned.get(slot, next(iter(cleaned.values()))), "prompts": cleaned, "mode": result.get("mode", "")}

    raise HTTPException(502, f"模板智能套用失败，AI没有返回可用的槽位提示词: {content[:500]}")


def _parse_json_response(content: str) -> Optional[dict]:
    """Robustly parse JSON from AI response, handling markdown fences and formatting issues."""
    if not content:
        return None

    # Strip markdown code fences
    cleaned = content.strip()
    if cleaned.startswith("```"):
        # Remove first line (```json or ```)
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline + 1:]
        else:
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    # Try direct parse
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # Try brace-depth matching to find the outermost JSON object
    depth = 0
    start_idx = None
    end_idx = None
    in_string = False
    escape_next = False
    for i, c in enumerate(content):
        if escape_next:
            escape_next = False
            continue
        if c == '\\' and in_string:
            escape_next = True
            continue
        if c == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '{':
            if depth == 0:
                start_idx = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and start_idx is not None:
                end_idx = i + 1
                break

    if start_idx is not None and end_idx is not None:
        try:
            return json.loads(content[start_idx:end_idx])
        except Exception:
            pass

    return None


# ─── Single Image Prompt ───────────────────────────────────────────────────────

@router.post("/projects/{project_id}/generate-image-prompt")
async def generate_image_prompt(project_id: str, body: dict, _user: str = Depends(require_user)):
    conn = _db()
    row = conn.execute("SELECT * FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    slot = body.get("slot", "main")
    slot_label = str(body.get("label") or slot).strip()
    slot_size = str(body.get("size") or "").strip()
    color_scheme = body.get("color_scheme", "")
    scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
    analysis_data = json.loads(row["analysis_data"]) if row["analysis_data"] else {}
    product_context = _build_product_context(row, scrape_data, analysis_data)

    # Get product_lock and image_tasks from previous pipeline analysis
    product_lock = analysis_data.get("product_lock", "")
    visual_style = analysis_data.get("visual_style", "")
    image_tasks = analysis_data.get("image_tasks", {})
    slot_task = image_tasks.get(slot, "")
    approved = _approved_copy(row)
    approved_block = (f"\n\n## APPROVED LISTING COPY (claim evidence only; typography is added separately)\n{approved}"
                      if approved else "")

    # Reference images
    ref_images = scrape_data.get("reference_images", []) or scrape_data.get("imageUrls", [])
    ref_urls_text = "\n".join(ref_images[:3]) if ref_images else ""

    slot_descriptions = {
        "main": "White background main image. Pure white (#FFFFFF), product centered 85%, no text, no icons. Include accessories if they show kit value. Soft studio shadow.",
        "sub1": "Outdoor/lifestyle scene showing the product in real use. Authentic environment, natural lighting.",
        "sub2": "Detail/feature image highlighting a key selling point with clean negative space for later typography.",
        "sub3": "Specifications/size image. Clean infographic style with dimensions or scale reference.",
        "sub4": "Technology/multi-angle image. Show internal features or multiple views.",
        "sub5": "Package/accessories image. Show everything included in the kit.",
        "sub6": "Multi-scenario image. Show 3-4 different use cases around the product.",
        "aplus_banner": "Wide-format A+ banner. Cinematic, brand-level imagery.",
        "aplus_banner_desktop": "Wide-format Premium A+ desktop banner. Cinematic brand-level imagery composed for 1464x600.",
        "aplus_banner_mobile": "Mobile Premium A+ banner. Same hero idea adapted to a compact 600x450 layout.",
        "aplus_1": "A+ feature module highlighting primary selling point.",
        "aplus_1_desktop": "A+ desktop feature module highlighting primary selling point in a wide 1464x600 layout.",
        "aplus_1_mobile": "A+ mobile feature module highlighting primary selling point in a compact 600x450 layout.",
        "aplus_2": "A+ feature module highlighting secondary selling point.",
        "aplus_2_desktop": "A+ desktop feature module highlighting secondary selling point in a wide 1464x600 layout.",
        "aplus_2_mobile": "A+ mobile feature module highlighting secondary selling point in a compact 600x450 layout.",
        "aplus_3": "A+ feature module highlighting tertiary selling point.",
        "aplus_3_desktop": "A+ desktop feature module highlighting tertiary selling point in a wide 1464x600 layout.",
        "aplus_3_mobile": "A+ mobile feature module highlighting tertiary selling point in a compact 600x450 layout.",
        "aplus_4": "A+ comparison image showing product advantages.",
        "aplus_compare_desktop": "A+ desktop comparison, specs, trust, or advantage module in a wide 1464x600 layout.",
        "aplus_compare_mobile": "A+ mobile comparison, specs, trust, or advantage module in a compact 600x450 layout.",
        "brand_story": "Brand story image communicating brand values and mission.",
        "brand_story_desktop": "Desktop brand story or trust-building module in a wide 1464x600 layout.",
        "brand_story_mobile": "Mobile brand story or trust-building module in a compact 600x450 layout.",
    }
    slot_desc = slot_descriptions.get(slot, f"{slot_label}. Product showcase image.")

    prompt = f"""You are an Amazon product image prompt engineer. Write ONE image generation prompt for this slot.

## SLOT TYPE
{slot_desc}

## CURRENT SLOT CONFIG
- Slot id: {slot}
- Slot label: {slot_label}
- Target canvas: {slot_size or "not specified"}

## SALES TASK FOR THIS IMAGE
{slot_task if slot_task else "Attract buyer attention and communicate product value."}

## PRODUCT LOCK (you MUST start your prompt with this — do not change the product appearance)
{product_lock if product_lock else "Describe the product exactly as shown in the reference photos. Do not alter its design."}

## VISUAL STYLE (reuse exactly — this keeps every image in the set consistent)
{visual_style if visual_style else "Professional Amazon product photography style appropriate for this category."}
{_color_directive(color_scheme, analysis_data)}

## PRODUCT INFORMATION
{product_context}{approved_block}

## REFERENCE IMAGES (the real product — sent to the image model as image inputs, NOT as text)
{ref_urls_text if ref_urls_text else "No reference images available."}

{_FIDELITY_RULE}
{_TEXT_RULE}

## PROMPT STRUCTURE (follow this exactly):
1. Product appearance lock — exact physical description from product lock above (first sentence)
2. Image goal — what this image must communicate (from sales task)
3. Scene/background — specific environment or background
4. Composition — product position, size in frame, camera angle
5. Canvas/layout — compose for target canvas {slot_size or "not specified"} and mention that exact size in the prompt
6. Typography zone — reserve a low-detail area for separately typeset copy; render no words, letters or numbers
7. Style/lighting — the locked color palette, lighting setup, mood
8. Negative constraints — what NOT to include

## RULES
- Output ONLY the prompt text, no explanations, no prefixes
- 100-200 words
- First sentence MUST be the product lock (exact appearance description)
- Never put a URL in the prompt — the reference photos are already given to the model
- MUST respect the current slot label and target canvas
- For feature/infographic images: describe the reserved text zone, but do not ask the model to draw copy
- Do NOT invent specs not mentioned in product info
- Do NOT use generic language like "high quality" or "professional" alone"""

    try:
        content = await _call_ai(prompt, max_tokens=16000)
    except HTTPException as e:
        content = _fallback_image_prompt(slot, slot_label, slot_size, row, scrape_data, analysis_data, color_scheme)
        return {
            "slot": slot,
            "prompt": content.strip(),
            "fallback": True,
            "warning": f"Hermes/Codex 当前不可用，已用本地规则生成可编辑图片提示词。原因：{str(e.detail)[:220]}",
        }
    return {"slot": slot, "prompt": content.strip()}


@router.post("/projects/{project_id}/review-image-prompt")
async def review_image_prompt(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Accept a user-submitted prompt draft, self-review and return an improved version."""
    conn = _db()
    row = conn.execute("SELECT id FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    slot = body.get("slot", "main")
    draft = body.get("prompt", "").strip()
    label = str(body.get("label") or slot).strip()
    size = str(body.get("size") or "").strip()
    color_scheme = body.get("color_scheme", "")

    if not draft:
        raise HTTPException(400, "prompt is required")

    reviewed = await _review_single_prompt(draft, label, size, color_scheme)
    return {"slot": slot, "prompt": reviewed}


# ─── Image Generation ─────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/generate-image")
async def generate_single_image(project_id: str, body: ImageGenReq, _user: str = Depends(require_user)):
    conn = _db()
    row = conn.execute("SELECT id, scrape_data, analysis_data FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)

    # Build reference image list: uploaded files (base64) take priority over scraped URLs
    # scene/result 图(use_reference=False)不挂参考图,生成纯场景 —— 根治"张张都是产品、看起来一样"
    ref_urls = (body.reference_urls if body.use_reference else [])
    if body.use_reference and not ref_urls:
        import base64 as _b64
        import mimetypes as _mt
        scrape_data = json.loads(row["scrape_data"]) if row["scrape_data"] else {}
        scraped_urls = (scrape_data.get("reference_images") or scrape_data.get("imageUrls") or [])[:2]
        uploaded_paths = scrape_data.get("uploaded_images", [])
        b64_refs: list[str] = []
        for p in uploaded_paths[:4]:
            p_obj = Path(p)
            if p_obj.exists():
                try:
                    raw = p_obj.read_bytes()
                    mime = _mt.guess_type(str(p_obj))[0] or "image/jpeg"
                    b64_refs.append(f"data:{mime};base64,{_b64.b64encode(raw).decode()}")
                except Exception:
                    pass
        # Uploaded images first (user's own product photos), then scraped.
        # Cap at 2: passing many conflicting angles to gpt-image makes it blend
        # them into a deformed hybrid. Fewer, cleaner references = higher fidelity.
        ref_urls = (b64_refs + list(scraped_urls))[:2]

    # Browser-facing workspace URLs are not reachable by the external image
    # provider. Materialise only those local references as data URIs while
    # preserving list order (product truth first, visual template second).
    if ref_urls:
        materialised: list[str] = []
        async with httpx.AsyncClient(timeout=60) as ref_client:
            for url in ref_urls[:2]:
                value = str(url or "").strip()
                if value.startswith("/api/"):
                    try:
                        raw_ref = await _fetch_image_bytes(ref_client, value)
                        mime = mimetypes.guess_type(value.split("?", 1)[0])[0] or "image/png"
                        materialised.append(f"data:{mime};base64,{base64.b64encode(raw_ref).decode()}")
                    except Exception as exc:  # noqa: BLE001
                        raise HTTPException(502, f"本地参考图读取失败：{exc}") from exc
                elif value:
                    materialised.append(value)
        ref_urls = materialised
    if body.reference_mode != "template":
        # Direct studio generation has one immutable product truth. Multiple
        # angles/competitor images encourage the model to blend identities.
        ref_urls = ref_urls[:1]

    if not _apimart_key():
        raise HTTPException(
            400,
            "Apimart 密钥未配置 — 请在「系统配置 → AI 服务」填入有 gpt-image-2 权限的密钥。",
        )

    # Deterministic product-fidelity preamble: the per-slot prompt is LLM-written and
    # may drift, so we always prepend a hard "reproduce the real product exactly"
    # instruction whenever reference photos are attached. This is the main lever for
    # keeping the generated product consistent with the user's real product.
    full_prompt = body.prompt
    if ref_urls:
        if body.reference_mode == "template" and len(ref_urls) >= 2:
            full_prompt = (
                "CRITICAL REFERENCE ROLES — DO NOT MIX THEM. REFERENCE 1 is the ONLY PRODUCT TRUTH: reproduce its "
                "product identically, including shape, proportions, color, material, controls, ports and included parts. "
                "REFERENCE 2 is ONLY A VISUAL TEMPLATE: reuse its content hierarchy, shot category, camera/view type, "
                "subject scale, negative-space map and design density, but do not copy its product identity, brand, logo, "
                "written text, person identity or exact pixels. Replace the template's product with REFERENCE 1. "
                "Create one coherent commercial photograph with believable perspective, contact, shadow and lighting. "
                "Render no words, letters, numbers, badges, diagrams or watermarks; typography is added later.\n\n"
            ) + body.prompt
        else:
            full_prompt = (
                "CRITICAL — IMMUTABLE PRODUCT TRUTH: REFERENCE IMAGE 1 shows the EXACT sellable product. "
                "Reproduce it identically: same silhouette, geometry, proportions, colors, color blocking, materials, "
                "surface finish, seams, openings, lenses, controls, ports, logos, labels, printed product markings, "
                "accessories and quantity. Change ONLY the environment, camera, composition, lighting, supporting graphic "
                "design and the exact artwork copy explicitly requested by the prompt. "
                "Do NOT redesign, recolor, relabel, simplify, crop away, add or remove any product part. "
                "When the prompt bans text, that means no ADDED marketing text; existing markings on the reference product "
                "must remain unchanged. If a requested composition conflicts with product fidelity, preserve the product.\n\n"
            ) + body.prompt

    from app.services.listing_image_compositor import parse_size
    target_w, target_h = parse_size(body.size)
    if abs(target_w / target_h - 1) < .12:
        provider_size = "1024x1024"
    elif target_w > target_h:
        provider_size = "1536x1024"
    else:
        provider_size = "1024x1536"
    base_body = {"model": "gpt-image-2", "prompt": full_prompt, "n": 1, "size": provider_size}
    if ref_urls:
        base_body["image_urls"] = ref_urls[:2]

    # gpt-image's `input_fidelity:"high"` preserves details of the input image (the
    # real product). Apimart may or may not pass it through, so try high-fidelity
    # first and gracefully fall back to a plain request if it is rejected.
    attempts = [{**base_body, "input_fidelity": "high"}, base_body] if ref_urls else [base_body]

    try:
        # Submission should return a task id quickly.  A long upstream read here
        # used to stack with the poll loop and lock the studio for 7–10 min.
        async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=20)) as client:
            import logging
            logging.info(f"[generate-image] slot={body.slot} ref_urls={len(ref_urls)} fidelity={'high' if ref_urls else 'n/a'}")

            resp = None
            for idx, attempt in enumerate(attempts):
                resp = await client.post(
                    f"{_apimart_base()}/images/generations",
                    headers={"Authorization": f"Bearer {_apimart_key()}", "Content-Type": "application/json"},
                    json=attempt,
                )
                if resp.status_code == 200:
                    if idx > 0:
                        logging.info(f"[generate-image] input_fidelity=high rejected, fell back to plain (slot={body.slot})")
                    elif "input_fidelity" in attempt:
                        logging.info(f"[generate-image] input_fidelity=high accepted (slot={body.slot})")
                    break  # accepted (with or without high fidelity)
                logging.info(f"[generate-image] attempt {idx} -> HTTP {resp.status_code}: {resp.text[:160]}")
                # The plain retry exists only for providers that reject the
                # optional input_fidelity field. Retrying 5xx/rate-limit errors
                # with the same payload just doubles the request time.
                if not (idx == 0 and resp.status_code in {400, 422}):
                    break
            if resp is None or resp.status_code != 200:
                raise HTTPException(502, f"图片生成提交失败: {resp.text[:300] if resp is not None else 'no response'}")

            submit_data = resp.json()
            task_id = submit_data.get("data", [{}])[0].get("task_id")
            if not task_id:
                raise HTTPException(502, f"未返回task_id: {resp.text[:300]}")

            # Image tasks regularly need 2–4 minutes.  Waiting here makes the
            # single HTTP request cross Cloudflare's ~100 second proxy limit; the
            # browser then reports a failure (nginx 499) although Apimart later
            # finishes and charges for the image.  Return immediately and let the
            # browser poll the short status endpoint below.
            return {
                "slot": body.slot,
                "task_id": task_id,
                "status": "processing",
                "size": body.size,
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"图片生成失败: {str(e)}")


_IMAGE_TASK_RESULTS: dict[str, dict] = {}


def _parse_image_task_payload(payload: dict) -> dict:
    """Convert Apimart's task payload into a stable client-facing state."""
    task_data = payload.get("data") if isinstance(payload, dict) else {}
    task_data = task_data if isinstance(task_data, dict) else {}
    status = str(task_data.get("status") or "processing").strip().lower()
    if status == "completed":
        result = task_data.get("result") if isinstance(task_data.get("result"), dict) else {}
        images = result.get("images") if isinstance(result.get("images"), list) else []
        url = images[0].get("url") if images and isinstance(images[0], dict) else ""
        if isinstance(url, list):
            url = url[0] if url else ""
        if url:
            return {"status": "completed", "provider_url": str(url)}
        return {"status": "failed", "error": "任务完成但未返回图片 URL"}
    if status == "failed":
        detail = task_data.get("error") or task_data.get("message") or task_data.get("result") or "上游生图任务失败"
        return {"status": "failed", "error": str(detail)[:500]}
    return {"status": status or "processing"}


@router.post("/projects/{project_id}/image-task-status")
async def image_task_status(project_id: str, body: ImageTaskStatusReq,
                            _user: str = Depends(require_user)):
    """Poll one upstream task without holding a proxy connection open."""
    conn = _db()
    row = conn.execute("SELECT id FROM listing_projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,160}", body.task_id):
        raise HTTPException(400, "无效的生图任务 ID")

    cache_key = f"{project_id}:{body.task_id}:{body.size}"
    cached = _IMAGE_TASK_RESULTS.get(cache_key)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=20)) as client:
            poll = await client.get(
                f"{_apimart_base()}/tasks/{body.task_id}",
                headers={"Authorization": f"Bearer {_apimart_key()}"},
            )
            # Rate limits and transient provider failures are retryable.  Report
            # processing so one bad status request does not discard a paid task.
            if poll.status_code == 429 or poll.status_code >= 500:
                return {"task_id": body.task_id, "slot": body.slot, "status": "processing"}
            if poll.status_code != 200:
                return {
                    "task_id": body.task_id,
                    "slot": body.slot,
                    "status": "failed",
                    "error": f"生图任务查询失败 HTTP {poll.status_code}: {poll.text[:240]}",
                }

            state = _parse_image_task_payload(poll.json())
            if state["status"] != "completed":
                return {"task_id": body.task_id, "slot": body.slot, **state}

            # Providers may return a different aspect ratio.  Normalise locally
            # only after completion, in a separate short request.
            raw = await _fetch_image_bytes(client, state["provider_url"])
        from app.services.listing_image_compositor import normalise_canvas, technical_quality
        normalised = normalise_canvas(raw, body.size, mode="cover")
        from app.routers.image_translate import save_bytes_to_workspace
        item = save_bytes_to_workspace(normalised, source="listing", project_id=project_id)
        result = {
            "task_id": body.task_id,
            "slot": body.slot,
            "status": "completed",
            "url": item["url"],
            "provider_url": state["provider_url"],
            "size": body.size,
            "technical_qa": technical_quality(normalised, body.size),
        }
        # A small idempotency cache prevents duplicate workspace files if the
        # completion response is retried after a mobile network interruption.
        if len(_IMAGE_TASK_RESULTS) >= 200:
            _IMAGE_TASK_RESULTS.pop(next(iter(_IMAGE_TASK_RESULTS)))
        _IMAGE_TASK_RESULTS[cache_key] = result
        return result
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"生图任务查询失败: {exc}") from exc


async def _fetch_image_bytes(client: httpx.AsyncClient, url: str) -> bytes:
    """Load image bytes from a workspace url (file read) or an external url (http)."""
    from app.routers.image_translate import WORKSPACE_DIR
    prefix = "/api/image-translate/images/"
    if prefix in url:
        fn = url.split(prefix, 1)[1].split("?")[0]
        p = WORKSPACE_DIR / fn
        if p.exists():
            return p.read_bytes()
    upload_prefix = "/api/listing/images/"
    if upload_prefix in url:
        rel = url.split(upload_prefix, 1)[1].split("?")[0]
        parts = [part for part in rel.split("/") if part and part not in {".", ".."}]
        if len(parts) >= 2:
            p = IMAGES_DIR / parts[0] / parts[-1]
            if p.exists():
                return p.read_bytes()
    if url.startswith("data:") and "," in url:
        return base64.b64decode(url.split(",", 1)[1])
    if "m.media-amazon." in url:
        import shutil
        import subprocess
        curl = shutil.which("curl")
        if curl:
            from app.core.proc import no_window_kwargs
            completed = await asyncio.to_thread(
                subprocess.run,
                [curl, "-fsSL", "--max-time", "25", url],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30,
                **no_window_kwargs(),
            )
            if completed.returncode == 0 and completed.stdout:
                return completed.stdout
    r = await client.get(url)
    r.raise_for_status()
    return r.content


@router.post("/projects/{project_id}/prepare-asset")
async def prepare_asset(project_id: str, body: PrepareAssetReq, _user: str = Depends(require_user)):
    """Normalise real source photography without asking a model to redraw it."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            raw = await _fetch_image_bytes(client, body.url)
        from app.services.listing_image_compositor import normalise_canvas, technical_quality
        out = normalise_canvas(
            raw, body.size,
            mode="contain" if body.mode == "contain" else "cover",
            background=body.background,
        )
        from app.routers.image_translate import save_bytes_to_workspace
        item = save_bytes_to_workspace(out, source="listing-source", project_id=project_id)
        return {"url": item["url"], "technical_qa": technical_quality(out, body.size)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"真实素材处理失败：{exc}") from exc


@router.post("/projects/{project_id}/composite-product")
async def composite_product_endpoint(project_id: str, body: CompositeProductReq,
                                     _user: str = Depends(require_user)):
    """Combine an AI-created empty scene with exact source product pixels."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            background_raw, product_raw = await asyncio.gather(
                _fetch_image_bytes(client, body.background_url),
                _fetch_image_bytes(client, body.product_url),
            )
        from app.services.listing_image_compositor import composite_product, technical_quality
        out = composite_product(
            background_raw, product_raw, body.size,
            text_zone=body.text_zone,
            product_scale=body.product_scale,
        )
        from app.routers.image_translate import save_bytes_to_workspace
        item = save_bytes_to_workspace(out, source="listing-composite", project_id=project_id)
        return {"url": item["url"], "technical_qa": technical_quality(out, body.size)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"真实产品合成失败：{exc}") from exc


@router.post("/projects/{project_id}/render-blueprint")
async def render_blueprint_endpoint(project_id: str, body: RenderBlueprintReq,
                                    _user: str = Depends(require_user)):
    """Assemble photo panels, exact product pixels and deterministic graphics."""
    if body.blueprint not in _LAYOUT_BLUEPRINTS:
        raise HTTPException(400, "未知的套图版式")
    expected = _BLUEPRINT_PANEL_COUNTS.get(body.blueprint, 1)
    if len(body.scene_urls) < expected:
        raise HTTPException(400, f"{body.blueprint} 需要 {expected} 张场景素材")
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            product_task = _fetch_image_bytes(client, body.product_url)
            scene_tasks = [_fetch_image_bytes(client, url) for url in body.scene_urls[:expected]]
            values = await asyncio.gather(product_task, *scene_tasks)
        product_raw, scene_raws = values[0], list(values[1:])
        from app.services.listing_blueprint_renderer import render_blueprint
        from app.services.listing_image_compositor import technical_quality
        out = render_blueprint(
            scene_raws, product_raw, body.size,
            blueprint=body.blueprint, accent_color=body.accent_color,
            labels=body.labels,
        )
        from app.routers.image_translate import save_bytes_to_workspace
        item = save_bytes_to_workspace(out, source="listing-blueprint", project_id=project_id)
        return {"url": item["url"], "technical_qa": technical_quality(out, body.size),
                "blueprint": body.blueprint, "scene_count": len(scene_raws)}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"结构化版式渲染失败：{exc}") from exc


def _vision_block(raw: bytes) -> dict:
    """Downsize review inputs so visual QA is fast and bounded."""
    from PIL import Image
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=86, optimize=True)
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg",
                   "data": base64.b64encode(buf.getvalue()).decode()},
    }


async def _render_vision_review(candidate: bytes, source: bytes | None, body: ReviewRenderReq) -> dict:
    """Use a vision model as an art director, not as the generator grading itself."""
    if not _apimart_key():
        return {"available": False, "reason": "visual_review_provider_unconfigured"}
    expected_copy = {
        key: value for key, value in (
            ("eyebrow", body.eyebrow), ("headline", body.headline), ("callout", body.callout),
            ("supporting_text", body.supporting_text), ("proof", body.proof),
        ) if str(value or "").strip()
    }
    content: list[dict] = [{"type": "text", "text": (
        "You are a strict senior ecommerce art director and Amazon image QA reviewer. "
        "Reject generic AI-looking scenes, pasted typography, incorrect product geometry, unreadable copy, "
        "weak selling-point communication, fake evidence and layouts that do not look commercially designed. "
        "The first image below is the exact product/source truth when present; the final image is the candidate. "
        "Product fidelity is an identity check, not a general similarity score. OCR every added artwork string carefully."
    )}]
    if source:
        content.append({"type": "text", "text": "SOURCE PRODUCT / EVIDENCE REFERENCE:"})
        content.append(_vision_block(source))
    content.extend([
        {"type": "text", "text": "CANDIDATE LISTING IMAGE:"},
        _vision_block(candidate),
        {"type": "text", "text": (
            f"Role: {body.role}; shot type: {body.shot_type}; product should appear: {body.show_product}; "
            f"legacy structured blueprint: {body.layout_blueprint or 'none'}. "
            f"EXPECTED ADDED ARTWORK COPY (exact JSON): {json.dumps(expected_copy, ensure_ascii=False)}. "
            "Every expected string must appear exactly once, character-for-character, with no misspelling, paraphrase, "
            "translation, omission, duplication or extra marketing text. Existing labels printed on the source product are "
            "immutable product details and are not unexpected artwork copy. If expected JSON is empty, there must be no "
            "added headline, caption, number, badge or marketing text. "
            f"Product fidelity anchors: {', '.join(body.product_fidelity_anchors[:8]) or 'silhouette, proportions, colour, material and visible details'}. "
            "When product should appear is true, compare every visible product part against the source: silhouette, proportions, "
            "colour blocking, material, seams, openings, controls, logo/label placement, accessories and quantity. Any redesign, "
            "missing/extra part, changed geometry or materially wrong detail is a fatal issue. When product should appear is false, "
            "do not penalize its intentional absence and return product_fidelity 100. "
            "Return JSON only: {\"scores\":{\"product_fidelity\":0-100,\"realism\":0-100,"
            "\"composition\":0-100,\"typography\":0-100,\"copy_accuracy\":0-100,\"commercial_readiness\":0-100},"
            "\"copy_check\":{\"exact\":true|false,\"unexpected_copy\":true|false,\"transcribed\":[\"...\"]},"
            "\"fatal_issues\":[\"...\"],\"improvements\":[\"...\"],\"verdict\":\"pass|fail\"}. "
            "Use pass only when every visible product detail matches the source, copy is concise and consumer-facing, "
            "all expected copy is exact, the layout has deliberate hierarchy, and the image could ship on a strong brand "
            "listing without repair."
        )},
    ])
    async with httpx.AsyncClient(timeout=httpx.Timeout(40, connect=15)) as client:
        response = await asyncio.wait_for(client.post(
                f"{_apimart_base()}/messages",
                json={"model": "claude-sonnet-4-6", "max_tokens": 1200,
                      "messages": [{"role": "user", "content": content}]},
                headers={"Authorization": f"Bearer {_apimart_key()}", "Content-Type": "application/json",
                         "anthropic-version": "2023-06-01"},
            ), timeout=45)
        response.raise_for_status()
    text = "".join(
        block.get("text", "") for block in response.json().get("content", [])
        if isinstance(block, dict) and block.get("type") == "text"
    )
    parsed = _strip_json(text)
    return {"available": bool(parsed), "result": parsed or {}, "raw": text[:500]}


@router.post("/projects/{project_id}/review-render")
async def review_render(project_id: str, body: ReviewRenderReq, _user: str = Depends(require_user)):
    """Technical + visual review.  A generated image cannot self-declare success."""
    source_locked = body.shot_type in _SOURCE_LOCKED_TYPES and bool(body.source_url)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            candidate = await _fetch_image_bytes(client, body.url)
            source = await _fetch_image_bytes(client, body.source_url) if body.source_url and not source_locked else None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"读取成图失败：{exc}") from exc

    from app.services.listing_image_compositor import technical_quality
    technical = technical_quality(candidate, body.size)
    issues = list(technical["issues"])
    public_values = [body.eyebrow, body.headline, body.callout, body.supporting_text, body.proof]
    if any(_INTERNAL_PUBLIC_COPY_RE.search(str(value or "")) for value in public_values):
        issues.append({"code": "internal_copy", "severity": "error",
                       "message": "成图文案包含内部审核说明，禁止交付"})
    if body.proof and not _public_proof(body.proof):
        issues.append({"code": "invalid_proof", "severity": "error",
                       "message": "证明数字不是简短、面向消费者的事实"})

    # Exact source artwork needs technical checks only; no model should second-
    # guess seller-owned pixels. All generated/composited art receives vision QA.
    vision = {"available": False, "reason": "exact_source_asset"}
    if not source_locked and not any(issue.get("severity") == "error" for issue in issues):
        try:
            vision = await _render_vision_review(candidate, source, body)
        except Exception as exc:  # noqa: BLE001
            vision = {"available": False, "reason": str(exc)[:240]}
        if vision.get("available"):
            result = vision.get("result") or {}
            scores = result.get("scores") if isinstance(result.get("scores"), dict) else {}
            fatal = [str(value) for value in (result.get("fatal_issues") or []) if str(value).strip()]
            improvements = [str(value) for value in (result.get("improvements") or []) if str(value).strip()]

            def score_value(key: str) -> int:
                try:
                    return max(0, min(100, round(float(scores.get(key, 0)))))
                except (TypeError, ValueError):
                    return 0

            product_fidelity = score_value("product_fidelity")
            visual_scores = [score_value(key) for key in (
                "realism", "composition", "typography", "commercial_readiness",
            )]
            retry_notes = [*fatal, *improvements]
            if source and body.show_product and product_fidelity < 92:
                issues.append({"code": "product_fidelity_failed", "severity": "error",
                               "message": f"产品外观一致性 {product_fidelity}/100，低于硬门槛 92"})
                retry_notes.append(
                    "Rebuild the product from the source reference without changing silhouette, proportions, colour, material, visible construction, labels or part count."
                )
            expected_copy = [
                str(value).strip() for value in public_values if str(value or "").strip()
            ]
            copy_check = result.get("copy_check") if isinstance(result.get("copy_check"), dict) else {}
            copy_accuracy = score_value("copy_accuracy")
            copy_failed = (
                (bool(expected_copy) and (copy_accuracy < 96 or copy_check.get("exact") is not True))
                or (not expected_copy and copy_check.get("unexpected_copy") is True)
            )
            if copy_failed:
                issues.append({"code": "artwork_copy_failed", "severity": "error",
                               "message": "图中文字与目标文案不完全一致，存在错字、漏字、重复或额外文字"})
                if expected_copy:
                    retry_notes.append(
                        "Preserve the composition but redraw the typography. Render exactly once and character-for-character: "
                        + " | ".join(expected_copy)
                    )
                else:
                    retry_notes.append("Remove every added headline, caption, number and marketing badge; preserve source-product labels only.")
            if result.get("verdict") != "pass" or fatal or min(visual_scores or [0]) < 80:
                issues.append({"code": "visual_review_failed", "severity": "error",
                               "message": fatal[0] if fatal else "成图审美、真实性或商业完成度未达标"})
                if not fatal and not improvements:
                    retry_notes.append("Improve realism, visual hierarchy, intentional negative space and commercial finish while preserving the product exactly.")
            vision["retry_guidance"] = retry_notes[:6]
        else:
            fidelity_required = bool(source and body.show_product)
            issues.append({
                "code": "product_fidelity_unverified" if fidelity_required else "visual_review_unavailable",
                "severity": "error" if fidelity_required else "warning",
                "message": "产品一致性复核未返回，生成图不能交付" if fidelity_required else "远程审美复核未返回，必须由人工完成审美复核",
            })
    elif not source_locked:
        vision = {"available": False, "reason": "deterministic_quality_failure"}

    errors = [issue for issue in issues if issue.get("severity") == "error"]
    score_values = (vision.get("result") or {}).get("scores") if vision.get("available") else {}
    score_numbers = []
    for value in (score_values or {}).values():
        try:
            score_numbers.append(max(0, min(100, round(float(value)))))
        except (TypeError, ValueError):
            continue
    score = round(sum(score_numbers) / len(score_numbers)) if score_numbers else (
        100 if source_locked and technical["ready"] else (70 if technical["ready"] else 0)
    )
    return {
        "ready": not errors,
        "score": score,
        "issues": issues,
        "technical": technical,
        "vision": vision,
        "retry_guidance": vision.get("retry_guidance") or [],
        "manual_visual_review_required": not source_locked and not vision.get("available"),
        "reviewed_at": time.time(),
    }


def _contact_sheet(items: list[bytes]) -> bytes:
    from PIL import Image, ImageDraw, ImageOps
    tile = 360
    cols = min(3, max(1, len(items)))
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile, rows * tile), "#E9EAEC")
    draw = ImageDraw.Draw(sheet)
    for index, raw in enumerate(items):
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        fitted = ImageOps.fit(image, (tile - 12, tile - 12), Image.Resampling.LANCZOS)
        x, y = (index % cols) * tile + 6, (index // cols) * tile + 6
        sheet.paste(fitted, (x, y))
        draw.rectangle((x + 8, y + 8, x + 42, y + 38), fill=(0, 0, 0))
        draw.text((x + 19, y + 14), str(index + 1), fill=(255, 255, 255))
    output = io.BytesIO()
    sheet.save(output, "JPEG", quality=88, optimize=True)
    return output.getvalue()


async def _set_vision_review(sheet: bytes, plan: dict) -> dict:
    if not _apimart_key():
        return {"available": False, "reason": "visual_review_provider_unconfigured"}
    roles = [str(item.get("role") or item.get("slot") or "") for item in plan.get("images") or []]
    content = [
        {"type": "text", "text": (
            "Act as a demanding ecommerce creative director reviewing this numbered contact sheet as ONE Amazon "
            "image set. Judge it against strong premium-brand listings. Reject sets that are merely unrelated AI "
            "renders, repeat the same product pose, use inconsistent aspect ratios/type scales/colour grading, have "
            "no visual narrative, contain pasted-looking copy, or fail to demonstrate the promised buyer benefit. "
            f"Intended sequence: {' | '.join(roles)}. Story: {plan.get('story') or ''}."
        )},
        _vision_block(sheet),
        {"type": "text", "text": (
            "Return JSON only: {\"scores\":{\"suite_cohesion\":0-100,\"design_system\":0-100,"
            "\"story_progression\":0-100,\"commercial_readiness\":0-100},\"fatal_issues\":[\"...\"],"
            "\"improvements\":[\"...\"],\"verdict\":\"pass|fail\"}. Pass requires every score >=80 and no "
            "fatal issue. Do not be generous."
        )},
    ]
    async with httpx.AsyncClient(timeout=httpx.Timeout(40, connect=15)) as client:
        response = await asyncio.wait_for(client.post(
                f"{_apimart_base()}/messages",
                json={"model": "claude-sonnet-4-6", "max_tokens": 1000,
                      "messages": [{"role": "user", "content": content}]},
                headers={"Authorization": f"Bearer {_apimart_key()}", "Content-Type": "application/json",
                         "anthropic-version": "2023-06-01"},
            ), timeout=45)
        response.raise_for_status()
    text = "".join(
        block.get("text", "") for block in response.json().get("content", [])
        if isinstance(block, dict) and block.get("type") == "text"
    )
    parsed = _strip_json(text)
    return {"available": bool(parsed), "result": parsed or {}, "raw": text[:500]}


@router.post("/projects/{project_id}/review-image-set")
async def review_image_set(project_id: str, body: ReviewSetReq, _user: str = Depends(require_user)):
    """Review the contact sheet so isolated acceptable images cannot masquerade as a coherent set."""
    deliverable = "aplus" if body.deliverable == "aplus" else "gallery"
    conn = _db()
    row = conn.execute("SELECT creative_sets FROM listing_projects WHERE id=?", (project_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "project not found")
    try:
        sets = json.loads(row["creative_sets"] or "{}")
        plan = sets.get(deliverable) or {}
    except Exception:
        plan = {}
    images = plan.get("images") or []
    complete = [item for item in images if item.get("final_url")]
    failed_individual = [item for item in complete if not (item.get("render_qa") or {}).get("ready")]
    issues: list[dict] = []
    if len(complete) != len(images) or not images:
        issues.append({"code": "incomplete_set", "severity": "error", "message": "整套图片尚未全部完成"})
    if failed_individual:
        issues.append({"code": "individual_failures", "severity": "error",
                       "message": f"仍有 {len(failed_individual)} 张未通过单图质检"})
    vision = {"available": False, "reason": "set_not_ready"}
    if not issues:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                raws = await asyncio.gather(*[_fetch_image_bytes(client, item["final_url"]) for item in complete])
            vision = await _set_vision_review(_contact_sheet(raws), plan)
        except Exception as exc:  # noqa: BLE001
            vision = {"available": False, "reason": str(exc)[:240]}
        if vision.get("available"):
            result = vision.get("result") or {}
            scores = result.get("scores") if isinstance(result.get("scores"), dict) else {}
            values = [int(value) for value in scores.values() if str(value).isdigit()]
            fatal = [str(value) for value in (result.get("fatal_issues") or []) if str(value).strip()]
            if result.get("verdict") != "pass" or fatal or min(values or [0]) < 80:
                issues.append({"code": "suite_review_failed", "severity": "error",
                               "message": fatal[0] if fatal else "整套设计一致性和叙事未达到商业标准"})
        else:
            issues.append({"code": "suite_review_unavailable", "severity": "warning",
                           "message": "远程整套审美复核未返回，必须由人工检查套图一致性"})
    scores = (vision.get("result") or {}).get("scores") if vision.get("available") else {}
    values = [int(value) for value in (scores or {}).values() if str(value).isdigit()]
    set_qa = {
        "ready": not any(issue.get("severity") == "error" for issue in issues),
        "score": round(sum(values) / len(values)) if values else (70 if not any(
            issue.get("severity") == "error" for issue in issues) else 0),
        "issues": issues,
        "vision": vision,
        "reviewed_at": time.time(),
    }
    plan["set_qa"] = set_qa
    _persist_shot_plan(project_id, plan, deliverable)
    return {"set_qa": set_qa, "plan": plan}


@router.post("/projects/{project_id}/overlay-callout")
async def overlay_callout_endpoint(project_id: str, body: OverlayCalloutReq, _user: str = Depends(require_user)):
    """Typeset a crisp callout onto an already-rendered (text-free) 套图 image and
    save the result. Separating text from generation keeps callouts legible,
    correctly spelled and re-editable (just call again with new text)."""
    safe_headline = _public_text(body.headline, 60) or ""
    safe_callout = _public_text(body.callout, 90) or ""
    safe_supporting = _public_text(body.supporting_text, 100) or ""
    safe_eyebrow = _public_text(body.eyebrow, 28) or ""
    safe_proof = _public_proof(body.proof) or ""
    if not body.url or not any((safe_callout, safe_headline, safe_supporting, safe_eyebrow, safe_proof)):
        raise HTTPException(400, "url 必填,且 headline / callout 至少一个")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            raw = await _fetch_image_bytes(client, body.url)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"读取底图失败：{e}")
    from app.services.listing_typography import overlay_callout
    try:
        out = overlay_callout(
            raw,
            safe_callout,
            body.text_pos,
            headline=safe_headline,
            color=body.color or "#FFFFFF",
            supporting_text=safe_supporting,
            eyebrow=safe_eyebrow,
            proof=safe_proof,
            layout_style=body.layout_style,
            accent_color=body.accent_color,
            theme=body.theme,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"文字叠加失败：{e}")
    from app.routers.image_translate import save_bytes_to_workspace
    item = save_bytes_to_workspace(out, source="listing", project_id=project_id)
    return {"url": item["url"], "id": item.get("id")}


# ─── PSD Download ─────────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/download-psd")
async def download_psd(project_id: str, body: dict, _user: str = Depends(require_user)):
    """Download an image as PSD format."""
    image_url = body.get("url")
    slot = body.get("slot", "image")
    if not image_url:
        raise HTTPException(400, "url is required")

    # Download the image
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(image_url)
            if resp.status_code != 200:
                raise HTTPException(502, "Failed to download image")
            image_bytes = resp.content
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Download failed: {e}")

    # Convert to PSD
    from PIL import Image
    from psd_tools import PSDImage

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    psd = PSDImage.frompil(img)
    buf = io.BytesIO()
    psd.save(buf)
    buf.seek(0)

    filename = f"{project_id}_{slot}.psd"
    return StreamingResponse(
        buf,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ─── Serve uploaded images ─────────────────────────────────────────────────────

@router.get("/images/{project_id}/{filename}")
def serve_image(project_id: str, filename: str):
    """Serve uploaded listing images."""
    fpath = IMAGES_DIR / project_id / filename
    if not fpath.exists():
        raise HTTPException(404)
    import mimetypes
    mime = mimetypes.guess_type(str(fpath))[0] or "image/png"
    return StreamingResponse(open(fpath, "rb"), media_type=mime)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clean_text(value) -> str:
    return " ".join(str(value or "").replace("\n", " ").split())


def _scrape_field(scrape_data: dict, key: str, default=""):
    product = scrape_data.get("product") if isinstance(scrape_data.get("product"), dict) else {}
    return scrape_data.get(key) or product.get(key) or default


def _copy_source(row, scrape_data: dict, analysis_data: dict) -> dict:
    title = _clean_text(_scrape_field(scrape_data, "title") or row["asin"])
    raw_bullets = _scrape_field(scrape_data, "bullets", [])
    if isinstance(raw_bullets, str):
        bullets = [raw_bullets]
    elif isinstance(raw_bullets, list):
        bullets = raw_bullets
    else:
        bullets = []
    manual = scrape_data.get("manual", {}) if isinstance(scrape_data.get("manual"), dict) else {}
    manual_points = [x.strip() for x in str(manual.get("selling_points") or "").splitlines() if x.strip()]
    bullets = [_clean_text(x) for x in (manual_points or bullets) if _clean_text(x)]
    description = _clean_text(manual.get("description") or _scrape_field(scrape_data, "description") or "")
    audience = _clean_text(manual.get("target_audience") or "Amazon shoppers looking for reliable, easy-to-use product performance")
    structured = analysis_data.get("structured") if isinstance(analysis_data.get("structured"), dict) else {}
    keywords = structured.get("keywords") if isinstance(structured.get("keywords"), list) else []
    usp = structured.get("usp") if isinstance(structured.get("usp"), list) else []
    return {
        "asin": row["asin"],
        "marketplace": row["marketplace"],
        "title": title,
        "bullets": bullets[:8],
        "description": description,
        "audience": audience,
        "keywords": [_clean_text(k).lower() for k in keywords if _clean_text(k)],
        "usp": [_clean_text(u) for u in usp if _clean_text(u)],
    }


def _keywords_from_text(text: str, limit: int = 36) -> list[str]:
    stop = {
        "with", "from", "that", "this", "your", "their", "and", "for", "the", "our",
        "are", "you", "not", "can", "has", "have", "will", "all", "new", "use",
        "amazon", "about", "choose", "quality", "product", "products",
    }
    words = []
    for raw in text.lower().replace("/", " ").replace("-", " ").replace(",", " ").split():
        word = "".join(ch for ch in raw if ch.isalnum())
        if len(word) < 3 or word in stop or word.isdigit():
            continue
        if word not in words:
            words.append(word)
        if len(words) >= limit:
            break
    return words


def _fallback_copy(copy_type: str, row, scrape_data: dict, analysis_data: dict) -> str:
    """Deterministic copy fallback for AI gateway 429. Output is intentionally editable."""
    src = _copy_source(row, scrape_data, analysis_data)
    title = src["title"]
    bullets = src["bullets"] or ([src["description"]] if src["description"] else [])
    feature_pool = src["usp"] + bullets
    if not feature_pool:
        feature_pool = [
            f"Designed for dependable everyday performance for ASIN {src['asin']}",
            "Built to help shoppers solve the core need shown in the product listing",
            "Easy to use, practical, and suitable for the intended Amazon marketplace",
        ]

    if copy_type == "title":
        base = title[:180].strip()
        return "\n".join([
            f"1. {base}",
            f"2. {base} for {src['audience'][:55]}".strip()[:200],
            f"3. {base} with Practical Features and Everyday Value".strip()[:200],
        ])

    if copy_type == "bullets":
        heads = ["CORE BENEFIT", "RELIABLE DESIGN", "EASY TO USE", "PRACTICAL VALUE", "BUYER READY"]
        lines = []
        for i, head in enumerate(heads):
            detail = feature_pool[i % len(feature_pool)]
            lines.append(f"{head}: {detail[:220]}")
        return "\n".join(lines)

    if copy_type == "search_terms":
        text = " ".join([title, src["description"], " ".join(bullets), " ".join(src["keywords"])])
        terms = src["keywords"] + _keywords_from_text(text)
        deduped = []
        for term in terms:
            if term and term not in deduped:
                deduped.append(term)
        out = " ".join(deduped)
        return out[:250].strip()

    if copy_type == "aplus":
        f1 = feature_pool[0]
        f2 = feature_pool[1 % len(feature_pool)]
        f3 = feature_pool[2 % len(feature_pool)]
        return f"""Brand Story
Built around practical performance and buyer confidence, this product is designed to support {src['audience']}.

Hero Banner
{title[:120]}

Feature Module 1
{f1[:260]}

Feature Module 2
{f2[:260]}

Feature Module 3
{f3[:260]}

Comparison / Advantage
Clear value, useful features, and a straightforward experience for shoppers comparing similar options.

Usage Scenarios
1. Everyday use for the primary product need.
2. Giftable or household-ready use where reliability matters.
3. Outdoor, work, travel, or category-relevant use depending on the product context."""

    raise HTTPException(400, f"type must be one of: title, bullets, search_terms, aplus")


def _build_product_context(row, scrape_data: dict, analysis_data: dict) -> str:
    """Build text context from scrape + analysis data for AI prompts."""
    parts = [f"ASIN: {row['asin']}", f"Marketplace: {row['marketplace']}"]

    if scrape_data:
        if scrape_data.get("title"):
            parts.append(f"Current Title: {scrape_data['title']}")
        if scrape_data.get("bullets"):
            bullets = scrape_data["bullets"]
            if isinstance(bullets, list):
                parts.append("Current Bullets:\n" + "\n".join(f"- {b}" for b in bullets))
        if scrape_data.get("description"):
            parts.append(f"Description: {scrape_data['description'][:500]}")
        manual = scrape_data.get("manual", {})
        if manual.get("product_name"):
            parts.append(f"Product Name: {manual['product_name']}")
        if manual.get("description"):
            parts.append(f"Product Description: {manual['description']}")
        if manual.get("selling_points"):
            parts.append(f"Selling Points: {manual['selling_points']}")
        if manual.get("target_audience"):
            parts.append(f"Target Audience: {manual['target_audience']}")

    if analysis_data:
        # Support both old format and new structured format
        if analysis_data.get("structured"):
            s = analysis_data["structured"]
            if s.get("usp"):
                parts.append(f"USP: {', '.join(s['usp'])}")
            if s.get("keywords"):
                parts.append(f"Keywords: {', '.join(s['keywords'][:15])}")
            if s.get("target_audience"):
                parts.append(f"Target Audience: {s['target_audience']}")
            if s.get("scenarios"):
                parts.append(f"Use Scenarios: {', '.join(s['scenarios'])}")
        elif analysis_data.get("analysis"):
            parts.append(f"AI Analysis: {str(analysis_data['analysis'])[:800]}")
        # imgflow data
        if analysis_data.get("imgflow"):
            imgf = analysis_data["imgflow"]
            if imgf.get("sifKeywords"):
                parts.append(f"SIF Keywords: {', '.join(imgf['sifKeywords'][:15])}")
            if imgf.get("uspExtraction"):
                parts.append(f"USP (imgflow): {imgf['uspExtraction'][:300]}")
            if imgf.get("sorftimeData"):
                parts.append(f"Sorftime Trends: {str(imgf['sorftimeData'])[:200]}")

    return "\n".join(parts)


def _approved_copy(row) -> str:
    """The user's confirmed listing copy, used as the verbatim source for on-image
    text/callouts so the images match the real listing. Prefers the advanced
    copy-job result, falls back to the simple per-field copy. Returns '' if none."""
    cols = set(row.keys()) if hasattr(row, "keys") else set()
    lines: list[str] = []

    cr = None
    if "copy_result" in cols and row["copy_result"]:
        try:
            cr = _parse_copy_result(json.loads(row["copy_result"]))
        except Exception:
            cr = None

    if isinstance(cr, dict):
        titles = cr.get("titles") or ([] if not cr.get("title") else [cr["title"]])
        if titles:
            lines.append(f"Title: {str(titles[0]).strip()}")
        bullets = (cr.get("bullets_a") or []) + (cr.get("bullets_b") or [])
        for b in bullets[:6]:
            if str(b).strip():
                lines.append(f"- {str(b).strip()}")
    else:
        if "title" in cols and row["title"]:
            first = str(row["title"]).splitlines()[0].strip()
            if first:
                lines.append(f"Title: {first}")
        if "bullets" in cols and row["bullets"]:
            for b in str(row["bullets"]).splitlines()[:6]:
                if b.strip():
                    lines.append(f"- {b.strip()}")

    return "\n".join(lines).strip()


# ═══════════════════════════════════════════════════════════════════════════════
# NEW-PRODUCT LISTING COPY GENERATOR
# Job-based workflow: images → vision analysis → competitor data → LLM copy
# ═══════════════════════════════════════════════════════════════════════════════

COPY_JOB_DB = settings.data_dir / "listing_copy_jobs.sqlite3"
COPY_IMAGES_DIR = settings.data_dir / "listing_copy_images"
COPY_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

_LISTING_RULES_FILE = Path(__file__).resolve().parents[2] / "app" / "services" / "amazon_listing_rules.md"

_AMAZON_LISTING_RULES = """# Amazon Listing Generation Rules

## Output Goal
The final deliverable must include:
- 1 generation plan/rationale
- 5 compliant Amazon titles
- 1 Product Highlights string (NEW Amazon field, effective 2026-07-27)
- 2 bullet point sets, each with exactly 5 bullet points
- 2 backend search term strings
- A compliance checklist

## Title Rules (Amazon policy effective 2026-07-27)
- Generate exactly 5 title options.
- Target the marketplace language. For US, write titles in English.
- Length: Every title MUST NOT exceed 75 characters INCLUDING spaces. This is the single hard limit for ALL categories. Count spaces.
- Mobile Optimization: Front-load the product type and 1-2 primary keywords within the first ~60 characters.
- Do NOT keyword-stuff or list specs in the title. Move secondary keywords/attributes to Product Highlights and bullets instead.
- Put "what the product IS" in the title; "what advantages it has" go in Product Highlights.
- Use title case. Do not use ALL CAPS.
- Forbidden Words: "Gift", "Free", "Bonus", "Warranty", "Hot Item", "Best Seller", "No.1", price/delivery promises.
- Do not include unsupported claims, medical claims, or subjective claims such as "best" or "top-rated".

## Product Highlights Rules (NEW field, effective 2026-07-27)
- Generate exactly 1 highlights string.
- Length: MUST NOT exceed 125 characters INCLUDING spaces.
- Use short, benefit/feature-driven PHRASES, NOT full sentences. Separate phrases with ", " (comma + space).
- Cover the most decisive of: material, core function, usage scenario, compatibility/fit, key spec.
  Example: "Non-stick, Food Grade, Heat Resistant 220°C, Fits Ninja Crispi, 100 PCS".
- This field IS searchable: naturally embed core keywords that are NOT already in the title (avoid duplication).
- It only displays on the storefront when the title is under 75 characters, so make it information-dense.

## Bullet Point Rules
- Generate exactly 2 bullet point sets.
- Set A (Conversion Focus): Focus on emotional benefits, usage scenarios, and persuasion. Use [Bold Header] for each bullet.
- Set B (Rufus/QA Focus): Focus on factual specifications, technical details, and answering shopper questions.
- Each set must contain exactly 5 bullets.
- Cover material/structure, core function, usage scenario, gift/audience fit, and risk-reducing details.
- Explicit Attributes: State key attributes in "[Attribute]: [Detail]" format.
- Avoid prohibited terms: medical claims, guaranteed outcomes, competitor attacks, prices, promotions, URLs.

## Search Term Rules
- Generate exactly 2 backend search term strings.
- Length Limit: Each string MUST be under 249 bytes. Use lowercase, space-separated terms. No commas.
- Do not repeat keywords already in the title. Prefer synonyms, spelling variants, use cases, long-tail terms.

## Output Format (JSON)
Return a JSON object with these fields:
{
  "rationale": "Strategy explanation",
  "titles": ["Title 1 (<=75 chars incl spaces)", "Title 2", "Title 3", "Title 4", "Title 5"],
  "highlights": "phrase1, phrase2, phrase3, ... (single string, <=125 chars incl spaces)",
  "bullets_a": ["Bullet 1", "Bullet 2", "Bullet 3", "Bullet 4", "Bullet 5"],
  "bullets_b": ["Bullet 1", "Bullet 2", "Bullet 3", "Bullet 4", "Bullet 5"],
  "search_terms": ["string 1 under 249 chars", "string 2 under 249 chars"],
  "compliance_notes": ["any compliance issues or notes"]
}"""


def _copy_job_db():
    conn = sqlite3.connect(str(COPY_JOB_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS copy_jobs (
        id TEXT PRIMARY KEY,
        project_id TEXT,
        status TEXT DEFAULT 'pending',
        stage INTEGER DEFAULT 0,
        stage_msg TEXT DEFAULT '',
        marketplace TEXT DEFAULT 'US',
        product_type TEXT DEFAULT '',
        asins TEXT DEFAULT '[]',
        product_notes TEXT DEFAULT '',
        image_paths TEXT DEFAULT '[]',
        vision_result TEXT,
        competitor_result TEXT,
        result TEXT,
        error TEXT,
        created_at REAL,
        updated_at REAL
    )""")
    conn.commit()
    return conn


_copy_job_db().close()

# Migration: link copy jobs to a listing project so the result can be restored
try:
    _cjc = _copy_job_db()
    _cjc.execute("ALTER TABLE copy_jobs ADD COLUMN project_id TEXT")
    _cjc.commit()
    _cjc.close()
except Exception:
    pass


class CopyJobReq(BaseModel):
    marketplace: str = "US"
    product_type: str
    asins: list[str] = []
    product_notes: str = ""
    project_id: Optional[str] = None


async def _analyze_images_vision(image_paths: list[str], product_type: str) -> dict:
    """Call vision API to analyze product images. Falls back gracefully."""
    from app.services.ai_synthesis_service import _apimart_key, _apimart_base
    import base64, httpx as hx

    if not image_paths:
        return {"mode": "skipped", "features": [], "reason": "No images provided"}

    key = _apimart_key()
    if not key:
        return {"mode": "skipped", "features": [], "reason": "No vision API configured"}

    # Build vision messages
    content: list[dict] = [
        {"type": "text", "text": (
            f"You are analyzing product images for an Amazon listing. "
            f"Product type: {product_type}. "
            f"Extract: materials, key features, dimensions/size cues, accessories included, "
            f"color options, usage scenarios visible in images. "
            f"Be specific and factual. Do not invent features not visible. "
            f"Return JSON: {{\"features\": [\"feature1\", ...], \"materials\": \"...\", "
            f"\"size_hints\": \"...\", \"accessories\": \"...\", \"scenarios\": [\"...\"]}}"
        )}
    ]
    for ip in image_paths[:6]:  # max 6 images for cost
        try:
            with open(ip, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            ext = Path(ip).suffix.lower().lstrip(".")
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/jpeg")
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
        except Exception:
            pass

    if len(content) == 1:
        return {"mode": "skipped", "features": [], "reason": "Could not read image files"}

    try:
        async with hx.AsyncClient(timeout=hx.Timeout(60, connect=10)) as client:
            resp = await asyncio.wait_for(
                client.post(
                    f"{_apimart_base()}/messages",
                    json={
                        "model": "claude-sonnet-4-6",
                        "max_tokens": 1000,
                        "messages": [{"role": "user", "content": content}],
                    },
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01",
                    },
                ),
                timeout=65,
            )
        if resp.status_code == 200:
            body = resp.json()
            text = ""
            for block in body.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    text += block.get("text", "")
            # Try to parse JSON
            import re as _re
            m = _re.search(r"\{[\s\S]*\}", text)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                    parsed["mode"] = "vision"
                    return parsed
                except Exception:
                    pass
            return {"mode": "vision", "features": [text[:500]], "raw": text}
    except Exception as exc:
        return {"mode": "error", "features": [], "reason": str(exc)}

    return {"mode": "skipped", "features": [], "reason": "Vision call failed"}


async def _fetch_competitor_data(asins: list[str], marketplace: str) -> dict:
    """Fetch competitor product/keyword data via sorftime. Fails gracefully."""
    from app.services.sorftime_service import _make_client, _safe_call
    results = {}
    errors = []
    try:
        async with _make_client() as client:
            tasks = []
            for i, asin in enumerate(asins[:5]):
                tasks.append(_safe_call(client, "product_report", {"asin": asin, "amzSite": marketplace}, i + 1))
                tasks.append(_safe_call(client, "competitor_product_keywords",
                                        {"asin": asin, "keywordSupportSite": marketplace}, i + 10))
            gathered = await asyncio.gather(*tasks)
            for name, val, err in gathered:
                if err:
                    errors.append(err)
                elif val:
                    asin_key = name
                    if asin_key not in results:
                        results[asin_key] = []
                    results[asin_key].append(val)
    except Exception as exc:
        errors.append(str(exc))
    return {"data": results, "errors": errors, "available": bool(results)}


def _build_listing_prompt(
    marketplace: str,
    product_type: str,
    product_notes: str,
    vision_result: dict,
    competitor_result: dict,
) -> str:
    parts = [
        f"You are an Amazon listing copywriting expert.",
        f"Marketplace: {marketplace}",
        f"Product Type: {product_type}",
        "",
    ]

    if product_notes:
        parts.append(f"Seller Notes (product specs/features):\n{product_notes}")
        parts.append("")

    if vision_result.get("mode") == "vision":
        features = vision_result.get("features", [])
        if features:
            parts.append(f"Image Analysis - Observed Features:\n" + "\n".join(f"- {f}" for f in features[:20]))
        materials = vision_result.get("materials", "")
        if materials:
            parts.append(f"Materials: {materials}")
        scenarios = vision_result.get("scenarios", [])
        if scenarios:
            parts.append(f"Visible Use Scenarios: {', '.join(scenarios[:5])}")
        parts.append("")

    if competitor_result.get("available"):
        comp_data = competitor_result.get("data", {})
        parts.append("Competitor Data (from market research):")
        parts.append(json.dumps(comp_data, ensure_ascii=False)[:3000])
        parts.append("")

    parts.append(_AMAZON_LISTING_RULES)
    parts.append("")
    parts.append("Now generate the listing copy. Return ONLY valid JSON, no other text.")

    return "\n".join(parts)


async def _run_copy_job(job_id: str) -> None:
    """Background task: vision → competitor → LLM → save result."""
    import httpx as hx

    def update(stage: int, msg: str, **kwargs):
        conn = _copy_job_db()
        conn.execute(
            "UPDATE copy_jobs SET stage=?, stage_msg=?, updated_at=?, status=? WHERE id=?",
            (stage, msg, time.time(), kwargs.get("status", "running"), job_id),
        )
        conn.commit()
        conn.close()

    try:
        conn = _copy_job_db()
        row = dict(conn.execute("SELECT * FROM copy_jobs WHERE id=?", (job_id,)).fetchone())
        conn.close()

        image_paths = json.loads(row.get("image_paths", "[]"))
        asins = json.loads(row.get("asins", "[]"))
        marketplace = row.get("marketplace", "US")
        product_type = row.get("product_type", "")
        product_notes = row.get("product_notes", "")

        # Stage 0: Vision
        update(0, "正在分析产品图片…" if image_paths else "未上传图片，跳过图片识别")
        vision_result = await _analyze_images_vision(image_paths, product_type)

        conn = _copy_job_db()
        conn.execute("UPDATE copy_jobs SET vision_result=? WHERE id=?",
                     (json.dumps(vision_result, ensure_ascii=False), job_id))
        conn.commit()
        conn.close()

        # Stage 1: Competitor data
        update(1, "正在查询竞品数据…" if asins else "未填写竞品ASIN，跳过竞品查询")
        competitor_result = await _fetch_competitor_data(asins, marketplace) if asins else {
            "data": {}, "errors": [], "available": False
        }

        conn = _copy_job_db()
        conn.execute("UPDATE copy_jobs SET competitor_result=? WHERE id=?",
                     (json.dumps(competitor_result, ensure_ascii=False), job_id))
        conn.commit()
        conn.close()

        # Stage 2: LLM generation
        update(2, "正在生成文案…")
        prompt = _build_listing_prompt(marketplace, product_type, product_notes, vision_result, competitor_result)

        # Try DeepSeek first, then apimart
        from app.services.ai_synthesis_service import (
            _deepseek_key, _apimart_key, _apimart_base, _stream_openai_compat
        )
        result_text = ""

        dk = _deepseek_key()
        if dk:
            try:
                async for chunk in _stream_openai_compat(dk, "https://api.deepseek.com", "deepseek-chat", prompt):
                    result_text += chunk
            except Exception:
                result_text = ""

        if not result_text:
            ak = _apimart_key()
            if ak:
                try:
                    async with hx.AsyncClient(timeout=hx.Timeout(120, connect=10)) as client:
                        resp = await client.post(
                            f"{_apimart_base()}/messages",
                            json={"model": "claude-sonnet-4-6", "max_tokens": 4096,
                                  "messages": [{"role": "user", "content": prompt}]},
                            headers={"Authorization": f"Bearer {ak}", "Content-Type": "application/json",
                                     "anthropic-version": "2023-06-01"},
                        )
                        resp.raise_for_status()
                        body = resp.json()
                        for block in body.get("content", []):
                            if isinstance(block, dict) and block.get("type") == "text":
                                result_text += block.get("text", "")
                except Exception:
                    pass

        if not result_text:
            raise RuntimeError("所有AI提供商均不可用，请在系统配置中设置 deepseek_api_key 或 apimart_key")

        # Parse JSON from result
        import re as _re
        parsed_result = _parse_copy_result(result_text)
        if not parsed_result:
            parsed_result = {"raw": result_text}

        result_json = json.dumps(parsed_result, ensure_ascii=False)
        conn = _copy_job_db()
        conn.execute(
            "UPDATE copy_jobs SET status='done', stage=3, stage_msg='文案生成完成', result=?, updated_at=? WHERE id=?",
            (result_json, time.time(), job_id),
        )
        conn.commit()
        conn.close()

        # Persist the result onto the linked project so it survives page refresh.
        project_id = row.get("project_id")
        if project_id:
            try:
                pconn = _db()
                pconn.execute(
                    "UPDATE listing_projects SET copy_result=?, copy_job_id=?, updated_at=? WHERE id=?",
                    (result_json, job_id, time.time(), project_id),
                )
                pconn.commit()
                pconn.close()
            except Exception:
                pass

    except Exception as exc:
        conn = _copy_job_db()
        conn.execute(
            "UPDATE copy_jobs SET status='failed', stage_msg=?, error=?, updated_at=? WHERE id=?",
            (str(exc), str(exc), time.time(), job_id),
        )
        conn.commit()
        conn.close()


# ─── Copy Job API ────────────────────────────────────────────────────────────

@router.get("/copy-jobs")
def list_copy_jobs(_user: str = Depends(require_user)):
    conn = _copy_job_db()
    rows = conn.execute(
        "SELECT id, status, stage, stage_msg, marketplace, product_type, error, created_at, updated_at "
        "FROM copy_jobs ORDER BY created_at DESC LIMIT 30"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.post("/copy-jobs")
async def create_copy_job(body: CopyJobReq, _user: str = Depends(require_user)):
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    asins = [a.strip().upper() for a in body.asins if a.strip()][:10]
    conn = _copy_job_db()
    conn.execute(
        "INSERT INTO copy_jobs (id, project_id, status, stage, stage_msg, marketplace, product_type, "
        "asins, product_notes, image_paths, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (job_id, body.project_id, "pending", 0, "等待开始", body.marketplace,
         body.product_type.strip(), json.dumps(asins),
         body.product_notes.strip(), "[]", now, now),
    )
    conn.commit()
    conn.close()
    return {"job_id": job_id, "status": "pending"}


@router.post("/copy-jobs/{job_id}/images")
async def upload_copy_job_images(
    job_id: str,
    files: list[UploadFile] = File(...),
    _user: str = Depends(require_user),
):
    conn = _copy_job_db()
    row = conn.execute("SELECT * FROM copy_jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "job not found")
    if row["status"] not in ("pending", "uploaded"):
        raise HTTPException(400, "job already started")

    img_dir = COPY_IMAGES_DIR / job_id
    img_dir.mkdir(exist_ok=True)
    saved_paths = json.loads(row["image_paths"] or "[]")

    for f in files[:10]:
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            continue
        content = await f.read()
        if len(content) > 10 * 1024 * 1024:
            continue
        fname = f"{uuid.uuid4().hex[:8]}{ext}"
        dest = img_dir / fname
        dest.write_bytes(content)
        saved_paths.append(str(dest))

    conn = _copy_job_db()
    conn.execute("UPDATE copy_jobs SET image_paths=?, status='uploaded', updated_at=? WHERE id=?",
                 (json.dumps(saved_paths), time.time(), job_id))
    conn.commit()
    conn.close()
    return {"job_id": job_id, "image_count": len(saved_paths)}


@router.post("/copy-jobs/{job_id}/start")
async def start_copy_job(job_id: str, _user: str = Depends(require_user)):
    conn = _copy_job_db()
    row = conn.execute("SELECT * FROM copy_jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "job not found")
    if row["status"] not in ("pending", "uploaded"):
        raise HTTPException(400, f"job status is {row['status']}, cannot start")

    conn = _copy_job_db()
    conn.execute("UPDATE copy_jobs SET status='running', stage=0, stage_msg='启动中…', updated_at=? WHERE id=?",
                 (time.time(), job_id))
    conn.commit()
    conn.close()

    asyncio.create_task(_run_copy_job(job_id))
    return {"job_id": job_id, "status": "running"}


@router.get("/copy-jobs/{job_id}")
def get_copy_job(job_id: str, _user: str = Depends(require_user)):
    conn = _copy_job_db()
    row = conn.execute("SELECT * FROM copy_jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "job not found")
    d = dict(row)
    for key in ("asins", "image_paths", "result", "vision_result", "competitor_result"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except Exception:
                pass
    if d.get("result"):
        d["result"] = _parse_copy_result(d["result"]) or d["result"]
    return d


@router.delete("/copy-jobs/{job_id}")
def delete_copy_job(job_id: str, _user: str = Depends(require_user)):
    # Clean up images
    img_dir = COPY_IMAGES_DIR / job_id
    if img_dir.exists():
        import shutil
        shutil.rmtree(img_dir, ignore_errors=True)
    conn = _copy_job_db()
    conn.execute("DELETE FROM copy_jobs WHERE id=?", (job_id,))
    conn.commit()
    conn.close()
    return {"ok": True}

    return "\n\n".join(parts)
