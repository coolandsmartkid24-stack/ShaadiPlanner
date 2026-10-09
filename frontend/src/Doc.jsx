import { dayName, niceDate, todayLabel } from "./lib.js";

/* The quotation document itself - the ONE component whose rendered DOM is what the PDF is made
   of. The wizard's preview, the hall's share page and the download all point at this same
   <article class="doc"> node, so the file on disk can never drift from what was on screen. */

export function Logo({ small }) {
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

/* Stroke icons on one 24x24 grid, coloured by the surrounding text: the quotation reads as
   sections instead of a wall of uppercase labels. Inline SVG so the capture keeps them. */
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

/* q   the quotation (wizard state or the public share payload)
   user  only the display name is read - no phone number goes on the paper. */
export function Doc({ q, user }) {
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
  const hall = (q.halls || [])[0];
  return (
    <article className="doc" aria-label="Quotation preview">
      <div className="doc-h">
        <Logo />
        <div className="doc-t">
          <h3>Quotation Request</h3>
          <small>{todayLabel()}</small>
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
      <p className="doc-v">{q.host || user?.name || ""}</p>
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
      {chips(q.services || [])}
      <p className="doc-k">
        <Ico n="bowl" />
        Food menu
      </p>
      {chips(q.menu || [])}
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

export default Doc;
