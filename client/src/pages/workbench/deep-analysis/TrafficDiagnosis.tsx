import { useState } from "react";
import { trafficDiagnosis } from "../../../api/deepAnalysis";

const MARKETPLACES = ["US", "UK", "DE", "CA", "JP", "FR", "ES", "IT", "MX", "AU"];

export default function TrafficDiagnosis() {
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
      const res = await trafficDiagnosis({ asin: asin.trim(), country });
      setResult(res.data);
    } catch (e: any) {
      setError(e?.message || "请求失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>⊘ 流量异动诊断</div>

      <div className="market-input-row" style={{ flexWrap: "wrap" }}>
        <input
          className="market-query-input"
          value={asin}
          onChange={(e) => setAsin(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="输入 ASIN，如 B0XXXXXXXX"
          disabled={loading}
        />
        <select className="market-query-input" style={{ flex: "1 1 80px", minWidth: 0 }} value={country} onChange={(e) => setCountry(e.target.value)}>
          {MARKETPLACES.map((m) => <option key={m}>{m}</option>)}
        </select>
        <button className="market-btn market-btn-submit" onClick={run} disabled={loading || !asin.trim()}>
          {loading ? "诊断中…" : "开始诊断"}
        </button>
      </div>

      {error && <div className="market-error" style={{ marginTop: 10 }}>{error}</div>}
      {loading && <div className="pulse-loading" style={{ marginTop: 10 }}><span className="pulse-spin">◌</span> 正在分析流量数据…</div>}

      {result && (
        <div style={{ marginTop: 14 }}>
          <div className="card" style={{ background: "var(--bg2)" }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 10 }}>
              「{asin}」流量诊断报告
            </div>

            {/* Traffic Terms */}
            {result.traffic_terms && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 10, color: "var(--t2)", marginBottom: 6 }}>流量关键词</div>
                {typeof result.traffic_terms === "string" ? (
                  <div style={{ fontSize: 10, lineHeight: 1.6, color: "var(--t)" }}>{result.traffic_terms}</div>
                ) : Array.isArray(result.traffic_terms) ? (
                  <div style={{ fontSize: 10 }}>
                    {result.traffic_terms.slice(0, 15).map((t: any, i: number) => (
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

            {/* Trend */}
            {result.trend && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 10, color: "var(--t2)", marginBottom: 6 }}>销量/流量趋势</div>
                {typeof result.trend === "string" ? (
                  <div style={{ fontSize: 10, lineHeight: 1.6, color: "var(--t)" }}>{result.trend}</div>
                ) : (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4, fontSize: 10 }}>
                    {Object.entries(result.trend).map(([k, v]) => (
                      <div key={k} style={{ padding: "4px 8px", background: "var(--bg3)", borderRadius: 4 }}>
                        <span style={{ color: "var(--t3)" }}>{k}: </span>
                        <span style={{ color: "var(--t)" }}>
                          {typeof v === "object" ? JSON.stringify(v).substring(0, 60) : String(v)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Report */}
            {result.report && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 10, color: "var(--t2)", marginBottom: 6 }}>产品报告</div>
                <div style={{ fontSize: 10, lineHeight: 1.6, color: "var(--t)" }}>
                  {typeof result.report === "string" ? result.report.substring(0, 800) : JSON.stringify(result.report).substring(0, 800)}
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
              <pre style={{ fontSize: 9, maxHeight: 400, overflow: "auto", padding: 8, background: "var(--bg)", borderRadius: 4, marginTop: 4 }}>
                {JSON.stringify(result, null, 2)}
              </pre>
            </details>
          </div>
        </div>
      )}
    </div>
  );
}
