import { useState } from "react";
import { competitorLookup } from "../../../api/deepAnalysis";

const MARKETPLACES = ["US", "UK", "DE", "CA", "JP", "FR", "ES", "IT", "MX", "AU"];

export default function CompetitorLookup() {
  const [asin, setAsin] = useState("");
  const [country, setCountry] = useState("US");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<any>(null);

  const run = async () => {
    if (!asin.trim() || loading) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const res = await competitorLookup({ asin: asin.trim(), country });
      setResult(res.data);
    } catch (e: any) {
      setError(e?.message || "请求失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>⊗ 竞品反查</div>

      <div className="market-input-row" style={{ flexWrap: "wrap" }}>
        <input
          className="market-query-input"
          value={asin}
          onChange={(e) => setAsin(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="输入竞品 ASIN"
          disabled={loading}
        />
        <select className="market-query-input" style={{ flex: "1 1 80px", minWidth: 0 }} value={country} onChange={(e) => setCountry(e.target.value)}>
          {MARKETPLACES.map((m) => <option key={m}>{m}</option>)}
        </select>
        <button className="market-btn market-btn-submit" onClick={run} disabled={loading || !asin.trim()}>
          {loading ? "反查中…" : "开始反查"}
        </button>
      </div>

      {error && <div className="market-error" style={{ marginTop: 10 }}>{error}</div>}
      {loading && <div className="pulse-loading" style={{ marginTop: 10 }}><span className="pulse-spin">◌</span> 正在反查竞品关键词…</div>}

      {result && (
        <div style={{ marginTop: 14 }}>
          <div className="card" style={{ background: "var(--bg2)" }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 10 }}>
              「{asin}」关键词信号分析
            </div>

            {/* Traffic Terms */}
            {result.traffic_terms && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 10, color: "var(--t2)", marginBottom: 6 }}>流量关键词</div>
                {typeof result.traffic_terms === "string" ? (
                  <div style={{ fontSize: 10, lineHeight: 1.6, color: "var(--t)" }}>{result.traffic_terms}</div>
                ) : Array.isArray(result.traffic_terms) ? (
                  <div style={{ fontSize: 10 }}>
                    {result.traffic_terms.slice(0, 20).map((t: any, i: number) => (
                      <div key={i} style={{ padding: "3px 6px", background: "var(--bg3)", borderRadius: 4, marginBottom: 3 }}>
                        {typeof t === "string" ? t : t.keyword || t.关键词 || JSON.stringify(t).substring(0, 50)}
                      </div>
                    ))}
                  </div>
                ) : (
                  <pre style={{ fontSize: 9, maxHeight: 200, overflow: "auto", padding: 8, background: "var(--bg)", borderRadius: 4 }}>
                    {JSON.stringify(result.traffic_terms, null, 2)}
                  </pre>
                )}
              </div>
            )}

            {/* Competitor Keywords */}
            {result.competitor_keywords && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 10, color: "var(--t2)", marginBottom: 6 }}>竞品关键词</div>
                {typeof result.competitor_keywords === "string" ? (
                  <div style={{ fontSize: 10, lineHeight: 1.6, color: "var(--t)" }}>{result.competitor_keywords}</div>
                ) : Array.isArray(result.competitor_keywords) ? (
                  <div style={{ fontSize: 10, overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse" }}>
                      <thead>
                        <tr style={{ borderBottom: "1px solid var(--b)" }}>
                          <th style={{ textAlign: "left", padding: "4px 6px" }}>关键词</th>
                          <th style={{ textAlign: "right", padding: "4px 6px" }}>排名</th>
                          <th style={{ textAlign: "right", padding: "4px 6px" }}>流量占比</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.competitor_keywords.slice(0, 15).map((kw: any, i: number) => (
                          <tr key={i} style={{ borderBottom: "1px solid var(--line)" }}>
                            <td style={{ padding: "4px 6px", fontFamily: "monospace" }}>
                              {typeof kw === "string" ? kw : kw.keyword || kw.关键词 || "-"}
                            </td>
                            <td style={{ padding: "4px 6px", textAlign: "right" }}>
                              {typeof kw === "object" ? (kw.rank || kw.排名 || "-") : "-"}
                            </td>
                            <td style={{ padding: "4px 6px", textAlign: "right" }}>
                              {typeof kw === "object" ? (kw.share || kw.流量占比 || "-") : "-"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <pre style={{ fontSize: 9, maxHeight: 200, overflow: "auto", padding: 8, background: "var(--bg)", borderRadius: 4 }}>
                    {JSON.stringify(result.competitor_keywords, null, 2)}
                  </pre>
                )}
              </div>
            )}

            {/* Product Detail */}
            {result.product_detail && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 10, color: "var(--t2)", marginBottom: 6 }}>产品信息</div>
                <div style={{ fontSize: 10, lineHeight: 1.6, color: "var(--t)" }}>
                  {typeof result.product_detail === "string" ? result.product_detail.substring(0, 500) : JSON.stringify(result.product_detail).substring(0, 500)}
                </div>
              </div>
            )}

            {/* Errors */}
            {result.errors?.length > 0 && (
              <div style={{ marginBottom: 10, fontSize: 10, color: "var(--amber)" }}>
                {result.errors.map((e: string, i: number) => <div key={i}>⚠ {e}</div>)}
              </div>
            )}

            <details style={{ marginTop: 12 }}>
              <summary style={{ fontSize: 10, color: "var(--t3)", cursor: "pointer" }}>查看原始 JSON</summary>
              <pre style={{ fontSize: 9, maxHeight: 300, overflow: "auto", padding: 8, background: "var(--bg)", borderRadius: 4, marginTop: 4 }}>
                {JSON.stringify(result, null, 2)}
              </pre>
            </details>
          </div>
        </div>
      )}
    </div>
  );
}
