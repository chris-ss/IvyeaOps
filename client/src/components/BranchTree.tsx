import { AgentSession } from "../api/agents";

type Props = {
  sessions: AgentSession[];
  currentId: string | null;
  onSelect: (sid: string) => void;
};

// Render the session list as a tree: top-level sessions on the left edge,
// branches indented under their parent.  We compute the tree client-side
// from the flat /agent-sessions list — the API stays simple, the tree is
// purely a render concern.
export default function BranchTree({ sessions, currentId, onSelect }: Props) {
  const childrenOf = new Map<string | null, AgentSession[]>();
  for (const s of sessions) {
    const key = s.parent_id || null;
    const arr = childrenOf.get(key) || [];
    arr.push(s);
    childrenOf.set(key, arr);
  }
  // Sort each group by updated_at desc so recent sessions float up.
  for (const arr of childrenOf.values()) {
    arr.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  }
  const roots = childrenOf.get(null) || [];

  const render = (sess: AgentSession, depth: number): JSX.Element[] => {
    const out: JSX.Element[] = [];
    const active = sess.id === currentId;
    const dateStr = sess.created_at?.replace("T", " ").slice(0, 16) || "";
    out.push(
      <button
        key={sess.id}
        onClick={() => onSelect(sess.id)}
        className={"sess-row" + (active ? " active" : "") + (sess.live ? " live" : "")}
        style={{ paddingLeft: 10 + depth * 14 }}
        title={sess.title + " · " + sess.agent_id}
      >
        {depth > 0 && <span className="sr-arr">↳</span>}
        <span className="sr-dot">●</span>
        <span className="sr-title">
          {sess.title}
          <span className="sr-date">{dateStr}</span>
        </span>
        <span className="sr-tag">{sess.agent_id}</span>
      </button>,
    );
    const kids = childrenOf.get(sess.id) || [];
    for (const k of kids) {
      out.push(...render(k, depth + 1));
    }
    return out;
  };

  return (
    <div style={{ padding: "4px 0" }}>
      {roots.flatMap((r) => render(r, 0))}
      {!roots.length && (
        <div style={{ padding: 16, color: "var(--t3)", fontSize: 10, textAlign: "center", lineHeight: 1.7 }}>
          暂无会话
          <br />
          点击上方「+ 新建」开始
        </div>
      )}
    </div>
  );
}
