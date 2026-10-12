import type { AnalysisResult } from "./types";

async function responseError(response: Response): Promise<Error> {
  const body = (await response.json().catch(() => ({}))) as {
    detail?: unknown;
  };
  return new Error(
    typeof body.detail === "string"
      ? body.detail
      : `请求失败（${response.status}）`,
  );
}

export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw await responseError(response);
  return response.json() as Promise<T>;
}

export async function analyze(
  input: { question: string; device_id: string; session_id?: string },
  onEvent: (
    event: string,
    data: Record<string, unknown> | AnalysisResult,
  ) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/analysis", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    signal,
  });
  if (!response.ok) throw await responseError(response);
  if (!response.body) throw new Error("浏览器无法读取分析流");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let completed = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
      let boundary: number;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const event = block
          .split("\n")
          .find((line) => line.startsWith("event:"))
          ?.slice(6)
          .trim();
        const raw = block
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim())
          .join("\n");
        if (!event || !raw) continue;
        const data = JSON.parse(raw) as Record<string, unknown>;
        if (event === "error") throw new Error(String(data.message));
        if (event === "result") completed = true;
        onEvent(event, data);
      }
      if (done) break;
    }
    if (!completed) throw new Error("分析连接已中断，请重新提交任务");
  } finally {
    reader.releaseLock();
  }
}
