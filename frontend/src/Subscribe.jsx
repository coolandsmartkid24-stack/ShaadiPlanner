import { useEffect, useState } from "react";
import { api } from "./api.js";
import { money, planName } from "./lib.js";

/* The three ways PayPak's hosted checkout accepts. Which one is ticked here is stored on the
   payment record and repeated on the gateway's own page - no card or wallet data is ever typed
   into this app. */
const METHODS = [
  { id: "easypaisa", name: "Easypaisa", hint: "Wallet · pay with your mobile number" },
  { id: "jazzcash", name: "JazzCash", hint: "Wallet · pay with your mobile number" },
  { id: "card", name: "Debit / credit card", hint: "Visa · Mastercard · 1Link" },
];
const labelOf = (id) => (METHODS.find((m) => m.id === id) || METHODS[0]).name;

const IcWallet = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 8.5A2.5 2.5 0 0 1 5.5 6H18v2" />
    <rect x="3" y="8.5" width="18" height="10.5" rx="2.5" />
    <circle cx="16.6" cy="13.8" r="1.15" fill="currentColor" stroke="none" />
  </svg>
);
const IcCard = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="2.5" y="5.5" width="19" height="13" rx="2.5" />
    <path d="M2.5 10h19M6 14.5h3" />
  </svg>
);
const iconFor = (id) => (id === "card" ? <IcCard /> : <IcWallet />);

function Subscribe({ user, onClose, onUpgraded, initialPlan }) {
  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [pick, setPick] = useState(initialPlan || "");
  const [method, setMethod] = useState("easypaisa");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const [handoff, setHandoff] = useState(null);   // {url, plan, method} while leaving for PayPak
  const [payReady, setPayReady] = useState(true);
  const [missing, setMissing] = useState([]);

  const load = () => {
    setLoading(true);
    setErr("");
    api
      .meta()
      .then((m) => {
        const list = Object.entries(m.plans || {}).filter(([id]) => id !== "free");
        setPlans(list);
        // The server says whether the hosted checkout can open here - shown before the pay
        // button is pressed instead of failing after it.
        if (m.pay) {
          setPayReady(!!m.pay.configured);
          setMissing(m.pay.missing || []);
        }
        setPick((cur) => {
          const ids = list.map(([id]) => id);
          if (cur && ids.includes(cur) && cur !== user.plan) return cur;
          const next = list.find(([id]) => id !== user.plan);
          return (next && next[0]) || ids[0] || "";
        });
      })
      .catch((x) => setErr(x.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  // Escape closes the sheet, but never while a request or a redirect is in flight.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const plan = plans.find(([id]) => id === pick) || [];
  const cfg = plan[1] || {};
  const price = cfg.price?.pkr || 0;
  const samePlan = pick === user.plan;

  const go = async () => {
    if (!pick || !payReady || samePlan) return;
    setBusy(true);
    setErr("");
    try {
      const r = await api.checkout(pick, method);
      if (r.url) {
        // PayPak owns the payment: the browser finishes on their hosted page and is sent back
        // to /?paid=<identifier>, where the app confirms and refreshes the plan.
        setHandoff({ url: r.url, plan: r.plan_name || planName(pick), method: labelOf(method) });
        await new Promise((res) => setTimeout(res, 450));   // let the hand-off screen paint
        window.location.assign(r.url);
        return;
      }
      setDone(r);
      onUpgraded(r);
    } catch (x) {
      setErr(x.message);
      setBusy(false);
    }
  };

  if (handoff) {
    return (
      <div className="scrim">
        <div className="modal pay" role="dialog" aria-modal="true" aria-label="Opening PayPak">
          <div className="done">
            <span className="spin big" aria-hidden="true" />
            <h2>Opening secure checkout…</h2>
            <p className="muted">
              Taking you to PayPak to pay {money(price)} for the {handoff.plan} plan. Choose{" "}
              <b>{handoff.method}</b> on the next screen, then you will land back here.
            </p>
            <div className="subrow">
              <a className="btn dark big" href={handoff.url}>
                Open the payment page
              </a>
              <button className="btn" onClick={() => { setHandoff(null); setBusy(false); }}>
                Go back
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (done) {
    return (
      <div className="scrim">
        <div className="modal pay" role="dialog" aria-modal="true" aria-label="Plan active">
          <div className="done">
            <span className="ok" aria-hidden="true">✓</span>
            <h2>{done.plan_name || cfg.name} plan active</h2>
            <p className="muted">
              {cfg.results} results per category and up to {cfg.halls} hall contacts every 24
              hours. It is live on every quotation straight away.
            </p>
            <button className="btn dark big" onClick={onClose}>
              Start planning
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="modal pay" role="dialog" aria-modal="true" aria-label="Subscribe to a plan">
        <button className="xx" onClick={onClose} aria-label="Close" disabled={busy}>
          ×
        </button>

        <div className="pay-h">
          <h2>Upgrade your plan</h2>
          <p className="muted">
            Current plan: <b>{planName(user.plan)}</b>. One payment unlocks more results per
            category and more hall contacts every 24 hours.
          </p>
        </div>

        {!payReady && (
          <div className="notice bad" role="alert">
            <b>Payments are not set up on this server yet.</b>
            <span>
              {missing.length ? `${missing.join(" and ")} ` : "The PayPak keys "}must be added
              before a plan can be bought - a plan is never activated without a confirmed payment.
            </span>
          </div>
        )}

        {loading ? (
          <div className="skel" aria-hidden="true">
            <span className="spin" />
            <span className="muted">Loading plans…</span>
          </div>
        ) : plans.length === 0 ? (
          <p className="err" role="alert">
            {err || "No plans available right now."}
          </p>
        ) : (
          <>
            <div className="plans2" role="group" aria-label="Choose a plan">
              {plans.map(([id, p]) => {
                const mine = user.plan === id;
                const on = pick === id;
                return (
                  <button
                    key={id}
                    type="button"
                    className={`pcard ${on ? "on" : ""}`}
                    aria-pressed={on}
                    onClick={() => setPick(id)}
                    disabled={busy || mine}
                  >
                    <span className="pc-top">
                      <b>{p.name}</b>
                      {mine && <span className="tag t-grey">Current</span>}
                    </span>
                    <span className="pc-price">
                      {money(p.price.pkr)}
                      <small>one-time</small>
                    </span>
                    <span className="pc-feats">
                      <span>{p.results} results per category</span>
                      <span>{p.halls} hall contacts / 24h</span>
                    </span>
                    <small className="pc-note">{p.note}</small>
                  </button>
                );
              })}
            </div>

            <div className="lbl">Pay with</div>
            <div className="methods" role="radiogroup" aria-label="Payment method">
              {METHODS.map((m) => (
                <label key={m.id} className={`method ${method === m.id ? "on" : ""}`}>
                  <input
                    type="radio"
                    name="pay-method"
                    value={m.id}
                    checked={method === m.id}
                    onChange={() => setMethod(m.id)}
                    disabled={busy}
                  />
                  <span className="m-ic" aria-hidden="true">{iconFor(m.id)}</span>
                  <span className="m-tx">
                    <b>{m.name}</b>
                    <small>{m.hint}</small>
                  </span>
                  <span className="m-dot" aria-hidden="true" />
                </label>
              ))}
            </div>

            {err && (
              <p className="err" role="alert">
                {err}
              </p>
            )}

            <div className="pay-sum">
              <span>
                <b>{cfg.name || "—"}</b> plan · {labelOf(method)}
              </span>
              <b>{money(price)}</b>
            </div>

            <div className="subrow">
              <button
                className="btn dark big"
                onClick={go}
                disabled={busy || loading || !pick || samePlan || !payReady}
              >
                {busy ? (
                  <>
                    <span className="spin" aria-hidden="true" /> Opening PayPak…
                  </>
                ) : !payReady ? (
                  "Payments unavailable"
                ) : samePlan ? (
                  "Current plan"
                ) : (
                  `Pay ${money(price)}`
                )}
              </button>
              <button className="btn" onClick={onClose} disabled={busy}>
                Cancel
              </button>
            </div>

            <p className="fine">
              Secure checkout by PayPak - no card or wallet details are ever typed into this app.
              You pick <b>{labelOf(method)}</b> again on their page, and the plan starts only once
              that payment is confirmed.
            </p>
          </>
        )}
      </div>
    </div>
  );
}

export default function SubscribePlan({ user, onUpgraded, className = "btn", plan = "" }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className={className} onClick={() => setOpen(true)}>
        Upgrade plan
      </button>
      {open && (
        <Subscribe
          user={user}
          initialPlan={plan}
          onClose={() => setOpen(false)}
          onUpgraded={onUpgraded}
        />
      )}
    </>
  );
}
