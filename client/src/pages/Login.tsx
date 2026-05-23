import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../api/client";

export default function Login() {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(username, password);
      navigate("/");
    } catch (err: any) {
      setError(err?.response?.data?.detail || "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="login-box" onSubmit={onSubmit}>
        <div className="mark">OPS WORKBENCH</div>
        <h1>
          欢迎回来 · <b>ops-hub</b>
        </h1>

        <label>USERNAME</label>
        <input
          className="inp"
          autoFocus
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
        />

        <label>PASSWORD</label>
        <input
          className="inp"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />

        {error && <div className="err">✗ {error}</div>}

        <button type="submit" disabled={loading || !password}>
          {loading ? (
            <>
              <span className="spin" style={{ marginRight: 8 }} />
              SIGNING IN...
            </>
          ) : (
            "→ SIGN IN"
          )}
        </button>
      </form>
    </div>
  );
}
