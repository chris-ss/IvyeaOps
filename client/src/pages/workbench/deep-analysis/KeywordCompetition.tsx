import { useState } from "react";
import { keywordCompetition } from "../../../api/deepAnalysis";

const MARKETPLACES = ["US", "UK", "DE", "CA", "JP", "FR", "ES", "IT", "MX", "AU"];

export default function KeywordCompetition() {
  const [keyword, setKeyword] = useState("");
  const [country, setCountry] = useState("US");
  const [asin, setAsin] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<any>(null);

  const run = async () => {
    if (!keyword.trim() || loading) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const res = await keywordCompetition({ keyword: keyword.trim(), country, asin: asin.trim() });
      setResult(res.data);
    } catch (e: any) {
      setError(e?.message || "请求失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>⊕ 关键词竞争分析</div>

      <div className="market-input-row" style={{ flexWrap: "wrap" }}>
        <input
          className="market-query-input"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="输入关键词，如: trail camera"
          disabled={loading}
        />
        <select
          className="market-query-input"
          style={{ flex: "1 1 80px", minWidth: 0 }}
          value={country}
          onChange={(e) => setCountry(e.target.value)}
        >
          {MARKETPLACES.map((m) => (
            <option key={m}>{m}</option>
          ))}
        </select>
        <button className="market-btn market-btn-submit" onClick={run} disabled={loading || !keyword.trim()}>
          {loading ? "分析中…" : "开始分析"}
        </button>
      </div>

      {error && <div className="market-error" style={{ marginTop: 10 }}>{error}</div>}
      {loading && <div className="pulse-loading" style={{ marginTop: 10 }}><span className="pulse-spin">◌</span> 正在分析关键词数据…</div>}

      {result && (
        <div style={{ marginTop: 14 }}>
          <ResultDisplay data={result} keyword={keyword} />
        </div>
      )}
    </div>
  );
}

function ResultDisplay({ data, keyword }: { data: any; keyword: string }) {
  const trend = data?.trend || {};
  const extendsList = data?.extends || [];
  const searchResults = data?.search_results || [];
  const detail = data?.detail || "";
  const errors = data?.errors || [];

  return (
    <div className="card" style={{ background: "var(--bg2)" }}>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 10 }}>
        「{keyword}」关键词分析
      </div>

      {/* Errors */}
      {errors.length > 0 && (
        <div style={{ marginBottom: 10, fontSize: 10, color: "var(--amber)" }}>
          {errors.map((e: string, i: number) => <div key={i}>⚠ {e}</div>)}
        </div>
      )}

      {/* Keyword Detail */}
      {detail && detail !== "没有相关数据" && (
        <div style={{ marginBottom: 12, padding: 10, background: "var(--bg3)", borderRadius: 4, fontSize: 10, lineHeight: 1.6 }}>
          <div style={{ color: "var(--t2)", marginBottom: 4 }}>关键词详情</div>
          <div style={{ color: "var(--t)" }}>{typeof detail === "string" ? detail : JSON.stringify(detail)}</div>
        </div>
      )}

      {/* Trend Data */}
      {trend && Object.keys(trend).length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 10, color: "var(--t2)", marginBottom: 6 }}>趋势数据</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, fontSize: 10 }}>
            {Object.entries(trend).map(([k, v]) => (
              <div key={k} style={{ padding: "4px 8px", background: "var(--bg3)", borderRadius: 4 }}>
                <span style={{ color: "var(--t3)" }}>{k}: </span>
                <span style={{ color: "var(--t)" }}>
                  {typeof v === "object" ? JSON.stringify(v).substring(0, 60) : String(v)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Extended Keywords */}
      {extendsList.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 10, color: "var(--t2)", marginBottom: 6 }}>扩展关键词 ({extendsList.length})</div>
          <div style={{ fontSize: 10, overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--b)" }}>
                  <th style={{ textAlign: "left", padding: "4px 6px" }}>关键词</th>
                  <th style={{ textAlign: "right", padding: "4px 6px" }}>搜索量</th>
                  <th style={{ textAlign: "right", padding: "4px 6px" }}>竞争度</th>
                </tr>
              </thead>
              <tbody>
                {extendsList.slice(0, 15).map((kw: any, i: number) => (
                  <tr key={i} style={{ borderBottom: "1px solid var(--line)" }}>
                    <td style={{ padding: "4px 6px", fontFamily: "monospace" }}>
                      {typeof kw === "string" ? kw : kw.keyword || kw.关键词 || JSON.stringify(kw).substring(0, 30)}
                    </td>
                    <td style={{ padding: "4px 6px", textAlign: "right" }}>
                      {typeof kw === "object" ? (kw.searchVolume || kw.搜索量 || "-") : "-"}
                    </td>
                    <td style={{ padding: "4px 6px", textAlign: "right" }}>
                      {typeof kw === "object" ? (kw.competition || kw.竞争度 || "-") : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Search Results */}
      {searchResults.length > 0 && (
        <div>
          <div style={{ fontSize: 10, color: "var(--t2)", marginBottom: 6 }}>搜索结果 Top ASIN ({searchResults.length})</div>
          <div style={{ fontSize: 10, overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--b)" }}>
                  <th style={{ textAlign: "left", padding: "4px 6px" }}>#</th>
                  <th style={{ textAlign: "left", padding: "4px 6px" }}>ASIN</th>
                  <th style={{ textAlign: "left", padding: "4px 6px" }}>标题</th>
                  <th style={{ textAlign: "right", padding: "4px 6px" }}>价格</th>
                </tr>
              </thead>
              <tbody>
                {searchResults.slice(0, 10).map((item: any, i: number) => (
                  <tr key={i} style={{ borderBottom: "1px solid var(--line)" }}>
                    <td style={{ padding: "4px 6px", color: "var(--t3)" }}>{i + 1}</td>
                    <td style={{ padding: "4px 6px", fontFamily: "monospace", fontSize: 9 }}>
                      {item.asin || item.ASIN || "-"}
                    </td>
                    <td style={{ padding: "4px 6px", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {item.title || item.标题 || "-"}
                    </td>
                    <td style={{ padding: "4px 6px", textAlign: "right" }}>
                      {item.price || item.价格 || "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* No data */}
      {(!detail || detail === "没有相关数据") && extendsList.length === 0 && searchResults.length === 0 && (
        <div style={{ fontSize: 10, color: "var(--t3)", padding: 10 }}>
          暂无数据。Sorftime 可能未收录该关键词。
        </div>
      )}

      {/* Raw JSON toggle */}
      <details style={{ marginTop: 12 }}>
        <summary style={{ fontSize: 10, color: "var(--t3)", cursor: "pointer" }}>查看原始 JSON</summary>
        <pre style={{ fontSize: 9, maxHeight: 300, overflow: "auto", padding: 8, background: "var(--bg)", borderRadius: 4, marginTop: 4 }}>
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
    </div>
  );
}
