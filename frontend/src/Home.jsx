import { useEffect, useState } from "react";
import { api } from "./api.js";
import { money, niceDate, fmtWait, initials, planName } from "./lib.js";
import SubscribePlan from "./Subscribe.jsx";

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

/* Home: the account header, the free-contact status (server-owned number, refreshed every 30s)
   and the list of saved quotations. */
export default function Home({ user, quotes, loading, error, onNew, onOpen, onDelete, onLogout, onRetry, onUpgraded }) {
  const [nextFree, setNextFree] = useState(0);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let live = true;
    api.me().then((m) => live && setNextFree(m.next_free_at || 0)).catch(() => {});
    const t = setInterval(() => setTick((x) => x + 1), 30000);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, []);

  const wait = nextFree ? nextFree * 1000 - Date.now() : 0;
  const ready = !nextFree || wait <= 0;
  const name = (user.name || "").trim();
  const first = name.split(" ")[0] || "there";

  return (
    <div className="page">
      <header className="top">
        <Logo small />
        <div className="top-r">
          <span className="tag t-dark">{planName(user.plan)}</span>
          <span className="who" title={user.email}>
            {initials(name || user.email) || "SP"}
          </span>
          <SubscribePlan user={user} onUpgraded={onUpgraded} />
          <button className="btn" onClick={onLogout}>
            Log out
          </button>
        </div>
      </header>

      <section className="welcome">
        <div>
          <h1>Salam, {first}</h1>
          <p>Plan your event and ask halls for a quotation.</p>
        </div>
        <button className="btn dark big" onClick={onNew}>
          + New quotation
        </button>
      </section>

      <section className="card status">
        <div>
          <b>
            {ready
              ? user.plan && user.plan !== "free"
                ? "Your hall contacts are ready"
                : "Your free hall contact is ready"
              : `Next hall contact in ${fmtWait(wait)}`}
          </b>
          <p>
            {user.plan && user.plan !== "free"
              ? `Your ${planName(user.plan)} plan: ${user.plan === "p10" ? "10 results per category and 20 hall contacts" : "5 results per category and 8 hall contacts"} every 24 hours.`
              : "Free: 1 hall every 24 hours. Upgrade to 5 Search for Rs 100 (8 contacts a day) or 10 Search for Rs 500 (20 contacts a day)."}
          </p>
        </div>
        <span className={`tag ${ready ? "t-mint" : "t-peach"}`} key={tick}>
          {ready ? "Ready" : "Waiting"}
        </span>
      </section>

      <h2 className="h2">Your quotations</h2>

      {error && (
        <div className="banner bad" role="alert">
          {error}
          <button className="btn" type="button" onClick={onRetry}>
            Retry
          </button>
        </div>
      )}

      {loading && !error ? (
        <div className="card empty">
          <span className="spin" aria-hidden="true" />
          <p className="muted">Loading your quotations…</p>
        </div>
      ) : quotes && quotes.length === 0 ? (
        <div className="card empty">
          <p>No quotations yet.</p>
          <button className="btn dark" onClick={onNew}>
            Create your first one
          </button>
        </div>
      ) : (
        quotes && (
          <div className="qlist">
            {quotes.map((q) => (
              <article key={q.id} className="card q">
                <div className="q-main">
                  <h3>{q.title || `${q.event_type} quotation`}</h3>
                  <p>
                    {niceDate(q.event_date)} · {q.slot} · {q.guests} guests · {money(q.budget)}
                  </p>
                  <p className="muted">{q.halls.length ? q.halls.map((h) => h.name).join(", ") : "No hall chosen yet"}</p>
                </div>
                <div className="q-r">
                  <span className={`tag ${q.sent.length ? "t-mint" : "t-grey"}`}>
                    {q.sent.length ? `Sent to ${q.sent.length}` : q.status === "sent" ? "Sent" : "Draft"}
                  </span>
                  <button className="btn" onClick={() => onOpen(q)}>
                    Open
                  </button>
                  <button className="btn ghost" onClick={() => onDelete(q)} aria-label={`Delete ${q.title || q.event_type}`}>
                    Delete
                  </button>
                </div>
              </article>
            ))}
          </div>
        )
      )}
    </div>
  );
}
