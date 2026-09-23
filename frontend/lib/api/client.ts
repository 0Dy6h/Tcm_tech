function canonicalHeaderName(name: string) {
  const lowerName = name.toLowerCase();
  if (lowerName === "content-type") {
    return "Content-Type";
  }
  if (lowerName === "accept") {
    return "Accept";
  }
  return name;
}

export function buildApiHeaders(extra?: HeadersInit): Record<string, string> {
  const headers: Record<string, string> = {};
  new Headers(extra).forEach((value, key) => {
    if (key.toLowerCase() === "x-access-token") {
      return;
    }
    headers[canonicalHeaderName(key)] = value;
  });
  return headers;
}

function isInternalApiTarget(input: URL | RequestInfo, internalBaseUrl: string) {
  try {
    const inputUrl =
      input instanceof URL ? input.toString() : typeof input === "string" ? input : input.url;
    return new URL(inputUrl, internalBaseUrl).origin === new URL(internalBaseUrl).origin;
  } catch {
    return false;
  }
}

// 带 HTTP 状态码的请求错误：让 UI 能区分 404（资源不存在/不可见）与网络/服务故障，
// 而不是把所有失败折叠成「后端未启动」。
export class ApiStatusError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiStatusError";
    this.status = status;
  }
}

export function getBackendBaseUrl() {
  if (typeof window === "undefined") {
    const internal = (process.env.QIYAN_INTERNAL_API_BASE_URL ?? "").trim();
    if (internal) return internal;
  }
  return process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || "http://127.0.0.1:8010";
}

export function describeApiError(error: unknown, action: string): string {
  if (error instanceof ApiStatusError) {
    const hints: Record<number, string> = {
      401: "请检查预览登录状态与访问权限。",
      403: "当前请求没有访问权限，请检查预览登录状态。",
      404: "资源不存在或当前不可见，请刷新页面确认。",
      409: "数据已更新，请刷新页面后再试。",
      413: "文件超过上传限制，请选择不超过 20 MB 的 PDF。",
      415: "文件格式不受支持，请选择有效的 PDF 文件。",
      422: "提交内容未通过校验，请检查输入后重试。",
      429: "请求过于频繁，请稍后重试。",
    };
    return `${action}失败（HTTP ${error.status}），${hints[error.status] ?? "服务端暂时无法处理，请稍后重试；若持续出现，请检查后端服务（端口 8010）日志。"}`;
  }
  return error instanceof TypeError
    ? `${action}失败，请确认后端服务已启动（默认端口 8010）且网络可达，然后重试。`
    : `${action}失败，请稍后重试。`;
}

export function apiFetch(input: URL | RequestInfo, init: RequestInit = {}): Promise<Response> {
  const headers = buildApiHeaders(init.headers);
  if (typeof window === "undefined") {
    const internalToken = (process.env.QIYAN_INTERNAL_API_TOKEN ?? "").trim();
    const internalBaseUrl = (process.env.QIYAN_INTERNAL_API_BASE_URL ?? "").trim();
    if (internalToken && internalBaseUrl && isInternalApiTarget(input, internalBaseUrl)) {
      headers["X-Access-Token"] = internalToken;
    }
  }
  return fetch(input, {
    ...init,
    headers,
  });
}
