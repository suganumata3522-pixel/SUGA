// 本番ビルドでは FastAPI が同一オリジンでフロントを配信するため空文字（相対パス）。
// 開発時 (vite dev) は VITE_API_BASE=http://localhost:8000 を指定する。
const BASE = import.meta.env.VITE_API_BASE ?? "";

export type Locator = {
  page: number;
  bbox?: [number, number, number, number] | null;
  // 差分位置（フィールド単位）。bbox は部材全体(橙枠)、diff_bbox は差分箇所(赤枠)。
  diff_bbox?: [number, number, number, number] | null;
  search?: string | null;
  file_id?: string | null;
};

export type FieldDiff = {
  field: string;
  drawing_value: string | null;
  calc_value: string | null;
  drawing_loc?: Locator | null;
  calc_loc?: Locator | null;
};

export type Diff = {
  kind: string;
  mark: string;
  fields: FieldDiff[];
  note?: string | null;
  drawing_loc?: Locator | null;
  calc_loc?: Locator | null;
};

export type CheckResult = {
  drawing_member_count: number;
  calc_member_count: number;
  diff_count: number;
  diffs: Diff[];
  drawing_slab_count: number;
  calc_slab_count: number;
  slab_diff_count: number;
  slab_diffs: Diff[];
  warnings?: string[];
};

export type UploadInfo = { id: string; name: string; role: "drawing" | "calc" };

export type ProductInfo = {
  kind: "core" | "sleeve";
  name: string;
  subtitle: string;
  fastapi_title: string;
  data_dirname: string;
  port: number;
  mode: "active" | "stub";
};

export async function getProductInfo(): Promise<ProductInfo> {
  const r = await fetch(`${BASE}/api/product-info`);
  if (!r.ok) throw new Error("製品情報の取得に失敗しました");
  return r.json();
}

export function highlightUrl(loc: Locator): string {
  const params = new URLSearchParams();
  params.set("page", String(loc.page));
  if (loc.bbox) {
    params.set("x0", String(loc.bbox[0]));
    params.set("y0", String(loc.bbox[1]));
    params.set("x1", String(loc.bbox[2]));
    params.set("y1", String(loc.bbox[3]));
  }
  if (loc.diff_bbox) {
    params.set("dx0", String(loc.diff_bbox[0]));
    params.set("dy0", String(loc.diff_bbox[1]));
    params.set("dx1", String(loc.diff_bbox[2]));
    params.set("dy1", String(loc.diff_bbox[3]));
  }
  if (loc.search) params.set("search", loc.search);
  return `${BASE}/api/highlight/${loc.file_id}?${params.toString()}`;
}

export function reportUrl(category: "beam" | "slab", marks?: string[]): string {
  const params = new URLSearchParams();
  params.set("category", category);
  if (marks) params.set("marks", marks.join(","));
  return `${BASE}/api/report.pdf?${params.toString()}`;
}

export async function listUploads(): Promise<{ drawing: UploadInfo[]; calc: UploadInfo[] }> {
  const r = await fetch(`${BASE}/api/uploads`);
  if (!r.ok) throw new Error("一覧の取得に失敗しました");
  return r.json();
}

export async function uploadFiles(role: "drawing" | "calc", files: File[]): Promise<UploadInfo[]> {
  const fd = new FormData();
  fd.append("role", role);
  for (const f of files) fd.append("files", f);
  const r = await fetch(`${BASE}/api/uploads`, { method: "POST", body: fd });
  if (!r.ok) throw new Error("アップロードに失敗しました");
  return r.json();
}

export async function deleteUpload(id: string): Promise<void> {
  const r = await fetch(`${BASE}/api/uploads/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error("削除に失敗しました");
}

export async function clearUploads(): Promise<void> {
  await fetch(`${BASE}/api/uploads/clear`, { method: "POST" });
}

export async function runCheck(): Promise<CheckResult> {
  const r = await fetch(`${BASE}/api/check`, { method: "POST" });
  if (!r.ok) {
    const msg = await r.text();
    throw new Error(msg || "整合チェックに失敗しました");
  }
  return r.json();
}
