import { createRoot } from "react-dom/client";
import { Studio } from "./App";
import "./index.css";

// No StrictMode: the studio is a class component that owns a long-lived WebGL context + RAF loop in
// its lifecycle; StrictMode's dev double-mount would tear down and rebuild the renderer needlessly.
createRoot(document.getElementById("root")!).render(<Studio />);
