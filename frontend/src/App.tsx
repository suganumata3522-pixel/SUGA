import { useEffect, useState } from "react";
import { CheckResult, Project, createProject, listProjects, runCheck, uploadFile } from "./api";

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [current, setCurrent] = useState<Project | null>(null);
  const [drawing, setDrawing] = useState<File | null>(null);
  const [calc, setCalc] = useState<File | null>(null);
  const [software, setSoftware] = useState<"ss" | "structuresuite">("ss");
  const [result, setResult] = useState<CheckResult | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { listProjects().then(setProjects); }, []);

  const handleCreate = async () => {
    if (!name) return;
    const p = await createProject(name);
    setName("");
    setProjects(await listProjects());
    setCurrent(p);
  };

  const handleCheck = async () => {
    if (!current) return;
    setBusy(true);
    try {
      if (drawing) await uploadFile(current.id, "drawing", drawing);
      if (calc) await uploadFile(current.id, "calc", calc);
      const r = await runCheck(current.id, software);
      setResult(r);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="container">
      <h1>SUGA - 構造図 / 計算書 整合チェック</h1>

      <div className="card">
        <h2>プロジェクト</h2>
        <div className="row">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="案件名（例: ○○マンション）" />
          <button onClick={handleCreate}>新規作成</button>
        </div>
        <table>
          <thead><tr><th>ID</th><th>案件名</th><th>選択</th></tr></thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id}>
                <td>{p.id}</td>
                <td>{p.name}</td>
                <td><button onClick={() => setCurrent(p)}>{current?.id === p.id ? "選択中" : "選ぶ"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {current && (
        <div className="card">
          <h2>ファイルアップロード — {current.name}</h2>
          <div className="row">
            <label>構造図PDF:
              <input type="file" accept="application/pdf" onChange={(e) => setDrawing(e.target.files?.[0] ?? null)} />
            </label>
          </div>
          <div className="row">
            <label>計算書PDF:
              <input type="file" accept="application/pdf" onChange={(e) => setCalc(e.target.files?.[0] ?? null)} />
            </label>
            <label>計算ソフト:
              <select value={software} onChange={(e) => setSoftware(e.target.value as "ss" | "structuresuite")}>
                <option value="ss">SS7 / SS3</option>
                <option value="structuresuite">StructureSuite</option>
              </select>
            </label>
            <button onClick={handleCheck} disabled={busy || (!drawing && !calc)}>{busy ? "照合中..." : "整合チェック実行"}</button>
          </div>
        </div>
      )}

      {result && (
        <div className="card">
          <h2>結果</h2>
          <p>図: {result.drawing_member_count} 部材 / 計算書: {result.calc_member_count} 部材 / 差分: <b>{result.diff_count}</b> 件</p>
          <table>
            <thead><tr><th>種別</th><th>分類</th><th>符号</th><th>階</th><th>差分</th></tr></thead>
            <tbody>
              {result.diffs.map((d, i) => (
                <tr key={i}>
                  <td className={`diff-kind ${d.kind.includes("断面") ? "diff-section" : d.kind.includes("配筋") ? "diff-rebar" : "diff-only"}`}>{d.kind}</td>
                  <td>{d.category}</td>
                  <td>{d.mark}</td>
                  <td>{d.floor ?? "-"}</td>
                  <td>
                    {d.fields.map((f, j) => (
                      <div key={j}><code>{f.field}</code>: 図 <b>{f.drawing_value ?? "-"}</b> / 計算 <b>{f.calc_value ?? "-"}</b></div>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
