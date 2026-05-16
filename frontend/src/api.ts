// 本番ビルドでは FastAPI が同一オリジンでフロントを配信するため空文字（相対パス）。
// 開発時 (vite dev) は VITE_API_BASE=http://localhost:8000 を指定する。
const BASE = import.meta.env.VITE_API_BASE ?? "";

export type Project = { id: number; name: string; created_at?: string };

export type Locator = {
  page: number;
  bbox?: [number, number, number, number] | null;
  search?: string | null;
};

export type FieldDiff = {
  field: string;
  drawing_value: string | null;
  calc_value: string | null;
  drawing_loc?: Locator | null;
  calc_loc?: Locator | null;
};

export type Diff = {
  kind: string;     // "図のみ" / "計算書のみ" / "断面幅B不一致" / "配筋不一致"
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
};

export function highlightUrl(projectId: number, role: "drawing" | "calc", loc: Locator): string {
  const params = new URLSearchParams();
  params.set("role", role);
  params.set("page", String(loc.page));
  if (loc.bbox) {
    params.set("x0", String(loc.bbox[0]));
    params.set("y0", String(loc.bbox[1]));
    params.set("x1", String(loc.bbox[2]));
    params.set("y1", String(loc.bbox[3]));
  }
  if (loc.search) params.set("search", loc.search);
  return `${BASE}/api/projects/${projectId}/highlight?${params.toString()}`;
}

export async function listProjects(): Promise<Project[]> {
  const r = await fetch(`${BASE}/api/projects`);
  return r.json();
}

export async function createProject(name: string): Promise<Project> {
  const fd = new FormData();
  fd.append("name", name);
  const r = await fetch(`${BASE}/api/projects`, { method: "POST", body: fd });
  return r.json();
}

export async function uploadFile(projectId: number, role: "drawing" | "calc", file: File) {
  const fd = new FormData();
  fd.append("role", role);
  fd.append("file", file);
  const r = await fetch(`${BASE}/api/projects/${projectId}/uploads`, { method: "POST", body: fd });
  return r.json();
}

export async function runCheck(projectId: number): Promise<CheckResult> {
  const fd = new FormData();
  fd.append("calc_software", "structuresuite");
  const r = await fetch(`${BASE}/api/projects/${projectId}/check`, { method: "POST", body: fd });
  return r.json();
}
