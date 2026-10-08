import { useEffect, useMemo, useRef, useState } from "react";
import { api, downloadPdf } from "./api.js";
import {
  EVENTS, SLOTS, MENU_IDEAS, SERVICES, PAID_PLANS, passOf, money, dayName, niceDate,
  payload, stepError, fmtWait, clamp, LIMITS, PRESET_TIMES, to24, from24, waLink,
} from "./lib.js";
import SubscribePlan from "./Subscribe.jsx";

const STEPS = ["Event", "Hall", "Menu", "Services", "Send"];

/* ---------- small shared pieces ---------- */
function Logo({ small }) {
  return (
    <div className={`brand ${small ? "sm" : ""}`}>
      <span className="mark">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">
          <path d="M12 2l2.4 6.2L21 9l-5 4.3L17.5 20 12 16.4 6.5 20 8 13.3 3 9l6.6-.8z" />
        </svg>
      </span>
      Shaadi<b>Planner</b>
    </div>
  );
}

function Stars({ v }) {
  return (
    <span className="stars" aria-hidden="true">
      <span className="bg">★★★★★</span>
      <span className="fg" style={{ width: `${(v / 5) * 100}%` }}>★★★★★</span>
    </span>
  );
}

function Field({ label, hint, children }) {
  return (
    <label className="fld">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

/* Stroke icons on one 24x24 grid, coloured by the surrounding text: the quotation reads as
   sections instead of a wall of uppercase labels. */
const ICONS = {
  venue: (
    <>
      <path d="M3 21h18" />
      <path d="M5 21V8l7-4 7 4v13" />
      <path d="M9 21v-6h6v6" />
      <path d="M9.5 10h.01M14.5 10h.01" />
    </>
  ),
  user: (
    <>
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </>
  ),
  event: <path d="M12 3l1.9 4.9L19 9l-4 3.5 1.2 5.5L12 15.4 7.8 18l1.2-5.5L5 9l5.1-1.1z" />,
  calendar: (
    <>
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <path d="M16 2v4M8 2v4M3 10h18" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  users: (
    <>
      <path d="M17 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9.5" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </>
  ),
  bowl: (
    <>
      <path d="M3 11h18a9 9 0 0 1-18 0z" />
      <path d="M7 11a5 5 0 0 1 10 0" />
      <path d="M12 3v3" />
    </>
  ),
  check: (
    <>
      <path d="M9 11l3 3 8-8" />
      <path d="M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9" />
    </>
  ),
  tick: <path d="M20 6L9 17l-5-5" />,
  note: (
    <>
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
      <path d="M14 3v6h6" />
      <path d="M8 13h8M8 17h5" />
    </>
  ),
};

function Ico({ n, s = 15 }) {
  return (
    <svg viewBox="0 0 24 24" width={s} height={s} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[n]}
    </svg>
  );
}

/* ---------- step 1: the event ---------- */
function StepEvent({ q, set }) {
  const wk = ["Friday", "Saturday", "Sunday"].includes(dayName(q.event_date));
  const [custom, setCustom] = useState(() => !PRESET_TIMES.includes(q.time));
  const pickSlot = (s) => {
    setCustom(false);
    set({ slot: s, time: SLOTS[s][1] });
  };
  const pickTime = (t) => {
    setCustom(false);
    set({ time: t });
  };
  return (
    <div className="step">
      <h2>Tell us about your event</h2>
      <Field label="Event name">
        <input value={q.title} maxLength={LIMITS.title} placeholder="e.g. Ali and Sara's Barat" onChange={(e) => set({ title: e.target.value })} />
      </Field>
      <Field label="Your name (on the quotation)">
        <input value={q.host} maxLength={LIMITS.host} onChange={(e) => set({ host: e.target.value })} />
      </Field>
      <div className="fld">
        <span>Which event?</span>
        <div className="chips">
          {EVENTS.map((x) => (
            <button type="button" key={x} className={`chip ${q.event_type === x ? "on" : ""}`} onClick={() => set({ event_type: x })}>
              {x}
            </button>
          ))}
        </div>
      </div>
      <div className="row2">
        <Field
          label="Date"
          hint={
            q.event_date ? (
              <>
                <b>{dayName(q.event_date)}</b>
                {wk ? " · weekend, halls may charge more" : " · weekday"}
              </>
            ) : (
              "Pick the event day"
            )
          }
        >
          <input type="date" value={q.event_date} min={new Date().toISOString().slice(0, 10)} onChange={(e) => set({ event_date: e.target.value })} />
        </Field>
        <div className="fld">
          <span>Morning or evening?</span>
          <div className="seg">
            {Object.keys(SLOTS).map((s) => (
              <button type="button" key={s} className={q.slot === s ? "on" : ""} onClick={() => pickSlot(s)}>
                {s}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="fld">
        <span>Start time</span>
        <div className="chips">
          {SLOTS[q.slot].map((t) => (
            <button type="button" key={t} className={`chip ${!custom && q.time === t ? "on" : ""}`} onClick={() => pickTime(t)}>
              {t}
            </button>
          ))}
          <button type="button" className={`chip ${custom ? "on" : ""}`} onClick={() => setCustom((c) => !c)}>
            Custom time
          </button>
        </div>
        {custom && (
          <div className="customtime">
            <input
              type="time"
              aria-label="Custom start time"
              value={to24(q.time)}
              onChange={(e) => set({ time: from24(e.target.value) })}
            />
            <small>
              {q.time ? `Starts at ${q.time}` : "Choose a time — it goes on the PDF and the message"}
            </small>
          </div>
        )}
      </div>
      <div className="row2">
        <div className="fld">
          <span>Number of guests</span>
          <div className="stepper">
            <button type="button" onClick={() => set({ guests: clamp(q.guests - 50, LIMITS.guestsMin, LIMITS.guestsMax, 300) })} aria-label="Fewer guests">
              −
            </button>
            <input
              type="number"
              inputMode="numeric"
              min={LIMITS.guestsMin}
              max={LIMITS.guestsMax}
              value={q.guests}
              onChange={(e) => set({ guests: e.target.value === "" ? "" : +e.target.value })}
              onBlur={(e) => set({ guests: clamp(+e.target.value, LIMITS.guestsMin, LIMITS.guestsMax, 300) })}
            />
            <button type="button" onClick={() => set({ guests: clamp(q.guests + 50, LIMITS.guestsMin, LIMITS.guestsMax, 300) })} aria-label="More guests">
              +
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- step 2: halls (list straight from GET /api/halls) ---------- */
function StepHall({ q, set, allow, plan, halls, loading, error, onRetry }) {
  const cities = useMemo(() => ["All", ...[...new Set(halls.map((h) => h.city).filter(Boolean))].sort()], [halls]);
  const [city, setCity] = useState("All");
  const [search, setSearch] = useState("");

  const list = useMemo(
    () =>
      halls
        .filter((h) => (city === "All" || h.city === city) && h.name.toLowerCase().includes(search.trim().toLowerCase()))
        .sort((a, b) => (b.reviewCount || 0) - (a.reviewCount || 0)),
    [halls, city, search]
  );

  const pick = (h) => {
    const on = q.halls.some((x) => x.id === h.id);
    if (on) set({ halls: q.halls.filter((x) => x.id !== h.id) });
    else if (q.halls.length < allow) set({ halls: [...q.halls, h] });
  };

  if (loading) {
    return (
      <div className="step">
        <h2>Choose your hall{allow > 1 ? "s" : ""}</h2>
        <div className="card empty">
          <span className="spin" aria-hidden="true" />
          <p className="muted">Loading halls…</p>
        </div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="step">
        <h2>Choose your hall{allow > 1 ? "s" : ""}</h2>
        <div className="banner bad" role="alert">
          {error}
          <button className="btn" type="button" onClick={onRetry}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="step">
      <h2>Choose your hall{allow > 1 ? "s" : ""}</h2>
      <p className="lead">
        {allow === 1
          ? "Free plan: pick 1 hall. You can contact 1 hall every 24 hours."
          : `Your ${plan} plan: pick up to ${allow} halls for this quotation.`}{" "}
        <b>
          {q.halls.length}/{allow} picked
        </b>
      </p>
      <div className="filters">
        <div className="seg">
          {cities.map((c) => (
            <button type="button" key={c} className={city === c ? "on" : ""} onClick={() => setCity(c)}>
              {c}
            </button>
          ))}
        </div>
        <input className="search" placeholder="Search hall name" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search hall" />
      </div>
      <div className="halls">
        {list.map((h) => {
          const on = q.halls.some((x) => x.id === h.id);
          const full = !on && q.halls.length >= allow;
          return (
            <button type="button" key={h.id} className={`hall ${on ? "on" : ""}`} onClick={() => pick(h)} disabled={full} aria-pressed={on}>
              <span className="tick">{on ? "✓" : ""}</span>
              <span className="hn">
                <b>{h.name}</b>
                <small>
                  {h.city}
                  {h.rating ? (
                    <>
                      {" · "}
                      {h.rating.toFixed(1)} <Stars v={h.rating} /> ({(h.reviewCount || 0).toLocaleString()})
                    </>
                  ) : (
                    " · No rating yet"
                  )}
                </small>
              </span>
            </button>
          );
        })}
        {!list.length && <p className="muted">No hall matches. Clear the search or filters.</p>}
      </div>
    </div>
  );
}

/* ---------- step 3: menu ---------- */
function StepMenu({ q, set }) {
  const [draft, setDraft] = useState("");
  const add = (x) => {
    x = String(x || "").trim().slice(0, 60);
    if (x && !q.menu.includes(x) && q.menu.length < LIMITS.menu) set({ menu: [...q.menu, x] });
    setDraft("");
  };
  return (
    <div className="step">
      <h2>What food do you want?</h2>
      <p className="lead">Tap ideas to add them, or type your own dish.</p>
      <div className="chips">
        {MENU_IDEAS.filter((x) => !q.menu.includes(x)).map((x) => (
          <button type="button" key={x} className="chip" onClick={() => add(x)} disabled={q.menu.length >= LIMITS.menu}>
            + {x}
          </button>
        ))}
      </div>
      <form className="addrow" onSubmit={(e) => { e.preventDefault(); add(draft); }}>
        <input placeholder="Type a dish, e.g. Lamb karahi" value={draft} maxLength={60} onChange={(e) => setDraft(e.target.value)} />
        <button className="btn dark">Add</button>
      </form>
      <h3 className="h3">
        Your menu ({q.menu.length}/{LIMITS.menu})
      </h3>
      <ul className="menu">
        {q.menu.map((m, i) => (
          <li key={m}>
            <span>
              {i + 1}. {m}
            </span>
            <button type="button" className="x" onClick={() => set({ menu: q.menu.filter((x) => x !== m) })} aria-label={`Remove ${m}`}>
              ×
            </button>
          </li>
        ))}
        {!q.menu.length && <li className="muted">No dishes yet.</li>}
      </ul>
    </div>
  );
}

/* ---------- step 4: services ---------- */
function StepServices({ q, set }) {
  const tog = (s) => set({ services: q.services.includes(s) ? q.services.filter((x) => x !== s) : [...q.services, s] });
  return (
    <div className="step">
      <h2>What else do you need?</h2>
      <p className="lead">Choose everything you want the hall to include.</p>
      <div className="svc">
        {SERVICES.map((s) => (
          <button type="button" key={s} className={`svc-i ${q.services.includes(s) ? "on" : ""}`} onClick={() => tog(s)} aria-pressed={q.services.includes(s)}>
            <span className="tick">{q.services.includes(s) ? "✓" : ""}</span>
            {s}
          </button>
        ))}
      </div>
      <Field label="Anything else the hall should know? (optional)">
        <textarea rows="3" maxLength={LIMITS.notes} placeholder="e.g. Separate entrance for ladies, vegetarian counter, stage for 30 people" value={q.notes} onChange={(e) => set({ notes: e.target.value })} />
        <small className="cnt">
          {q.notes.length}/{LIMITS.notes}
        </small>
      </Field>
    </div>
  );
}

/* ---------- the quotation document (same layout the PDF uses) ---------- */
function Doc({ q, user }) {
  const row = (n, a, b) => (
    <div className="dr">
      <span>
        <Ico n={n} />
        {a}
      </span>
      <b>{b}</b>
    </div>
  );
  // Services and dishes are choices, so they are shown as the choices that were made rather
  // than as a comma-separated string.
  const chips = (list) => (
    <div className="doc-chips">
      {list.map((x) => (
        <span className="doc-chip" key={x}>
          <Ico n="tick" s={12} />
          {x}
        </span>
      ))}
      {!list.length && <span className="doc-v">None selected</span>}
    </div>
  );
  const hall = q.halls[0];
  return (
    <article className="doc" aria-label="Quotation preview">
      <div className="doc-h">
        <Logo />
        <div className="doc-t">
          <h3>Quotation Request</h3>
          <small>{new Date().toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })}</small>
        </div>
      </div>
      <p className="doc-k">
        <Ico n="venue" />
        Prepared for
      </p>
      <p className="doc-v">{hall ? hall.name : "Your chosen hall"}</p>
      <p className="doc-k">
        <Ico n="user" />
        From
      </p>
      <p className="doc-v">
        {q.host || user.name} · {user.phone}
      </p>
      <p className="doc-p">
        Assalam o Alaikum. I would like a quotation for my {q.event_type.toLowerCase()} at your venue on {niceDate(q.event_date)} (
        {dayName(q.event_date) || "day"}, {q.slot.toLowerCase()}, {q.time}). Kindly see the details below and let us know your price and
        availability.
      </p>
      <div className="dt">
        {row("event", "Event", q.event_type + (q.title ? ` · ${q.title}` : ""))}
        {row("calendar", "Date and day", niceDate(q.event_date) + (q.event_date ? ` · ${dayName(q.event_date)}` : ""))}
        {row("clock", "Time", `${q.slot} · ${q.time}`)}
        {row("users", "Number of persons", Number(q.guests || 0).toLocaleString("en-IN"))}
      </div>
      <p className="doc-k">
        <Ico n="check" />
        Services wanted
      </p>
      {chips(q.services)}
      <p className="doc-k">
        <Ico n="bowl" />
        Food menu
      </p>
      {chips(q.menu)}
      {q.notes && (
        <>
          <p className="doc-k">
            <Ico n="note" />
            Notes
          </p>
          <p className="doc-v">{q.notes}</p>
        </>
      )}
    </article>
  );
}

function previewMessage(q, hall, user) {
  return (
    `Assalam o Alaikum ${hall.name} team,\n` +
    `I am ${q.host || user.name}. I am planning a ${q.event_type} on ${dayName(q.event_date)}, ${niceDate(q.event_date)} ` +
    `(${q.slot}, ${q.time}) for ${q.guests} guests.\n` +
    `Kindly see this quotation and let us know: [PDF link added by the app]\nThank you.`
  );
}

/* ---------- upgrades go through the subscription modal (Subscribe.jsx), which posts
   /api/checkout and hands the browser to PayPak's hosted page. There is no per-quotation
   pass checkout any more: the plan lives on the account, not on a quotation. ---------- */

/* ---------- the wizard ---------- */

/* Where the wizard was when the tab was closed. The quotation itself is saved on the server
   (debounced PATCH below), so only the step number lives here - it is dropped again by exit(),
   which is the deliberate "Close". A crash or a closed tab keeps it, so nothing is retyped. */
const stepKey = (id) => `sp.wizard-step.${id || ""}`;
const readStep = (id) => {
  try {
    const n = parseInt(localStorage.getItem(stepKey(id)) || "0", 10);
    return Number.isFinite(n) && n >= 0 && n <= 4 ? n : 0;
  } catch {
    return 0;
  }
};
const saveStep = (id, n) => {
  try {
    localStorage.setItem(stepKey(id), String(n));
  } catch {
    /* private mode: the wizard still works, it just does not remember the step */
  }
};
const clearStep = (id) => {
  try {
    localStorage.removeItem(stepKey(id));
  } catch {
    /* ignore */
  }
};

export default function Wizard({ initial, user, onExit, onUpgraded, toast }) {
  const [q, setQ] = useState(initial);
  const qRef = useRef(initial);
  const [step, setStep] = useState(() => readStep(initial.id));
  const [saveState, setSaveState] = useState("");
  const [halls, setHalls] = useState([]);
  const [hallsLoading, setHallsLoading] = useState(true);
  const [hallsErr, setHallsErr] = useState("");
  const [sending, setSending] = useState("");
  const [, setTick] = useState(0);
  const mounted = useRef(true);

  const pending = useRef(null);
  const chain = useRef(Promise.resolve());
  const timer = useRef(null);

  const allow = q.allow || 1;
  const left = q.left ?? 0;
  const busyNow = !!sending;
  const plan = passOf(user.plan);
  const upsell = PAID_PLANS.filter((p) => p.halls > allow);

  /* ---- debounced save: every edit becomes a PATCH of the allowed fields only ---- */
  const flush = () => {
    clearTimeout(timer.current);
    const body = pending.current;
    if (!body) return chain.current;
    if (!qRef.current.id) {
      // Opened before the server had the row (App opens the wizard on the click): the edit is
      // kept and retried - the id effect below clears this as soon as the POST comes back.
      timer.current = setTimeout(flush, 400);
      return chain.current;
    }
    pending.current = null;
    setSaveState("saving");
    const p = chain.current.then(async () => {
      try {
        await api.update(qRef.current.id, body);
        if (mounted.current) setSaveState("saved");
      } catch (e) {
        if (mounted.current) {
          setSaveState("error");
          toast(e.message, "error");
        }
      }
    });
    chain.current = p.then(() => {});
    return chain.current;
  };

  const set = (patch) => {
    const next = { ...qRef.current, ...patch };
    qRef.current = next;
    setQ(next);
    pending.current = payload(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(flush, 600);
  };

  /* The tab can disappear mid-typing - closed, crashed, power cut. The debounced save leaves at
     most 600 ms of slack, so the very last edit is pushed again with keepalive on the way out;
     the browser finishes that request even though the page is already going away. */
  const flushNow = () => {
    const body = pending.current;
    if (!body || !qRef.current.id) return;
    pending.current = null;
    clearTimeout(timer.current);
    api.update(qRef.current.id, body, true).catch(() => {});
  };

  useEffect(() => {
    const bye = () => flushNow();
    window.addEventListener("pagehide", bye);
    window.addEventListener("beforeunload", bye);
    return () => {
      window.removeEventListener("pagehide", bye);
      window.removeEventListener("beforeunload", bye);
    };
  }, []);

  // The quotation was opened before its row existed: take the real id (and the server-owned
  // allowance fields) as soon as App has them, keeping everything typed in the meantime - which
  // also unblocks the pending flush above.
  useEffect(() => {
    if (!initial.id || qRef.current.id) return;
    const next = {
      ...qRef.current,
      id: initial.id,
      allow: initial.allow,
      left: initial.left,
      sent: initial.sent,
      next_free_at: initial.next_free_at,
      pass_id: initial.pass_id,
      status: initial.status,
    };
    qRef.current = next;
    setQ(next);
    if (pending.current) flush();
  }, [initial.id]);

  // Server-owned fields only (allowance, pass, status) - never clobbers a still-typing field.
  const applyAllowance = (r) => {
    const next = {
      ...qRef.current,
      allow: r.allow,
      left: r.left,
      sent: r.sent,
      next_free_at: r.next_free_at,
      pass_id: r.pass_id,
      status: r.status,
    };
    qRef.current = next;
    setQ(next);
  };

  // The plan lives on the account, so after an upgrade this quotation's allowance is re-read
  // from the server (allow / left / next_free_at all move with the plan).
  const refreshAllowance = async () => {
    try {
      applyAllowance(await api.get(qRef.current.id));
    } catch (e) {
      toast(e.message, "error");
    }
  };

  /* ---- halls ---- */
  const loadHalls = () => {
    setHallsLoading(true);
    setHallsErr("");
    api
      .halls()
      .then((d) => {
        if (!mounted.current) return;
        setHalls(d);
        setHallsLoading(false);
      })
      .catch((e) => {
        if (!mounted.current) return;
        setHallsErr(e.message);
        setHallsLoading(false);
      });
  };
  useEffect(() => {
    mounted.current = true;
    loadHalls();
    const t = setInterval(() => setTick((x) => x + 1), 30000);
    return () => {
      mounted.current = false;
      clearTimeout(timer.current);
      clearInterval(t);
    };
  }, []);

  // Remembered across reloads while the quotation is being worked on.
  useEffect(() => {
    saveStep(initial.id, step);
  }, [initial.id, step]);

  const exit = async () => {
    await flush();                     // whatever was typed is on the server before we leave
    clearStep(initial.id);
    onExit();
  };

  // "Save" on the last step: commit now, stay where you are.
  const saveNow = async () => {
    await flush();
    toast("Quotation saved. Close it whenever you are ready.", "success");
  };

  const err = stepError(q, step, allow);

  /* ---- sending: open the WhatsApp window first (so the popup is allowed), then ask the
         server for the signed link and spend the allowance, then navigate. ---- */
  const copy = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      return false;
    }
  };

  const send = async (hall) => {
    if (busyNow) return;
    setSending(hall.id);
    let w = null;
    try {
      w = window.open("", "_blank");                    // opened synchronously: popups from a later await are blocked
      await flush();                                     // the server validates what is stored, not what is typed
      const link = await api.shareLink(qRef.current.id, hall.id);
      const updated = await api.contact(qRef.current.id, hall.id);
      applyAllowance(updated);
      // Halls with no whatsappNumber still get the same message + PDF, dialled through their
      // listed phone number - wa.me accepts any reachable number.
      const waUrl = link.wa_url || (hall.phone ? waLink(hall.phone, link.message) : "");
      if (waUrl) {
        if (w && !w.closed) {
          w.opener = null;
          w.location.href = waUrl;
          toast(`WhatsApp opened for ${hall.name}`);
        } else {
          const ok = await copy(link.message);
          toast(ok ? "Popup blocked — the message with the PDF link was copied, paste it into WhatsApp." : "Allow popups to open WhatsApp.");
        }
      } else if (w && !w.closed) {
        w.close();
      }
      if (!waUrl) {
        const ok = await copy(link.message);
        toast(ok ? `Message copied — ${hall.name} has no number on file, share the PDF another way.` : `No number on file for ${hall.name}.`);
      }
    } catch (e) {
      if (w && !w.closed) w.close();
      toast(e.message, "error");
    } finally {
      setSending("");
    }
  };

  const copyNumber = async (hall) => {
    const ok = await copy(hall.phone);
    toast(ok ? `${hall.phone} copied — paste it in WhatsApp and send the PDF.` : `Could not copy — ${hall.phone}`);
  };

  const copyMessage = async (hall) => {
    try {
      const link = await api.shareLink(q.id, hall.id);
      const ok = await copy(link.message);
      toast(ok ? "Message copied to clipboard." : "Could not copy — select the text below instead.");
      if (!ok) toast(previewMessage(q, hall, user));
    } catch (e) {
      toast(e.message, "error");
    }
  };

  const download = async () => {
    try {
      await flush();
      await downloadPdf(document.querySelector("article.doc"), q.id);
      toast("PDF downloaded.");
    } catch (e) {
      toast(e.message, "error");
    }
  };

  // The upgrade itself is handled by App (session + toast); here only the allowance of this
  // quotation is re-read, because the account's plan is what sets allow / left.
  const upgraded = (r) => {
    onUpgraded(r);
    if (r && !r.url) refreshAllowance();
  };

  const waitLeft = q.next_free_at ? q.next_free_at * 1000 - Date.now() : 0;
  const blocked = left <= 0;

  return (
    <div className="page wiz">
      <header className="top">
        <Logo small />
        <div className="top-r">
          {saveState === "saving" && (
            <span className="save" role="status">
              <i className="spin" aria-hidden="true" />
              Saving…
            </span>
          )}
          {saveState === "saved" && <span className="save ok">Saved</span>}
          {saveState === "error" && (
            <button type="button" className="save bad" onClick={flush}>
              Not saved · Retry
            </button>
          )}
          <SubscribePlan user={user} onUpgraded={upgraded} />
          <button className="btn" onClick={exit} disabled={busyNow}>
            Save and exit
          </button>
        </div>
      </header>

      <nav className="prog" aria-label="Steps">
        {STEPS.map((s, i) => (
          <button key={s} className={`ps ${i === step ? "on" : ""} ${i < step ? "done" : ""}`} onClick={() => i <= step && setStep(i)} disabled={i > step || busyNow}>
            <i>{i < step ? "✓" : i + 1}</i>
            <span>{s}</span>
          </button>
        ))}
      </nav>

      <div className="wbody">
        <main className="card wmain">
          {step === 0 && <StepEvent q={q} set={set} />}
          {step === 1 && <StepHall q={q} set={set} allow={allow} plan={plan.name} halls={halls} loading={hallsLoading} error={hallsErr} onRetry={loadHalls} />}
          {step === 2 && <StepMenu q={q} set={set} />}
          {step === 3 && <StepServices q={q} set={set} />}
          {step === 4 && (
            <div className="step">
              <h2>Review and send</h2>
              <div className="rev">
                <Doc q={q} user={user} />
                <div className="send">
                  <div className="card pad">
                    <h3 className="h3">1. Save a PDF copy</h3>
                    <button className="btn big" onClick={download}>
                      Download PDF
                    </button>
                  </div>

                  <div className="card pad">
                    <h3 className="h3">2. Send on WhatsApp</h3>
                    {blocked && (
                      <div className="lockbox">
                        <b>
                          {plan.id === "free"
                            ? "Your free hall contact is used for now."
                            : `All ${plan.halls} hall sends on your ${plan.name} plan are used for now.`}
                        </b>
                        <p>
                          {waitLeft > 0 ? `The next one unlocks in ${fmtWait(waitLeft)}.` : "Try again in a few minutes."}{" "}
                          {plan.id === "free" ? "Upgrade to contact more halls today." : "Upgrade for a bigger daily allowance."}
                        </p>
                      </div>
                    )}
                    {q.halls.length === 0 ? (
                      <p className="muted">Go back and pick a hall first.</p>
                    ) : (
                      q.halls.map((h) => {
                        const done = (q.sent || []).includes(h.id);
                        const target = h.whatsappNumber || h.phone;   // what wa.me can open for this hall
                        const can = !done && left > 0 && target;
                        return (
                          <div className="sendrow" key={h.id}>
                            <span>
                              <b>{h.name}</b>
                              {done ? (
                                <small>Sent — waiting for their reply</small>
                              ) : h.whatsappNumber ? (
                                <small>WhatsApp ready · {h.whatsappNumber}</small>
                              ) : h.phone ? (
                                <>
                                  <small className="num">{h.phone}</small>
                                  <small className="note">
                                    No WhatsApp number on file for this hall. Copy their number, then send them the PDF
                                    below on WhatsApp.
                                  </small>
                                </>
                              ) : (
                                <small>No number on file — copy the message and reach them another way.</small>
                              )}
                            </span>
                            {done ? (
                              <span className="tag t-mint">Sent</span>
                            ) : (
                              <span className="acts">
                                {target && (
                                  <button
                                    className={`btn wa ${can ? "" : "off"}`}
                                    onClick={() => send(h)}
                                    disabled={!can || busyNow}
                                  >
                                    {sending === h.id ? "Opening…" : "Send PDF on WhatsApp"}
                                  </button>
                                )}
                                {h.phone && !h.whatsappNumber && (
                                  <button className="btn" onClick={() => copyNumber(h)} disabled={busyNow}>
                                    Copy number
                                  </button>
                                )}
                                {!h.whatsappNumber && (
                                  <button className="btn ghost" onClick={() => copyMessage(h)} disabled={busyNow}>
                                    Copy message
                                  </button>
                                )}
                              </span>
                            )}
                          </div>
                        );
                      })
                    )}
                    {q.halls.length > 0 && (
                      <details className="msg">
                        <summary>See the message we send</summary>
                        <pre>{previewMessage(q, q.halls[0], user)}</pre>
                      </details>
                    )}
                  </div>

                  <div className="card pad more">
                    <h3 className="h3">Contact more halls</h3>
                    <p className="muted">
                      Your <b>{plan.name}</b> plan lets you pick {allow} hall{allow > 1 ? "s" : ""} here
                      {" "}and you have {left} contact{left === 1 ? "" : "s"} left in the next 24 hours.
                    </p>
                    {upsell.length ? (
                      <div className="passes">
                        {upsell.map((p) => (
                          <div key={p.id} className={`pass ${user.plan === p.id ? "on" : ""}`}>
                            <b>{p.name}</b>
                            <span className="price">{money(p.price)}</span>
                            <small>{p.searches} results per category</small>
                            <small>{p.note}</small>
                            {user.plan === p.id && <small>Your current plan</small>}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="muted">You are already on the biggest plan.</p>
                    )}
                    {upsell.length > 0 && <SubscribePlan user={user} onUpgraded={upgraded} className="btn dark big" />}
                  </div>
                </div>
              </div>
            </div>
          )}
        </main>

        <aside className="card sum">
          <h3 className="h3">Quotation summary</h3>
          <dl>
            <div>
              <dt>Event</dt>
              <dd>{q.event_type}</dd>
            </div>
            <div>
              <dt>When</dt>
              <dd>
                {q.event_date ? `${dayName(q.event_date)}, ${niceDate(q.event_date)}` : "Not chosen"}
                <br />
                {q.slot}, {q.time}
              </dd>
            </div>
            <div>
              <dt>Guests</dt>
              <dd>{Number(q.guests || 0).toLocaleString("en-IN")}</dd>
            </div>
            <div>
              <dt>Hall</dt>
              <dd>{q.halls.length ? q.halls.map((h) => h.name).join(", ") : "Not chosen"}</dd>
            </div>
            <div>
              <dt>Menu</dt>
              <dd>{q.menu.length} dishes</dd>
            </div>
            <div>
              <dt>Plan</dt>
              <dd>
                {plan.name}
                {q.sent?.length ? ` · sent to ${q.sent.length}` : ""}
              </dd>
            </div>
          </dl>
        </aside>
      </div>

      <footer className="bar">
        {err && step < 4 && <span className="why">{err}</span>}
        <button className="btn" onClick={() => setStep(step - 1)} disabled={step === 0 || busyNow}>
          Back
        </button>
        {step < 4 ? (
          <button className="btn dark big" onClick={() => !err && setStep(step + 1)} disabled={!!err || busyNow}>
            Next
          </button>
        ) : (
          <>
            <button className="btn" onClick={saveNow} disabled={busyNow}>
              Save
            </button>
            <button className="btn dark big" onClick={exit} disabled={busyNow}>
              Close
            </button>
          </>
        )}
      </footer>
    </div>
  );
}
