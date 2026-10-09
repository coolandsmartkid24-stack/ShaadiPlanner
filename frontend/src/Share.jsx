import { useEffect, useState } from "react";
import { api, downloadPdf } from "./api.js";
import Doc, { Logo } from "./Doc.jsx";

/* The hall's side of the link: the quotation, read only, drawn by the SAME <Doc> component the
   wizard previews with. The PDF is captured from that document, so what lands on the hall's disk
   is byte-for-byte the layout the couple was looking at - same badge, same icons, same pills,
   same date (in the reader's own local time). */
export default function Share({ id, sig, toast }) {
  const [q, setQ] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .shareView(id, sig)
      .then((d) => live && setQ(d))
      .catch((e) => live && setErr(e.message));
    return () => {
      live = false;
    };
  }, [id, sig]);

  const download = async () => {
    setBusy(true);
    try {
      await downloadPdf(document.querySelector("article.doc"));
      toast("PDF downloaded.", "success");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <header className="top">
        <Logo small />
        <div className="top-r">
          <span className="tag t-dark">Quotation</span>
        </div>
      </header>

      {err ? (
        <div className="banner bad" role="alert">
          {err}
        </div>
      ) : !q ? (
        <div className="card empty">
          <span className="spin" aria-hidden="true" />
          <p className="muted">Loading the quotation…</p>
        </div>
      ) : (
        <div className="rev">
          <Doc q={q} user={{ name: q.owner_name }} />
          <div className="send">
            <div className="card pad">
              <h3 className="h3">Save a PDF copy</h3>
              <p className="muted">
                The file is the document on this page - exactly what you see, including the icons,
                the ticked pills and today's date.
              </p>
              <button className="btn big" onClick={download} disabled={busy} data-html2canvas-ignore="true">
                {busy ? "Preparing…" : "Download PDF"}
              </button>
            </div>
            <div className="card pad">
              <h3 className="h3">Reply</h3>
              <p className="muted">
                Send your price and availability back to {q.host || q.owner_name || "the couple"} on
                WhatsApp.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
