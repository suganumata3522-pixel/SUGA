const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export type Project = { id: number; name: string; created_at?: string };

export type FieldDiff = {
  field: string;
  drawing_value: string | null;
  calc_value: string | null;
};

export type Diff = {
  kind: string;     // "図のみ" / "計算書のみ" / "断面幅B不一致" / "配筋不一致"
  mark: string;
  fields: FieldDiff[];
  note?: string | null;  // 計算書の備考（例: "1F 駐輪場・ENT"）
};

export type CheckResult = {
  drawing_member_count: number;
  calc_member_count: number;
  diff_count: number;
  diffs: Diff[];
};

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
