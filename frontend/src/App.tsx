import { useEffect, useMemo, useState } from "react";
import { CheckResult, Diff, Locator, Project, createProject, highlightUrl, listProjects, runCheck, uploadFile } from "./api";

const KIND_COLORS: Record<string, string> = {
  "図のみ": "diff-only",
  "計算書のみ": "diff-only",
  "断面幅B不一致": "diff-section",
  "配筋不一致": "diff-rebar",
  "要目視確認": "diff-review",
  "スラブ厚不一致": "diff-section",
  "スラブ配筋不一致": "diff-rebar",
};

const FOUNDATION_PREFIX = /^(?:FB|FCG|FG)/;
const CANTILEVER_PREFIX = /^(?:CB|WCB)\d/;
const WALLBEAM_PREFIX = /^(?:WB)\d/;

type HighlightTarget = {
  projectId: number;
  role: "drawing" | "calc";
  loc: Locator;
  mark: string;
};

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [current, setCurrent] = useState<Project | null>(null);
  const [drawing, setDrawing] = useState<File | null>(null);
  const [calc, setCalc] = useState<File | null>(null);
  const [result, setResult] = useState<CheckResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hideFoundation, setHideFoundation] = useState(true);
  const [hideCalcOnly, setHideCalcOnly] = useState(false);
  const [hideCantilever, setHideCantilever] = useState(false);
  const [hideWallBeam, setHideWallBeam] = useState(false);
  const [highlight, setHighlight] = useState<HighlightTarget | null>(null);

  useEffect(() => {
    listProjects().then(setProjects).catch((e) => setError(String(e)));
  }, []);

  const handleCreate = async () => {
    if (!name) return;
    try {
      const p = await createProject(name);
      setName("");
      setProjects(await listProjects());
      setCurrent(p);
    } catch (e) {
      setError(String(e));
    }
  };

  const handleCheck = async () => {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      if (drawing) await uploadFile(current.id, "drawing", drawing);
      if (calc) await uploadFile(current.id, "calc", calc);
      const r = await runCheck(current.id);
      setResult(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const filteredDiffs = useMemo<Diff[]>(() => {
    if (!result) return [];
    return result.diffs.filter((d) => {
      if (hideFoundation && FOUNDATION_PREFIX.test(d.mark)) return false;
      if (hideCantilever && CANTILEVER_PREFIX.test(d.mark)) return false;
      if (hideWallBeam && WALLBEAM_PREFIX.test(d.mark)) return false;
      if (hideCalcOnly && d.kind === "計算書のみ") return false;
      return true;
    });
  }, [result, hideFoundation, hideCantilever, hideWallBeam, hideCalcOnly]);

  const openHighlight = (role: "drawing" | "calc", loc: Locator | null | undefined, mark: string) => {
    if (!loc || !current) return;
    setHighlight({ projectId: current.id, role, loc, mark });
  };

  return (
    <div className="container">
      <h1>SUGA - 構造図 / 計算書 整合チェック（RC小梁）</h1>
      {error && <div className="card error">{error}</div>}

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
            <label>構造図PDF（二次部材リスト）:
              <input type="file" accept="application/pdf" onChange={(e) => setDrawing(e.target.files?.[0] ?? null)} />
            </label>
          </div>
          <div className="row">
            <label>計算書PDF（StructureSuite 小梁）:
              <input type="file" accept="application/pdf" onChange={(e) => setCalc(e.target.files?.[0] ?? null)} />
            </label>
            <button onClick={handleCheck} disabled={busy || (!drawing && !calc)}>
              {busy ? "照合中..." : "整合チェック実行"}
            </button>
          </div>
        </div>
      )}

      {result && (
        <div className="card">
          <h2>結果 — 小梁</h2>
          <p>
            構造図: <b>{result.drawing_member_count}</b> 部材 /
            計算書: <b>{result.calc_member_count}</b> 部材 /
            差分: <b>{result.diff_count}</b> 件
            （表示中: <b>{filteredDiffs.length}</b> 件）
          </p>
          <div className="row">
            <label><input type="checkbox" checked={hideFoundation} onChange={(e) => setHideFoundation(e.target.checked)} />
              基礎部材（FB/FCG/FG）を除外
            </label>
            <label><input type="checkbox" checked={hideCantilever} onChange={(e) => setHideCantilever(e.target.checked)} />
              片持小梁（CB/WCB）を除外
            </label>
            <label><input type="checkbox" checked={hideWallBeam} onChange={(e) => setHideWallBeam(e.target.checked)} />
              壁梁（WB）を除外
            </label>
            <label><input type="checkbox" checked={hideCalcOnly} onChange={(e) => setHideCalcOnly(e.target.checked)} />
              「計算書のみ」を除外
            </label>
          </div>
          <DiffTable diffs={filteredDiffs} onHighlight={openHighlight} />
        </div>
      )}

      {result && (
        <div className="card">
          <h2>結果 — スラブ</h2>
          <p>
            構造図: <b>{result.drawing_slab_count}</b> 枚 /
            計算書: <b>{result.calc_slab_count}</b> 枚 /
            差分: <b>{result.slab_diff_count}</b> 件
          </p>
          <DiffTable diffs={result.slab_diffs} onHighlight={openHighlight} />
        </div>
      )}

      {highlight && (
        <div className="modal-backdrop" onClick={() => setHighlight(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <b>{highlight.mark}</b> — {highlight.role === "drawing" ? "構造図" : "計算書"} p.{highlight.loc.page}
              <button className="close" onClick={() => setHighlight(null)}>閉じる</button>
            </div>
            <div className="modal-body">
              <img src={highlightUrl(highlight.projectId, highlight.role, highlight.loc)} alt={highlight.mark} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function DiffTable({
  diffs,
  onHighlight,
}: {
  diffs: Diff[];
  onHighlight: (role: "drawing" | "calc", loc: Locator | null | undefined, mark: string) => void;
}) {
  if (diffs.length === 0) {
    return <p className="muted">差分なし</p>;
  }
  return (
    <table>
      <thead><tr><th>種別</th><th>符号</th><th>備考(計算書)</th><th>差分</th></tr></thead>
      <tbody>
        {diffs.map((d, i) => (
          <tr key={i}>
            <td className={`diff-kind ${KIND_COLORS[d.kind] ?? ""}`}>{d.kind}</td>
            <td>
              <b>{d.mark}</b>
              {d.fields.length === 0 && (
                <div className="row" style={{ marginTop: 4 }}>
                  {d.drawing_loc && (
                    <button className="link" onClick={() => onHighlight("drawing", d.drawing_loc!, d.mark)}>図 p.{d.drawing_loc.page}</button>
                  )}
                  {d.calc_loc && (
                    <button className="link" onClick={() => onHighlight("calc", d.calc_loc!, d.mark)}>計算 p.{d.calc_loc.page}</button>
                  )}
                </div>
              )}
            </td>
            <td className="muted">{d.note ?? ""}</td>
            <td>
              {d.fields.length === 0 && <span className="muted">—</span>}
              {d.fields.map((f, j) => (
                <div key={j} className="field-diff">
                  <code>{f.field}</code>: 図 <b>{f.drawing_value ?? "—"}</b> / 計算 <b>{f.calc_value ?? "—"}</b>
                  <span className="field-actions">
                    {f.drawing_loc && (
                      <button className="link" onClick={() => onHighlight("drawing", f.drawing_loc!, `${d.mark} / ${f.field}`)}>図</button>
                    )}
                    {f.calc_loc && (
                      <button className="link" onClick={() => onHighlight("calc", f.calc_loc!, `${d.mark} / ${f.field}`)}>計算</button>
                    )}
                  </span>
                </div>
              ))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
