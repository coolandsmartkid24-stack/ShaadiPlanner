// Client for the Shaadi Planner API (backend on 127.0.0.1:8010, reached through the Vite proxy).
// The token decides everything on the SERVER (allowances, passes, ownership) - the UI only shows
// what the API answers. A 401 clears the session and hands control back to the login screen.

const KEY = "sp.session";

let store = load();
let unauthorized = null;

function load() {
  try {
    const v = JSON.parse(localStorage.getItem(KEY));
    return v && v.token ? v : null;
  } catch {
    return null;
  }
}

function persist() {
  try {
    if (store) localStorage.setItem(KEY, JSON.stringify(store));
    else localStorage.removeItem(KEY);
  } catch {
    /* private mode: keep the session in memory only */
  }
}

export const getSession = () => (store ? { ...store } : null);
export const setSession = (patch) => {
  store = { ...(store || {}), ...patch };
  persist();
};
export const clearSession = () => {
  store = null;
  persist();
};
export const onUnauthorized = (fn) => {
  unauthorized = fn;
};

// FastAPI errors are {"detail": "..."} - surface that text instead of the raw body.
async function detail(r) {
  try {
    const j = await r.json();
    if (j?.detail) return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    /* not JSON: fall through */
  }
  return `Request failed (${r.status})`;
}

async function req(path, { method = "GET", body, auth = true, blob = false, keepalive = false } = {}) {
  const headers = {};
  if (auth && store?.token) headers.Authorization = `Bearer ${store.token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let r;
  try {
    // keepalive: the tab may be closing - the browser finishes the request anyway.
    r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), keepalive });
  } catch {
    throw new Error("Cannot reach the server. Is the backend running on 127.0.0.1:8010?");
  }
  if (r.status === 401 && auth) {
    clearSession();
    unauthorized?.();
  }
  if (!r.ok) throw new Error(await detail(r));
  if (blob) return r.blob();
  if (r.status === 204) return null;
  return r.json();
}

export const api = {
  // ---- account ----
  signup: (f) => req("/api/signup", { method: "POST", body: { name: f.name, phone: f.phone, email: f.email, password: f.password } }),
  login: (email, password) => req("/api/login", { method: "POST", body: { email, password } }),
  forgot: (email, password) => req("/api/forgot", { method: "POST", body: { email, password } }),
  me: () => req("/api/me"),
  meta: () => req("/api/meta"),

  // ---- subscription: POST /api/checkout {plan, method}. The API answers either
  //      {dev:true, token} (PAYPAK_DEV_GRANT only) or {url} - the browser is then sent to that
  //      hosted checkout page and comes back on /?paid=<identifier>.
  checkout: (plan, method = "card") => req("/api/checkout", { method: "POST", body: { plan, method } }),
  payment: (identifier) => req(`/api/payments/${encodeURIComponent(identifier)}`),
  confirmPayment: (identifier, extra) =>
    req(`/api/payments/${encodeURIComponent(identifier)}/confirm`, { method: "POST", body: extra || {} }),

  // ---- venues behind the Hall step ----
  halls: () => req("/api/halls"),

  // ---- quotations ----
  quotations: () => req("/api/quotations"),
  get: (id) => req(`/api/quotations/${id}`),
  create: (body) => req("/api/quotations", { method: "POST", body }),
  update: (id, body, keepalive = false) => req(`/api/quotations/${id}`, { method: "PATCH", body, keepalive }),
  remove: (id) => req(`/api/quotations/${id}`, { method: "DELETE" }),

  // ---- sending: the server owns the allowance and the message wording ----
  contact: (id, hallId) => req(`/api/quotations/${id}/contact`, { method: "POST", body: { hall_id: hallId } }),
  shareLink: (id, hallId) => req(`/api/quotations/${id}/share-link`, { method: "POST", body: { hall_id: hallId } }),
  pdf: (id) => req(`/api/quotations/${id}/pdf`, { blob: true }),
};

function saveBlob(blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "Shaadi_Quotation.pdf";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

// The download IS the preview: the wizard's rendered document is captured in the browser and
// written into the PDF, so what lands on disk is exactly what was on screen - not a second,
// server-drawn copy of it. The fixed name is not derived from the quotation in any way.
async function previewPdf(node) {
  const [{ default: html2canvas }, { jsPDF }] = await Promise.all([import("html2canvas"), import("jspdf")]);
  // currentColor inside an inline SVG does not survive the capture - bake the computed
  // colour into each icon first so the tick and the section icons keep their colours.
  node.querySelectorAll("svg").forEach((s) => {
    s.style.color = getComputedStyle(s).color;
  });
  const canvas = await html2canvas(node, { backgroundColor: "#ffffff", scale: 2, useCORS: true });
  const pdf = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4" });
  const pw = pdf.internal.pageSize.getWidth();
  const ph = pdf.internal.pageSize.getHeight();
  const img = canvas.toDataURL("image/jpeg", 0.95);
  const imgH = (canvas.height * pw) / canvas.width;
  let position = 0;
  let left = imgH;
  pdf.addImage(img, "JPEG", 0, position, pw, imgH);
  for (left -= ph; left > 0; left -= ph) {
    position -= ph;
    pdf.addPage();
    pdf.addImage(img, "JPEG", 0, position, pw, imgH);
  }
  return pdf.output("blob");
}

export async function downloadPdf(node, id) {
  try {
    saveBlob(await previewPdf(node));
  } catch {
    // Capture failed (old browser, blocked font): the server's copy still downloads,
    // under the very same fixed name.
    saveBlob(await api.pdf(id));
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// PayPak's IPN and the browser's return trip race each other, so this polls the payment record
// until the gateway has settled it and, while it is still pending, asks the server to verify the
// return trip too (sandbox answers at once, live waits for the IPN - both are handled the same).
// `onTick` receives the pass number so the UI can keep saying the confirmation is running.
// Resolves with the payment view, or gives up after ~60s and answers with whatever is known.
export async function settlePayment(identifier, extra, onTick) {
  const deadline = Date.now() + 60000;
  const fatal = (e) =>
    /not found|expired|did not match|not changed|Log in|cannot reach/i.test(String(e?.message || ""));
  let last = null;
  let n = 0;
  while (Date.now() < deadline) {
    try {
      last = await api.payment(identifier);
      if (last?.status && last.status !== "pending") return last;
    } catch (e) {
      if (fatal(e)) throw e;
    }
    n += 1;
    onTick?.(n);
    await sleep(2000);
    if (n % 3 === 1) {
      try {
        const c = await api.confirmPayment(identifier, extra);
        if (c?.status && c.status !== "pending") return c;
        last = c || last;
      } catch (e) {
        if (fatal(e)) throw e;   // 403 in live mode simply means "still waiting for the IPN"
      }
    }
  }
  return last;
}
