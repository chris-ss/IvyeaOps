import type { TourStep } from "../components/Tour";

/**
 * Interactive tours, keyed by route pathname. Each board's tour auto-runs on the
 * user's first visit (once, remembered in localStorage) and can be replayed via
 * the "?" button in the top bar.
 *
 * Steps target elements by a stable CSS selector (existing class or a
 * `[data-tour="…"]` attribute added on the element); a step without `sel` shows
 * a centered intro card. A selector that matches nothing also renders centered,
 * so steps degrade gracefully.
 *
 * To add a board: add an entry here (+ tag its key element with `data-tour="…"`
 * if it has no stable class).
 */
export const TOURS: Record<string, TourStep[]> = {
  // ── 控制台总览（首页）─────────────────────────────────────────────────────
  "/": [
    {
      title: "欢迎使用 IvyeaOps 👋",
      body: "一台服务器、一次登录，把亚马逊运营全流程收进浏览器。\n这个快速引导带你认识控制台。3 步就能开始用：\n① 配一个 AI 模型  ② 配数据源  ③ 去任意板块开干。",
    },
    { sel: '[data-tour="sidebar"]', title: "左侧 = 所有板块入口", body: "按「工具 / AI & 系统 / 小工具 / 管理」分组。点任意一项进入对应板块；左下角按钮可折叠侧边栏。" },
    { sel: '.sb a[href="/hub-settings"]', title: "第一步：系统配置", body: "新装后先来这里：配一个「全局兜底大模型」（DeepSeek/OpenAI 等任选）+ 数据源 Key。配好这两样，全站 AI 与数据功能就能用了。" },
    { sel: ".home-tabs", title: "首页 · 运营驾驶舱", body: "每日盯盘面板：大盘流量 / 关键词 / 竞品监控 / 自有 ASIN / 类目大盘 五个标签页。点标签切换不同维度。" },
    { sel: '[data-tour="home-source"]', title: "数据源 & 站点", body: "右上角选站点和数据源（Sorftime）。切换数据源会重新加载全部数据。" },
    { sel: '[data-tour="tour-help"]', title: "随时查手册 / 重看引导", body: "📖 是使用手册（各板块详细文档）。旁边的「?」可随时重看当前板块的这个引导。" },
  ],

  // ── 系统配置 ───────────────────────────────────────────────────────────────
  "/hub-settings": [
    { title: "系统配置：全站的总开关", body: "这里集中配置模型、数据源、集成路径等。每个区块独立保存，点该区块的「保存」即时生效。新用户重点看下面两处。" },
    { sel: '[data-tour="settings-fallback"]', title: "★ 全局兜底大模型（最重要）", body: "所有板块文本 AI 的统一出口。选一个 provider（推荐 DeepSeek：快、便宜、国内直连）+ 填 Key，全站 AI 立即可用。数据源 Key（Sorftime）也在附近的「数据源」区配。" },
    { sel: '[data-tour="settings-health"]', title: "健康检查", body: "一眼看清各服务与 AI 链的就绪状态（文本链 / 全局兜底 / 视觉）。配完回这里确认对应项变绿即可。" },
  ],

  // ── 市场调研 ───────────────────────────────────────────────────────────────
  "/market": [
    { title: "市场调研", body: "输入关键词或 ASIN，一键生成结构化的市场调研报告（市场规模、竞争格局、机会风险、SWOT、行动清单）。" },
    { sel: ".market-query-input", title: "输入调研对象", body: "选「关键词 / ASIN」模式，填入内容，并在右侧选数据源与站点。" },
    { sel: ".market-btn-submit", title: "生成报告", body: "点这里开始生成。AI 走标准降级链（Hermes 优先，失败自动切全局兜底模型），过程会流式输出。" },
    { title: "深入分析 & 历史", body: "出报告后，报告下方会出现「深入分析」：选一个角度 + 智能体，把整份报告带进「智能体会话」继续追问。历史记录自动保存，可随时载入 / 导出。" },
  ],

  // ── Listing 工作台 ───────────────────────────────────────────────────────────
  "/listing": [
    { title: "Listing 工作台", body: "从竞品 ASIN 到整套文案 + 图片提示词的流水线，按 ① 采集 → ② 文案 → ③ 主图 → ④ A+ → ⑤ 输出 顺序走。" },
    { sel: '[data-tour="listing-tabs"]', title: "五步流程", body: "顶部这排就是流程步骤。每步完成后点下一步推进；采集会抓竞品文案与图片（有 imgflow 直抓，无则回退 Sorftime）。" },
    { title: "开始：新建 / 选 ASIN", body: "左侧填竞品 ASIN 新建项目，点「采集 ASIN 数据」开始。之后文案、主图提示词、A+ 都基于采集 + AI 分析逐步生成。" },
  ],
};

/** Whether a board at `pathname` has a tour. */
export function hasTour(pathname: string): boolean {
  return Array.isArray(TOURS[pathname]) && TOURS[pathname].length > 0;
}
