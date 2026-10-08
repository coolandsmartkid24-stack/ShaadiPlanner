import { useEffect, useState } from "react";
import { api } from "./api.js";
import { money, planName } from "./lib.js";

const METHODS = [
  ["jazzcash", "JazzCash"],
  ["easypaisa", "Easypaisa"],
  ["card", "Debit / credit card"],
];

function Subscribe({ user, onClose, onUpgraded, initialPlan }) {
  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [pick, setPick] = useState(initialPlan || "");
  const [method, setMethod] = useState("jazzcash");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const [redirecting, setRedirecting] = useState("");

  const load = () => {
    setLoading(true);
    setErr("");
    api
      .meta()
      .then((m) => {
        const list = Object.entries(m.plans || {}).filter(([id]) => id !== "free");
        setPlans(list);
        // Default to the plan asked for, otherwise the first one that is not already active.
        setPick((cur) => {
          const ids = list.map(([id]) => id);
          if (cur && ids.includes(cur)) return cur;
          const next = list.find(([id]) => id !== user.plan);
          return (next && next[0]) || ids[0] || "";
        });
      })
      .catch((x) => setErr(x.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const plan = plans.find(([id]) => id === pick) || [];
  const cfg = plan[1] || {};

  const go = async () => {
    if (!pick) return;
    setBusy(true);
    setErr("");
    try {
      const r = await api.checkout(pick, method);
      if (r.url) {
        // PayPak owns the payment: the browser finishes on their hosted page and is sent
        // back to /?paid=<identifier>, where the app confirms and refreshes the plan.
        setRedirecting(r.plan_name || "PayPak");
        window.location.href = r.url;
        return;
      }
      setDone(r);
      onUpgraded(r);
    } catch (x) {
      setErr(x.message);
      setBusy(false);
    }
  };

  if (redirecting) {
    return (
      <div className="scrim">
        <div className="modal" role="dialog" aria-modal="true" aria-label="Opening PayPak">
          <div className="done">
            <span className="spin" aria-hidden="true" />
            <h2>Opening secure checkout…</h2>
            <p className="muted">
              Taking you to PayPak to pay for the {redirecting} plan. You will land back here
              when it is done.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Subscribe to a plan">
        <button className="xx" onClick={onClose} aria-label="Close" disabled={busy}>
          ×
        </button>
        {done ? (
          <div className="done">
            <span className="ok">✓</span>
            <h2>{done.plan_name || cfg.name} plan active</h2>
            <p className="muted">
              {cfg.results} results per category and up to {cfg.halls} hall contacts every 24
              hours.
            </p>
            <button className="btn dark big" onClick={onClose}>
              Save and exit
            </button>
          </div>
        ) : (
          <>
            <h2>Subscribe to a plan</h2>
            <p className="muted">
              Current plan: <b>{planName(user.plan)}</b>. Paid plans show more halls in every
              search and allow more hall contacts every 24 hours.
            </p>
            {loading ? (
              <p className="muted">Loading plans…</p>
            ) : plans.length === 0 ? (
              <p className="err" role="alert">
                {err || "No plans available right now."}
              </p>
            ) : (
              <div className="passes">
                {plans.map(([id, p]) => (
                  <button
                    key={id}
                    className={`pass ${pick === id ? "on" : ""}`}
                    onClick={() => setPick(id)}
                    disabled={busy}
                  >
                    <b>{p.name}</b>
                    <span className="price">{money(p.price.pkr)}</span>
                    <small>
                      {p.results} results per category · {p.note}
                    </small>
                    {user.plan === id && <small>Your current plan</small>}
                  </button>
                ))}
              </div>
            )}
            {plans.length > 0 && (
              <div className="methods">
                {METHODS.map(([k, n]) => (
                  <label key={k} className={`method ${method === k ? "on" : ""}`}>
                    <input type="radio" name="plan-pm" checked={method === k} onChange={() => setMethod(k)} />
                    {n}
                  </label>
                ))}
              </div>
            )}
            {err && plans.length > 0 && (
              <p className="err" role="alert">
                {err}
              </p>
            )}
            <div className="subrow">
              <button className="btn dark big" onClick={go} disabled={busy || loading || !pick || pick === user.plan}>
                {busy ? "Processing payment…" : pick === user.plan ? "Current plan" : `Subscribe · ${money(cfg.price?.pkr || 0)}`}
              </button>
              <button className="btn" onClick={onClose} disabled={busy}>
                Save and exit
              </button>
            </div>
            <p className="fine">
              You finish on PayPak's secure page (JazzCash, Easypaisa or card). The plan is
              activated only once the payment is confirmed.
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
        Subscribe Plan
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
