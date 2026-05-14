const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export type Project = { id: number; name: string; created_at?: string };

export type Diff = {
  kind: string;
  category: string;
  mark: string;
  floor: string | null;
  fields: { field: string; drawing_value: string | null; calc_value: string | null }[];
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

export async function runCheck(projectId: number, calcSoftware: "ss" | "structuresuite"): Promise<CheckResult> {
  const fd = new FormData();
  fd.append("calc_software", calcSoftware);
  const r = await fetch(`${BASE}/api/projects/${projectId}/check`, { method: "POST", body: fd });
  return r.json();
}
