import { useEffect, useMemo, useState } from "react";
import {
  CheckResult, Diff, Locator, ProductInfo, UploadInfo,
  clearUploads, deleteUpload, getProductInfo, highlightUrl, listUploads, reportUrl, runCheck, uploadFiles,
} from "./api";

const KIND_COLORS: Record<string, string> = {
  "一致": "diff-match",
  "構造図のみ": "diff-only",
  "計算書のみ": "diff-only",
  "断面幅不一致": "diff-section",
  "配筋不一致": "diff-rebar",
  "要目視確認": "diff-review",
  "スラブ厚不一致": "diff-section",
  "スラブ配筋不一致": "diff-rebar",
};

// フィルタに常時表示する種別と順序（該当0件でも表示する）。
// 不整合 → 一致 → 計算書のみ → 構造図のみ の順。
const BEAM_KINDS = [
  "配筋不一致", "断面幅不一致", "要目視確認", "一致", "計算書のみ", "構造図のみ",
];
const SLAB_KINDS = [
  "スラブ配筋不一致", "スラブ厚不一致", "一致", "計算書のみ", "構造図のみ",
];

const FOUNDATION_PREFIX = /^(?:FB|FCG|FG)/;
const CANTILEVER_PREFIX = /^(?:CB|WCB)\d/;
const WALLBEAM_PREFIX = /^(?:WB)\d/;

type CompareTarget = { mark: string; drawing?: Locator | null; calc?: Locator | null };

export default function App() {
  const [product, setProduct] = useState<ProductInfo | null>(null);
  const [uploads, setUploads] = useState<{ drawing: UploadInfo[]; calc: UploadInfo[] }>({ drawing: [], calc: [] });
  const [result, setResult] = useState<CheckResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hideFoundation, setHideFoundation] = useState(false);
  const [hideCantilever, setHideCantilever] = useState(false);
  const [hideWallBeam, setHideWallBeam] = useState(false);
  // 非表示にする種別。既定で「一致」を隠す（不整合のみ表示）。
  const [hiddenKinds, setHiddenKinds] = useState<Set<string>>(new Set(["一致"]));
  const [highlight, setHighlight] = useState<CompareTarget | null>(null);
  const [reporting, setReporting] = useState<"beam" | "slab" | null>(null);
  // 出力範囲: ON のとき表示中の項目のみ出力する
  const [reportFiltered, setReportFiltered] = useState(true);

  const refresh = () => listUploads().then(setUploads).catch((e) => setError(String(e)));
  useEffect(() => {
    getProductInfo().then(setProduct).catch((e) => setError(String(e)));
    refresh();
  }, []);

  const toggleKind = (k: string) => {
    setHiddenKinds((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k); else next.add(k);
      return next;
    });
  };

  const handleUpload = async (role: "drawing" | "calc", files: File[]) => {
    const pdfs = files.filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    if (pdfs.length === 0) {
      setError("PDFファイルを選んでください");
      return;
    }
    setError(null);
    try {
      await uploadFiles(role, pdfs);
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  };

  const handleDelete = async (id: string) => {
    await deleteUpload(id);
    await refresh();
  };

  const handleClear = async () => {
    await clearUploads();
    setResult(null);
    await refresh();
  };

  const handleCheck = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult(await runCheck());
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  // 小梁: 部材プレフィックス除外 + 種別フィルタ
  const beamDiffs = useMemo<Diff[]>(() => {
    if (!result) return [];
    return result.diffs.filter((d) => {
      if (hideFoundation && FOUNDATION_PREFIX.test(d.mark)) return false;
      if (hideCantilever && CANTILEVER_PREFIX.test(d.mark)) return false;
      if (hideWallBeam && WALLBEAM_PREFIX.test(d.mark)) return false;
      if (hiddenKinds.has(d.kind)) return false;
      return true;
    });
  }, [result, hideFoundation, hideCantilever, hideWallBeam, hiddenKinds]);

  // スラブ: 種別フィルタのみ
  const slabDiffs = useMemo<Diff[]>(() => {
    if (!result) return [];
    return result.slab_diffs.filter((d) => !hiddenKinds.has(d.kind));
  }, [result, hiddenKinds]);

  const openCompare = (mark: string, drawing?: Locator | null, calc?: Locator | null) => {
    if (!drawing?.file_id && !calc?.file_id) return;
    setHighlight({ mark, drawing, calc });
  };

  const handleReport = async (category: "beam" | "slab") => {
    setReporting(category);
    setError(null);
    try {
      // 「表示中の項目のみ出力」が ON のとき、フィルタ後の符号一覧を渡す。
      // 「一致」を表示している場合は「一致」も含めて出力する。
      let marks: string[] | undefined;
      if (reportFiltered) {
        const list = category === "beam" ? beamDiffs : slabDiffs;
        marks = list.map((d) => d.mark);
      }
      const r = await fetch(reportUrl(category, marks));
      if (!r.ok) {
        const msg = await r.text();
        throw new Error(msg || "レポート生成に失敗しました");
      }
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const ts = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 12);
      const label = category === "beam" ? "小梁" : "スラブ";
      a.href = url;
      a.download = `yhg_report_${label}_${ts}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(String(e));
    } finally {
      setReporting(null);
    }
  };

  const canCheck = uploads.drawing.length > 0 && uploads.calc.length > 0;

  const isStub = product?.mode === "stub";

  return (
    <div className="container">
      <header className="app-header">
        <div className="app-title">{product?.name ?? "YHG"}</div>
        <div className="app-subtitle">{product?.subtitle ?? "構造図・計算書 整合チェックツール（RC小梁・スラブ）"}</div>
      </header>

      {isStub ? (
        <div className="card">
          <h2>実装準備中</h2>
          <p>
            <b>{product?.name}</b> は現在開発準備中です。
            梁スリーブ貫通補強の計算書サンプルPDFが揃い次第、パーサと整合チェックロジックを実装します。
          </p>
          <p className="hint">
            このウィンドウを閉じて、構造図・計算書の整合チェックには <b>YHG.exe</b> をご利用ください。
          </p>
        </div>
      ) : (
      <>
      <div className="steps-guide">
        <div className="step"><span className="step-no">1</span>構造図・計算書PDFを入れる</div>
        <div className="step-arrow">→</div>
        <div className="step"><span className="step-no">2</span>「整合チェック実行」を押す</div>
        <div className="step-arrow">→</div>
        <div className="step"><span className="step-no">3</span>差分を確認・PDFで照合</div>
      </div>

      {error && <div className="card error">{error}</div>}

      <div className="card">
        <h2><span className="badge">1</span>PDFを入れる</h2>
        <p className="hint">
          構造図PDF・計算書PDFを下の枠にドラッグ＆ドロップ、または「ファイルを選ぶ」で追加します。
          複数ファイルをまとめて入れられます。
          <b>計算書は「小梁計算書」と「スラブ計算書」の両方</b>を入れると、小梁・スラブ両方の照合ができます。
        </p>
        <div className="dropzones">
          <DropZone role="drawing" title="構造図PDF（二次部材リスト）"
                    files={uploads.drawing} onUpload={handleUpload} onDelete={handleDelete} />
          <DropZone role="calc" title="計算書PDF（小梁計算書・スラブ計算書）"
                    files={uploads.calc} onUpload={handleUpload} onDelete={handleDelete} />
        </div>
        <div className="row">
          <button className="primary" onClick={handleCheck} disabled={busy || !canCheck}>
            {busy ? "照合中... (20〜30秒)" : "整合チェック実行"}
          </button>
          {(uploads.drawing.length > 0 || uploads.calc.length > 0) && (
            <button className="ghost" onClick={handleClear} disabled={busy}>すべて消去</button>
          )}
          {!canCheck && <span className="hint" style={{ margin: 0 }}>構造図・計算書を両方入れると実行できます</span>}
        </div>
      </div>

      {result && (
        <div className="card">
          <div className="card-h2-row">
            <h2><span className="badge">2</span>整合チェック結果 — 小梁</h2>
            <div className="report-controls">
              <label className="kind-check" title="OFF にすると種別フィルタ・部材除外を無視し、全差分を出力します">
                <input type="checkbox" checked={reportFiltered}
                       onChange={(e) => setReportFiltered(e.target.checked)} />
                表示中の項目のみ出力
              </label>
              <button className="secondary" onClick={() => handleReport("beam")}
                      disabled={reporting !== null}>
                {reporting === "beam" ? "生成中... (10〜30秒)" : "小梁をPDF出力"}
              </button>
            </div>
          </div>
          <p className="hint">
            「配筋不一致」「断面幅不一致」は要修正候補、「要目視確認」はPDF目視が必要なもの、
            「構造図のみ／計算書のみ」は片方にしか無い符号、「一致」は整合済みです。
            各行の「PDFで照合」ボタンで構造図と計算書の該当箇所を並べて表示します。
            右上の<b>「小梁をPDF出力」</b>で差分をまとめたPDFをダウンロードできます。
          </p>
          <p>
            構造図: <b>{result.drawing_member_count}</b> 部材 /
            計算書: <b>{result.calc_member_count}</b> 部材 /
            不整合: <b>{result.diff_count}</b> 件（表示中: <b>{beamDiffs.length}</b> 件）
          </p>
          <FilterBar
            diffs={result.diffs} allKinds={BEAM_KINDS}
            hiddenKinds={hiddenKinds} onToggleKind={toggleKind}
            prefixFilters={[
              { label: "基礎部材（FB/FCG/FG）を除外", checked: hideFoundation, onChange: setHideFoundation },
              { label: "片持小梁（CB/WCB）を除外", checked: hideCantilever, onChange: setHideCantilever },
              { label: "壁梁（WB）を除外", checked: hideWallBeam, onChange: setHideWallBeam },
            ]}
          />
          <DiffTable diffs={beamDiffs} onCompare={openCompare} />
        </div>
      )}

      {result && (
        <div className="card">
          <div className="card-h2-row">
            <h2><span className="badge">3</span>整合チェック結果 — スラブ</h2>
            <div className="report-controls">
              <label className="kind-check" title="OFF にすると種別フィルタを無視し、全差分を出力します">
                <input type="checkbox" checked={reportFiltered}
                       onChange={(e) => setReportFiltered(e.target.checked)} />
                表示中の項目のみ出力
              </label>
              <button className="secondary" onClick={() => handleReport("slab")}
                      disabled={reporting !== null}>
                {reporting === "slab" ? "生成中... (10〜30秒)" : "スラブをPDF出力"}
              </button>
            </div>
          </div>
          {result.calc_slab_count === 0 && (
            <div className="notice">
              計算書側にスラブのデータが見つかりません。スラブの厚さ・配筋を照合するには、
              「スラブ計算書PDF」も計算書欄にアップロードして再実行してください。
            </div>
          )}
          <p>
            構造図: <b>{result.drawing_slab_count}</b> 枚 /
            計算書: <b>{result.calc_slab_count}</b> 枚 /
            不整合: <b>{result.slab_diff_count}</b> 件（表示中: <b>{slabDiffs.length}</b> 件）
          </p>
          <FilterBar
            diffs={result.slab_diffs} allKinds={SLAB_KINDS}
            hiddenKinds={hiddenKinds} onToggleKind={toggleKind} />
          <DiffTable diffs={slabDiffs} onCompare={openCompare} />
        </div>
      )}

      {highlight && (
        <div className="modal-backdrop" onClick={() => setHighlight(null)}>
          <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <span><b>{highlight.mark}</b>　<span className="muted">構造図と計算書を並べて照合</span></span>
              <button className="close" onClick={() => setHighlight(null)}>閉じる</button>
            </div>
            <div className="modal-body compare-body">
              <ComparePane title="構造図" loc={highlight.drawing} />
              <ComparePane title="計算書" loc={highlight.calc} />
            </div>
          </div>
        </div>
      )}
      </>
      )}
    </div>
  );
}

function ComparePane({ title, loc }: { title: string; loc?: Locator | null }) {
  return (
    <div className="compare-pane">
      <div className="compare-pane-head">
        {title}
        {loc?.file_id ? <span className="muted">　p.{loc.page}</span> : null}
      </div>
      <div className="compare-pane-img">
        {loc?.file_id
          ? <img src={highlightUrl(loc)} alt={title} />
          : <div className="compare-empty">この符号に該当する記載がありません</div>}
      </div>
    </div>
  );
}

function FilterBar({
  diffs, allKinds, hiddenKinds, onToggleKind, prefixFilters,
}: {
  diffs: Diff[];
  allKinds: string[];
  hiddenKinds: Set<string>;
  onToggleKind: (k: string) => void;
  prefixFilters?: { label: string; checked: boolean; onChange: (v: boolean) => void }[];
}) {
  const counts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const d of diffs) m[d.kind] = (m[d.kind] ?? 0) + 1;
    return m;
  }, [diffs]);
  return (
    <div className="filterbar">
      <div className="filter-group">
        <span className="filter-label">表示する種別:</span>
        {allKinds.map((k) => (
          <label key={k} className="kind-check">
            <input type="checkbox" checked={!hiddenKinds.has(k)} onChange={() => onToggleKind(k)} />
            <span className={`diff-kind ${KIND_COLORS[k] ?? ""}`}>{k}</span>
            <span className="kind-count">{counts[k] ?? 0}</span>
          </label>
        ))}
      </div>
      {prefixFilters && prefixFilters.length > 0 && (
        <div className="filter-group">
          <span className="filter-label">部材で除外:</span>
          {prefixFilters.map((pf) => (
            <label key={pf.label} className="kind-check">
              <input type="checkbox" checked={pf.checked} onChange={(e) => pf.onChange(e.target.checked)} />
              {pf.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function DropZone({
  role, title, files, onUpload, onDelete,
}: {
  role: "drawing" | "calc";
  title: string;
  files: UploadInfo[];
  onUpload: (role: "drawing" | "calc", files: File[]) => void;
  onDelete: (id: string) => void;
}) {
  const [over, setOver] = useState(false);
  const inputId = `file-${role}`;

  return (
    <div className="dropzone-wrap">
      <div className="dropzone-title">{title}</div>
      <div
        className={over ? "dropzone over" : "dropzone"}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          onUpload(role, Array.from(e.dataTransfer.files));
        }}
        onClick={() => document.getElementById(inputId)?.click()}
      >
        <div className="dropzone-icon">＋</div>
        <div className="dropzone-text">ここにPDFをドラッグ＆ドロップ</div>
        <div className="dropzone-sub">またはクリックしてファイルを選ぶ（複数可）</div>
        <input
          id={inputId}
          type="file"
          accept="application/pdf"
          multiple
          style={{ display: "none" }}
          onChange={(e) => {
            onUpload(role, Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
      </div>
      {files.length > 0 && (
        <ul className="filelist">
          {files.map((f) => (
            <li key={f.id}>
              <span className="filelist-name">{f.name}</span>
              <button className="filelist-del" onClick={() => onDelete(f.id)} title="削除">×</button>
            </li>
          ))}
        </ul>
      )}
      {files.length === 0 && <div className="filelist-empty">まだファイルがありません</div>}
    </div>
  );
}

function DiffTable({
  diffs, onCompare,
}: {
  diffs: Diff[];
  onCompare: (mark: string, drawing?: Locator | null, calc?: Locator | null) => void;
}) {
  if (diffs.length === 0) {
    return <p className="muted">表示できる項目がありません（フィルタを確認してください）</p>;
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
              {d.fields.length === 0 && (d.drawing_loc?.file_id || d.calc_loc?.file_id) && (
                <div className="row" style={{ marginTop: 4 }}>
                  <button className="link" onClick={() => onCompare(d.mark, d.drawing_loc, d.calc_loc)}>
                    PDFで照合
                  </button>
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
                    {(f.drawing_loc?.file_id || f.calc_loc?.file_id) && (
                      <button className="link" onClick={() => onCompare(d.mark, f.drawing_loc, f.calc_loc)}>
                        PDFで照合
                      </button>
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
