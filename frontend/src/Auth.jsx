import { useState } from "react";
import { api, setSession } from "./api.js";
import { PHONE_RE } from "./lib.js";

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

/* signup / login / forgot. Phone + password rules are checked here first so the round trip
   is only made when the request can actually succeed. */
export default function Auth({ onDone }) {
  const [mode, setMode] = useState("signup");
  const [f, setF] = useState({ name: "", phone: "", email: "", password: "" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const up = mode === "signup";
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const go = async (e) => {
    e.preventDefault();
    setErr("");
    const email = f.email.trim().toLowerCase();
    const password = f.password;
    if (!email) return setErr("Enter your email address.");
    if (mode !== "login" && password.length < 8)
      return setErr("Use a password of 8 or more characters.");   // the server only requires this on sign up
    if (up) {
      if (!f.name.trim()) return setErr("Enter your name.");
      if (!PHONE_RE.test(f.phone.trim())) return setErr("Enter your WhatsApp number, e.g. 0300 1234567");
    }
    setBusy(true);
    try {
      if (up) setSession(await api.signup({ ...f, email }));
      else if (mode === "login") setSession(await api.login(email, password));
      else {
        await api.forgot(email, password);
        setSession(await api.login(email, password));
      }
      onDone();
    } catch (x) {
      setErr(x.message);
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <div className="auth-l">
        <Logo />
        <h1>Get a hall quotation in 5 minutes.</h1>
        <p>
          Tell us your event, pick a hall, add your menu, and we send a clean PDF quotation
          request to the hall on WhatsApp.
        </p>
        <ul className="pts">
          <li>Free to start</li>
          <li>Your quotations are saved</li>
          <li>Download them as PDF anytime</li>
        </ul>
      </div>

      <form className="card auth-f" onSubmit={go} noValidate>
        <div className="tabs2" role="tablist">
          <button type="button" role="tab" aria-selected={up} className={up ? "on" : ""} onClick={() => { setMode("signup"); setErr(""); }}>
            Sign up
          </button>
          <button type="button" role="tab" aria-selected={!up} className={!up && mode !== "forgot" ? "on" : ""} onClick={() => { setMode("login"); setErr(""); }}>
            Log in
          </button>
        </div>

        {mode === "signup" && (
          <>
            <label htmlFor="a-name">Your name</label>
            <input id="a-name" value={f.name} onChange={set("name")} required autoComplete="name" placeholder="Ayesha Khan" />
            <label htmlFor="a-ph">Your WhatsApp number</label>
            <input id="a-ph" inputMode="tel" placeholder="0300 1234567" value={f.phone} onChange={set("phone")} required autoComplete="tel" />
          </>
        )}

        <label htmlFor="a-em">Email</label>
        <input id="a-em" type="email" value={f.email} onChange={set("email")} required autoComplete="email" placeholder="you@example.com" />

        <label htmlFor="a-pw">
          Password
          {mode !== "login" && <small className="pw-hint">8 or more characters</small>}
        </label>
        <input
          id="a-pw"
          type="password"
          value={f.password}
          onChange={set("password")}
          required
          minLength={mode === "login" ? undefined : 8}
          autoComplete={mode === "signup" ? "new-password" : "current-password"}
          placeholder={mode === "login" ? "Your password" : "At least 8 characters"}
        />

        {err && (
          <p className="err" role="alert">
            {err}
          </p>
        )}

        <button className="btn dark big" disabled={busy}>
          {busy ? "Please wait…" : mode === "signup" ? "Create my account" : mode === "login" ? "Log in" : "Reset and log in"}
        </button>

        <button type="button" className="linkish" onClick={() => { setMode(mode === "forgot" ? "login" : "forgot"); setErr(""); }}>
          {mode === "forgot" ? "Back to log in" : "Forgot your password?"}
        </button>
        <p className="fine">
          Demo accounts: free@demo.pk / free (Free) · premium@demo.pk / premium (5 Search) ·
          pro@demo.pk / pro (10 Search)
        </p>
      </form>
    </div>
  );
}
