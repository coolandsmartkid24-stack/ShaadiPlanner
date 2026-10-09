import { useCallback, useEffect, useRef, useState } from "react";
import { ToastContainer, toast as notify } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";
import { api, getSession, setSession, clearSession, onUnauthorized, settlePayment } from "./api.js";
import { newQuotation, passOf, planName } from "./lib.js";
import Auth from "./Auth.jsx";
import Home from "./Home.jsx";
import Share from "./Share.jsx";
import Wizard from "./Wizard.jsx";

const PAY_KEY = "sp.pending-payment";   // survives the trip to the gateway and back
const OPEN_KEY = "sp.open-quotation";   // which quotation the wizard had open (localStorage:
                                        // it has to come back after a crash or a closed tab)

const readPay = () => {
  try {
    return JSON.parse(sessionStorage.getItem(PAY_KEY) || "null");
  } catch {
    return null;
  }
};
const stashPay = (p) => {
  try {
    if (p) sessionStorage.setItem(PAY_KEY, JSON.stringify(p));
    else sessionStorage.removeItem(PAY_KEY);
  } catch {
    /* private mode: the confirmation simply has to happen on this page load */
  }
};
const readOpen = () => {
  try {
    return localStorage.getItem(OPEN_KEY) || "";
  } catch {
    return "";
  }
};
const stashOpen = (id) => {
  try {
    if (id) localStorage.setItem(OPEN_KEY, id);
    else localStorage.removeItem(OPEN_KEY);
  } catch {
    /* private mode: the wizard still works, it just does not reopen itself */
  }
};

// A token that came back with /api/me is the fresh one; an older backend does not send one, so
// the stored token is kept rather than being overwritten with undefined.
const keepSession = (m) => ({ ...m, token: m.token || getSession()?.token });

// A hall's link is ?share=<id>&sig=<sig> (the signed /q/ path redirects here). It is read once,
// on the way in, and never needs a session: the quotation is public to whoever holds the sig.
const readShare = () => {
  try {
    const p = new URLSearchParams(window.location.search);
    const id = p.get("share");
    const sig = p.get("sig");
    return id && sig ? { id, sig } : null;
  } catch {
    return null;
  }
};

function Splash() {
  return (
    <div className="splash">
      <div className="brand">
        <span className="mark">
          <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">
            <path d="M12 2l2.4 6.2L21 9l-5 4.3L17.5 20 12 16.4 6.5 20 8 13.3 3 9l6.6-.8z" />
          </svg>
        </span>
        Shaadi<b>Planner</b>
      </div>
      <span className="spin" aria-hidden="true" />
    </div>
  );
}

/* Shown while the return trip from PayPak is being verified. It never resolves on its own -
   settlePayment() drives it, so the user always sees that something is happening instead of a
   frozen page. */
function PayOverlay({ pass }) {
  const line =
    pass <= 1
      ? "Confirming your payment…"
      : pass < 5
      ? "Waiting for PayPak to confirm…"
      : "Checking the gateway one more time…";
  return (
    <div className="scrim" role="status" aria-live="polite">
      <div className="modal pay" role="dialog" aria-modal="true" aria-label="Confirming your payment">
        <div className="done">
          <span className="spin big" aria-hidden="true" />
          <h2>{line}</h2>
          <p className="muted">
            Keep this tab open. Your plan switches on the moment the payment is verified - this
            usually takes a few seconds.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState(getSession);
  const [booting, setBooting] = useState(() => !!getSession());
  const [quotes, setQuotes] = useState(null);
  const [quotesErr, setQuotesErr] = useState("");
  const [open, setOpen] = useState(null);       // quotation being edited in the wizard
  const [shared] = useState(readShare);         // a hall opened a link: render that quotation
  const [paying, setPaying] = useState(null);   // {pass} while PayPak is being asked to confirm
  const settling = useRef(false);

  const toast = useCallback((m, type) => {
    notify(String(m || ""), { type: type || "info" });
  }, []);

  // Reloads the list and re-opens whatever quotation the wizard had open when the tab was
  // closed - the work is already saved on the server, so the place in the wizard is too.
  const refresh = useCallback(async () => {
    if (!getSession()) {
      setQuotes(null);
      return;
    }
    try {
      setQuotesErr("");
      const list = await api.quotations();
      setQuotes(list);
      const id = readOpen();
      if (id) {
        const hit = (list || []).find((x) => x.id === id);
        if (hit) setOpen((cur) => cur || hit);
        else stashOpen("");          // deleted somewhere else: stop trying to reopen it
      }
    } catch (e) {
      setQuotesErr(e.message);
    }
  }, []);

  const openQuotation = useCallback((q) => {
    setOpen(q);
    stashOpen(q?.id || "");
  }, []);

  // A dead/expired token drops the app back to the login screen from anywhere.
  useEffect(() => {
    onUnauthorized(() => {
      setUser(null);
      setQuotes(null);
      setOpen(null);
    });
    return () => onUnauthorized(null);
  }, []);

  // The trip back from PayPak: the gateway's answer is verified here, in the open, with a
  // progress overlay. The marker stays in sessionStorage when nothing conclusive came back, so
  // a reload finishes the job instead of losing the payment.
  const finishPayment = useCallback(async () => {
    const p = readPay();
    if (!p || settling.current) return;
    settling.current = true;
    setPaying({ pass: 1 });
    try {
      const done = await settlePayment(p.id, p.extra || {}, (n) => setPaying({ pass: n }));
      if (done && done.status && done.status !== "pending") {
        stashPay(null);
        if (done.status === "success") {
          const m = await api.me().catch(() => null);
          if (m && m.email) {
            setSession(keepSession(m));
            setUser(getSession());
          } else if (!getSession()) {
            setUser(null);          // the token died while we were confirming: log in again
          }
          toast(`${planName(done.plan || done.pass)} plan is active.`, "success");
        } else {
          toast(`Payment ${done.status} - your plan was not changed.`, "error");
        }
      } else {
        toast("PayPak has not confirmed the payment yet. Reload this page in a minute to check again.", "warning");
      }
    } catch (e) {
      // Keep the marker when the account is the problem - logging back in runs this again.
      // Anything else is final, so the same failure is not replayed on every page load.
      if (!/log in/i.test(String(e?.message || ""))) stashPay(null);
      toast(e.message, "error");
    } finally {
      settling.current = false;
      setPaying(null);
    }
  }, [toast]);

  // First paint: the stored token decides the account, /api/me confirms it and refreshes it.
  // PayPak returns the browser to /?paid=<identifier> (or /?cancelled=1): those parameters are
  // stripped from the URL first, the payment is remembered, and finishPayment() confirms it.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const paidId = params.get("paid");
    const cancelled = params.has("cancelled");
    const extra = {};
    params.forEach((v, k) => {
      if (k !== "paid" && k !== "cancelled") extra[k] = v;
    });
    if (paidId || cancelled) {
      params.delete("paid");
      params.delete("cancelled");
      const qs = params.toString();
      window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash);
    }
    if (paidId) stashPay({ id: paidId, extra });
    else if (cancelled) {
      stashPay(null);
      toast("Payment cancelled - your plan was not changed.", "warning");
    }
    if (!getSession()) {
      if (paidId) toast("Payment made - log in and your plan will be activated.", "info");
      setBooting(false);
      return;
    }
    (async () => {
      let m = null;
      try {
        m = await api.me();
      } catch {
        /* 401 already cleared the session; anything else keeps the cached one */
      }
      if (m && m.email) {
        setSession(keepSession(m));
        setUser(getSession());
      } else {
        setUser(getSession());
      }
      setBooting(false);
      if (readPay()) finishPayment();
    })();
  }, [toast, finishPayment]);

  useEffect(() => {
    if (user && !booting) refresh();
  }, [user, booting, refresh]);

  // "+ New quotation" opens the wizard on the click: the POST that creates the row runs behind
  // it. Until it lands the wizard holds its edits (no id to PATCH yet) and adopts the real id
  // when it arrives, so the first screen costs no round trip.
  const handleCreated = () => {
    const draft = newQuotation(user);
    // allow is server-owned and not part of the POST body - only the wizard's first screen
    // reads it, so the plan's allowance is shown right away instead of a frame of "1 hall".
    setOpen({ ...draft, id: "", allow: passOf(user?.plan).halls });
    stashOpen("");
    api
      .create(draft)
      .then((q) => {
        setQuotes((list) => [q, ...(list || [])]);
        setOpen((cur) => (cur && cur.id === "" ? q : cur));
        stashOpen(q.id);
      })
      .catch((e) => {
        // Nothing exists server-side, so the wizard cannot save: close it rather than leave a
        // quotation that would silently discard every edit.
        setOpen((cur) => (cur && cur.id === "" ? null : cur));
        stashOpen("");
        toast(e.message, "error");
      });
  };

  const deleteQuotation = async (q) => {
    try {
      await api.remove(q.id);
      setQuotes((list) => (list || []).filter((x) => x.id !== q.id));
      toast("Quotation deleted.", "success");
    } catch (e) {
      toast(e.message, "error");
    }
  };

  // The native window.confirm blocks the page and cannot be styled: the confirmation is a
  // react-toastify toast with Delete / Cancel actions instead. It stays until one is pressed.
  const handleDelete = (q) => {
    const name = q.title || q.event_type || "";
    notify(
      ({ closeToast }) => (
        <div className="confirm">
          <span>
            Delete "{name}" quotation? This cannot be undone.
          </span>
          <div className="confirm-acts">
            <button type="button" className="go" onClick={() => { closeToast(); deleteQuotation(q); }}>
              Delete
            </button>
            <button type="button" onClick={closeToast}>Cancel</button>
          </div>
        </div>
      ),
      { autoClose: false, closeOnClick: false, closeButton: false, draggable: false, icon: false }
    );
  };

  const handleLogout = () => {
    clearSession();
    stashOpen("");
    setUser(null);
    setQuotes(null);
    setOpen(null);
  };

  const handleUpgraded = async (r) => {
    // DEV checkout carries a fresh token; the hosted PayPak checkout does not (the plan is
    // applied later, by the /?paid= confirm above) - never overwrite a good token with undefined.
    if (r?.token) setSession({ token: r.token });
    if (r?.plan) setSession({ plan: r.plan });
    if (getSession()) {
      try {
        const m = await api.me();        // the server owns the plan, so read it back
        if (m && m.email) setSession(keepSession(m));
      } catch {
        /* keep the cached copy */
      }
    }
    setUser(getSession());
    toast(`You are on the ${r?.plan_name || planName(r?.plan)} plan now.`);
  };

  let view;
  if (shared) view = <Share id={shared.id} sig={shared.sig} toast={toast} />;
  else if (booting) view = <Splash />;
  else if (!user)
    view = (
      <Auth
        onDone={() => {
          setUser(getSession());
          if (readPay()) finishPayment();   // paid, then had to log in again
        }}
      />
    );
  else if (open)
    view = (
      <Wizard
        initial={open}
        user={user}
        onExit={() => {
          setOpen(null);
          stashOpen("");            // closed on purpose: the next visit starts at step 1
          refresh();
        }}
        onUpgraded={handleUpgraded}
        toast={toast}
      />
    );
  else
    view = (
      <Home
        user={user}
        quotes={quotes}
        loading={!quotes && !quotesErr}
        error={quotesErr}
        onNew={handleCreated}
        onOpen={openQuotation}
        onDelete={handleDelete}
        onLogout={handleLogout}
        onRetry={refresh}
        onUpgraded={handleUpgraded}
      />
    );

  return (
    <>
      {view}
      {paying && <PayOverlay pass={paying.pass} />}
      <ToastContainer
        position="bottom-center"
        autoClose={4200}
        newestOnTop
        theme="dark"
        limit={3}
      />
    </>
  );
}
