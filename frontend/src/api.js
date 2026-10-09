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
  // The hall's link: no session, only the signed id. The answer is the quotation itself -
  // the SPA renders it with the same <Doc> component the wizard previews with.
  shareView: (id, sig) => req(`/api/quotations/${encodeURIComponent(id)}/public?sig=${encodeURIComponent(sig || "")}`, { auth: false }),
};

const PDF_NAME = "Shaadi_Quotation.pdf";

function saveBlob(blob) {
  const url = URL.createObjectURL(blob);
  const done = () => setTimeout(() => URL.revokeObjectURL(url), 60000);
  const a = document.createElement("a");
  if (typeof a.download === "undefined") {
    // iOS Safari before 13 / in-app browsers: an anchor cannot save a blob, so the file is
    // shown instead - the viewer has its own Save. Assigning the URL never gets blocked.
    window.location.href = url;
    done();
    return;
  }
  a.href = url;
  a.download = PDF_NAME;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  done();
}

/* ---- the download --------------------------------------------------------------------------------
   The PDF is not drawn a second time anywhere: the rendered preview - the very <article class="doc">
   on screen - is captured with html2canvas at scale 2 and written into a single page whose size is
   the element's own size, so every line breaks where it broke on screen. There is no doc.text(), no
   server-side reportlab copy and no fallback that could hand back a plain-text document, so the
   badge, the icons, the divider lines, the green-tick pills and the date in the file are exactly the
   ones the user was looking at. */

// The webfont must be in the document before the capture, or the canvas falls back to a system face
// that the on-screen preview did not use.
async function fontsReady() {
  try {
    const f = document.fonts;
    if (!f) return;
    await Promise.all(
      [400, 500, 600, 700, 800].map((w) => f.load(`${w} 13px "Plus Jakarta Sans"`).catch(() => {}))
    );
    await f.ready;
  } catch {
    /* no Font Loading API: capture whatever is already on screen */
  }
}

// currentColor inside an inline SVG does not survive the capture - bake the computed colour into
// each icon first so the tick and the section icons keep their colours, and put the old value back
// afterwards so the preview on screen is untouched.
async function withPaintedIcons(node, work) {
  const painted = [...node.querySelectorAll("svg")].map((s) => [s, s.style.color]);
  painted.forEach(([s]) => {
    s.style.color = getComputedStyle(s).color;
  });
  try {
    return await work();
  } finally {
    painted.forEach(([s, c]) => {
      s.style.color = c;
    });
  }
}

async function capture(node) {
  if (!node) throw new Error("Open the Review step first - there is no preview to download.");
  await fontsReady();
  const { default: html2canvas } = await import("html2canvas");
  return withPaintedIcons(node, () =>
    html2canvas(node, {
      backgroundColor: "#ffffff",
      scale: 2,             // 2x the CSS pixels: crisp on paper
      useCORS: true,        // same-origin font files, kept for any external asset
      logging: false,
      imageTimeout: 15000,
      ignoreElements: (el) => el.hasAttribute && el.hasAttribute("data-html2canvas-ignore"),
    })
  );
}

// Only when the content would outrun what a PDF page may measure (~2 m) is it cut into A4 sheets;
// a quotation never comes close, but a runaway layout must not produce an unreadable file.
const MAX_PAGE_MM = 1800;

function sliceIntoA4(canvas, node, jsPDF) {
  const pdf = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4", compress: true });
  const pw = pdf.internal.pageSize.getWidth();
  const ph = pdf.internal.pageSize.getHeight();
  const w = canvas.width;
  const pagePx = Math.round((ph * w) / pw);              // one A4 page, in canvas pixels
  const base = node.getBoundingClientRect();
  const k = base.width ? canvas.width / base.width : 2;  // CSS px -> canvas px
  // Blocks that must never be split across two sheets (the CSS break-inside: avoid covers print).
  const zones = [...node.querySelectorAll(".dr, .doc-chip, .doc-k, .doc-h, .doc-t")]
    .map((el) => {
      const r = el.getBoundingClientRect();
      return [(r.top - base.top) * k, (r.bottom - base.top) * k];
    })
    .filter(([a, b]) => b > a);

  let y = 0;
  while (y < canvas.height) {
    let end = Math.min(y + pagePx, canvas.height);
    for (const [a, b] of zones) {          // a cut inside a row/pill moves to just before it
      if (end > a && end < b && a > y) {
        end = a;
        break;
      }
    }
    const h = Math.max(1, end - y);
    const slice = document.createElement("canvas");
    slice.width = w;
    slice.height = h;
    const ctx = slice.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, w, h);
    ctx.drawImage(canvas, 0, y, w, h, 0, 0, w, h);
    if (y > 0) pdf.addPage();
    pdf.addImage(slice.toDataURL("image/jpeg", 0.95), "JPEG", 0, 0, pw, (h * pw) / w);
    y = end;
  }
  return pdf.output("blob");
}

async function previewPdf(node) {
  const [{ jsPDF }, canvas] = await Promise.all([import("jspdf"), capture(node)]);
  const cssW = node.getBoundingClientRect().width || canvas.width / 2;
  const mmPerPx = (cssW * 25.4) / 96 / canvas.width;     // canvas pixels -> millimetres (96 dpi)
  const pageW = canvas.width * mmPerPx;
  const pageH = canvas.height * mmPerPx;

  if (pageH > MAX_PAGE_MM) return sliceIntoA4(canvas, node, jsPDF);

  // One page the size of the document itself: no cut, no margin to guess, no second layout.
  const pdf = new jsPDF({ orientation: "portrait", unit: "mm", format: [pageW, pageH], compress: true });
  pdf.addImage(canvas.toDataURL("image/jpeg", 0.95), "JPEG", 0, 0, pageW, pageH);
  return pdf.output("blob");
}

// The download IS the preview: one element in, one PDF out. If the capture cannot run the caller
// is told - there is no second, differently-drawn document to fall back to.
export async function downloadPdf(node) {
  saveBlob(await previewPdf(node));
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
