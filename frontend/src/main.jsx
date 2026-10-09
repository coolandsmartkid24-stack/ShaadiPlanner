import React from "react";
import { createRoot } from "react-dom/client";
// The face is bundled (the woff2 files ship with the app), never fetched from a font CDN: the
// capture of the preview must not depend on a network font that could fail to load.
import "@fontsource/plus-jakarta-sans/400.css";
import "@fontsource/plus-jakarta-sans/500.css";
import "@fontsource/plus-jakarta-sans/600.css";
import "@fontsource/plus-jakarta-sans/700.css";
import "@fontsource/plus-jakarta-sans/800.css";
import App from "./App.jsx";
import "./styles.css";
createRoot(document.getElementById("root")).render(<App />);
