import { useCallback, useEffect, useState } from "react";
import { ToastContainer, toast as notify } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";
import { api, getSession, setSession, clearSession, onUnauthorized } from "./api.js";
import { newQuotation, planName } from "./lib.js";
import Auth from "./Auth.jsx";
import Home from "./Home.jsx";
import Wizard from "./Wizard.jsx";

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

export default function App() {
  const [user, setUser] = useState(getSession);
  const [booting, setBooting] = useState(() => !!getSession());
  const [quotes, setQuotes] = useState(null);
  const [quotesErr, setQuotesErr] = useState("");
  const [open, setOpen] = useState(null);       // quotation being edited in the wizard

  const toast = useCallback((m, type) => {
    notify(String(m || ""), { type: type || "info" });
  }, []);

  const refresh = useCallback(async () => {
    if (!getSession()) {
      setQuotes(null);
      return;
    }
    try {
      setQuotesErr("");
      setQuotes(await api.quotations());
    } catch (e) {
      setQuotesErr(e.message);
    }
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

  // First paint: the stored token decides the account, /api/me confirms it and refreshes it.
  // PayPak returns the browser to /?paid=<identifier> (or /?cancelled=1): those parameters are
  // stripped from the URL first, then the payment is confirmed and the plan re-read from /api/me.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const paidId = params.get("paid");
    const cancelled = params.has("cancelled");
    if (paidId || cancelled) {
      params.delete("paid");
      params.delete("cancelled");
      const qs = params.toString();
      window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash);
    }
    if (!getSession()) return;
    (async () => {
      let m = null;
      try {
        m = await api.me();
      } catch {
        /* 401 already cleared the session; anything else keeps the cached one */
      }
      if (paidId) {
        try {
          const p = await api.confirmPayment(paidId);
          if (p && p.status === "success") {
            m = await api.me();
            toast(`${planName(p.plan)} plan is active.`);
          }
        } catch (x) {
          toast(x.message, "error");
        }
      } else if (cancelled) {
        toast("Payment cancelled — your plan was not changed.", "warning");
      }
      if (m) {
        setSession({ token: getSession()?.token, ...m });
        setUser(getSession());
      } else {
        setUser(getSession());
      }
      setBooting(false);
    })();
  }, [toast]);

  useEffect(() => {
    if (user && !booting) refresh();
  }, [user, booting, refresh]);

  const handleCreated = async () => {
    try {
      const q = await api.create(newQuotation(user));
      setQuotes((list) => [q, ...(list || [])]);
      setOpen(q);
    } catch (e) {
      toast(e.message, "error");
    }
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
    setUser(null);
    setQuotes(null);
    setOpen(null);
  };

  const handleUpgraded = (r) => {
    // DEV checkout carries a fresh token; the hosted PayPak checkout does not (the plan is
    // applied later, by the /?paid= confirm above) - never overwrite a good token with undefined.
    if (r?.token) setSession({ token: r.token });
    if (r?.plan) setSession({ plan: r.plan });
    setUser(getSession());
    toast(`You are on the ${r?.plan_name || planName(r?.plan)} plan now.`);
  };

  let view;
  if (booting) view = <Splash />;
  else if (!user) view = <Auth onDone={() => setUser(getSession())} />;
  else if (open) view = <Wizard initial={open} user={user} onExit={() => { setOpen(null); refresh(); }} onUpgraded={handleUpgraded} toast={toast} />;
  else
    view = (
      <Home
        user={user}
        quotes={quotes}
        loading={!quotes && !quotesErr}
        error={quotesErr}
        onNew={handleCreated}
        onOpen={setOpen}
        onDelete={handleDelete}
        onLogout={handleLogout}
        onRetry={refresh}
        onUpgraded={handleUpgraded}
      />
    );

  return (
    <>
      {view}
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
