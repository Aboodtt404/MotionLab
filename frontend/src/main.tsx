import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./theme.css";

// No StrictMode: the studio owns a long-lived WebGL context + RAF loop; StrictMode's dev
// double-mount would tear down and rebuild the renderer needlessly.
createRoot(document.getElementById("root")!).render(<App />);
