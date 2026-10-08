// Shared constants and helpers. The validation below mirrors backend/quotations.py so a bad
// value is caught in the wizard instead of coming back as a 422 from the API.

export const EVENTS = ["Mehndi", "Barat", "Walima", "Nikah", "Engagement", "Other"];
export const SLOTS = {
  Morning: ["10:00 AM", "11:00 AM", "12:00 PM"],
  Evening: ["6:00 PM", "7:00 PM", "8:00 PM"],
};
export const MENU_IDEAS = [
  "Soup with crackers", "Saag stall", "Chicken biryani", "Mutton qorma", "Chicken boti",
  "Seekh kabab", "Live naan station", "Raita + salad", "Kheer", "Gajar ka halwa",
  "Cold drink", "Mineral water", "BBQ station", "Tea / kehwa",
];
export const SERVICES = [
  "Venue", "Catering", "Decor", "DJ / sound", "Photography", "Valet parking",
  "Bridal makeup", "Sweets", "Generator backup", "Stage and lighting",
];
// The subscription plans, mirroring backend/quotations.PLANS (the server is always the source
// of truth - /api/meta returns the same numbers and is used wherever the plan is bought).
// searches = results per category, halls = hall sends allowed in the rolling 24-hour window,
// price = Rs charged by the PayPak hosted checkout.
export const PASSES = [
  { id: "free", name: "Free", halls: 1, searches: 1, price: 0, note: "1 hall every 24 hours" },
  { id: "p5", name: "5 Search", halls: 8, searches: 5, price: 100, note: "8 halls every 24 hours" },
  { id: "p10", name: "10 Search", halls: 20, searches: 10, price: 500, note: "20 halls every 24 hours" },
];
export const passOf = (id) => PASSES.find((p) => p.id === id) || PASSES[0];
export const planName = (id) => passOf(id).name;
export const PAID_PLANS = PASSES.filter((p) => p.price > 0);
export const PRESET_TIMES = Object.values(SLOTS).flat();

// "7:00 PM" -> "19:00" for <input type="time">; "" when it cannot be parsed.
export function to24(t) {
  const m = /^\s*(\d{1,2}):(\d{2})\s*(am|pm)?\s*$/i.exec(String(t || ""));
  if (!m) return "";
  const mm = +m[2];
  if (mm > 59) return "";
  const ap = (m[3] || "").toLowerCase();
  let h = +m[1];
  if (ap) {
    if (h < 1 || h > 12) return "";
    h = (h % 12) + (ap === "pm" ? 12 : 0);
  } else if (h > 23) return "";
  return `${String(h).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

// "19:00" -> "7:00 PM" - the wording the PDF, the message and the summary all use.
export function from24(v) {
  const m = /^\s*(\d{1,2}):(\d{2})\s*$/.exec(String(v || ""));
  if (!m) return "";
  const h = +m[1];
  if (h > 23 || +m[2] > 59) return "";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${m[2]} ${h < 12 ? "AM" : "PM"}`;
}

// "+92 317 1111233" / "0317-1111233" / "3171111233" -> "923171111233" (what wa.me wants)
export function waDigits(n) {
  const d = String(n || "").replace(/[^\d]/g, "").replace(/^00/, "").replace(/^0/, "");
  if (d.startsWith("92")) return d;
  if (d.length === 10 && d.startsWith("3")) return "92" + d;
  return d;
}

// Used for halls that list a phone number but no whatsappNumber - same wa.me deep link,
// so the message with the PDF still lands in a chat with that hall.
export function waLink(n, text) {
  return `https://wa.me/${waDigits(n)}?text=${encodeURIComponent(text || "")}`;
}

export const LIMITS = { title: 100, host: 100, notes: 500, menu: 40, services: 20, guestsMin: 20, guestsMax: 5000 };
export const PHONE_RE = /^(?:\+?92|0092)?[\s-]?0?3\d{2}[\s-]?\d{7}$/;

const pad = (n) => String(n).padStart(2, "0");
export const todayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

export const money = (n) => "Rs " + (Number(n) || 0).toLocaleString("en-IN");

export function dayName(d) {
  if (!d) return "";
  const x = new Date(`${d}T00:00:00`);
  return isNaN(x) ? "" : x.toLocaleDateString("en-GB", { weekday: "long" });
}

export function niceDate(d) {
  if (!d) return "Date not chosen";
  const x = new Date(`${d}T00:00:00`);
  return isNaN(x) ? d : x.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}

export function initials(name) {
  return String(name || "")
    .replace(/[^A-Za-z0-9 ]/g, "")
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");
}

// "5h 12m" / "45m" - how long until the next free hall contact unlocks.
export function fmtWait(ms) {
  const t = Math.max(0, ms);
  const h = Math.floor(t / 3600000);
  const m = Math.floor((t % 3600000) / 60000);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

// The body the PATCH/POST endpoints accept: ONLY the fields in backend quotations.FIELDS,
// halls as ids. Unknown keys are refused by the server on purpose.
export function payload(q) {
  return {
    title: String(q.title || "").slice(0, LIMITS.title),
    host: String(q.host || "").slice(0, LIMITS.host),
    event_type: q.event_type,
    event_date: q.event_date || "",
    slot: q.slot,
    time: String(q.time || "").trim().slice(0, 20),
    guests: clamp(Number(q.guests), LIMITS.guestsMin, LIMITS.guestsMax, 300),
    budget: clamp(Number(q.budget), 0, 1_000_000_000, 0),
    menu: (q.menu || []).slice(0, LIMITS.menu),
    services: (q.services || []).slice(0, LIMITS.services),
    notes: String(q.notes || "").slice(0, LIMITS.notes),
    halls: (q.halls || []).map((h) => h.id),
  };
}

export function clamp(n, lo, hi, fallback) {
  if (!Number.isFinite(n)) return fallback;
  return Math.min(hi, Math.max(lo, Math.round(n)));
}

// Body for POST /api/quotations - a fresh draft, everything valid on the first save.
export function newQuotation(user) {
  return {
    title: "",
    host: user?.name || "",
    event_type: "Barat",
    event_date: "",
    slot: "Evening",
    time: "7:00 PM",
    guests: 300,
    budget: 1_500_000,
    menu: ["Chicken biryani", "Mutton qorma", "Kheer"],
    services: ["Venue", "Catering"],
    notes: "",
    halls: [],
  };
}

// null = the step is complete, otherwise the sentence shown under the footer bar.
export function stepError(q, step, allow) {
  if (step === 0) {
    if (!q.event_date) return "Pick the event date to continue.";
    if (q.event_date < todayISO()) return "The event date cannot be in the past.";
    if ((q.guests || 0) < LIMITS.guestsMin || (q.guests || 0) > LIMITS.guestsMax)
      return `Number of guests must be between ${LIMITS.guestsMin} and ${LIMITS.guestsMax.toLocaleString("en-IN")}.`;
    if (!(q.budget > 0)) return "Enter your total budget to continue.";
    if ((q.title || "").length > LIMITS.title) return `Event name is too long (max ${LIMITS.title} characters).`;
    if ((q.host || "").length > LIMITS.host) return `Your name is too long (max ${LIMITS.host} characters).`;
    if (!String(q.time || "").trim()) return "Pick a start time to continue.";
    if (String(q.time).trim().length > 20) return "Start time is too long (max 20 characters).";
    return null;
  }
  if (step === 1) {
    if (!q.halls.length) return "Pick at least one hall to continue.";
    if (q.halls.length > allow) return `You can pick up to ${allow} hall${allow > 1 ? "s" : ""}.`;
    return null;
  }
  if (step === 2) {
    if (!q.menu.length) return "Add at least one dish to continue.";
    if (q.menu.length > LIMITS.menu) return `Too many dishes (max ${LIMITS.menu}).`;
    if (q.menu.some((d) => d.length > 60)) return "A dish name is too long (max 60 characters).";
    return null;
  }
  if (step === 3) {
    if ((q.services || []).length > LIMITS.services) return `Too many services (max ${LIMITS.services}).`;
    if ((q.notes || "").length > LIMITS.notes) return `Notes are too long (max ${LIMITS.notes} characters).`;
    return null;
  }
  return null;
}
