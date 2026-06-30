/* The design's <svg><defs> symbol sheet — referenced via <use href="#i-…">. Verbatim from the
 * MotionLab Studio dc.html, transcribed to JSX (attributes already use the SVG presentation names
 * React accepts: stroke-width, stroke-linejoin, etc. stay as-is on SVG elements in React 18). */
import React from "react";

export function IconDefs() {
  return (
    <svg width="0" height="0" style={{ position: "absolute", overflow: "hidden" }} aria-hidden="true">
      <defs dangerouslySetInnerHTML={{ __html: SYMBOLS }} />
    </svg>
  );
}

// Kept as raw SVG markup (presentation attributes use hyphenated names) injected once into <defs>.
const SYMBOLS = `
<symbol id="i-solid" viewBox="0 0 24 24"><path d="M12 3 21 8 12 13 3 8Z" fill="currentColor" opacity=".95"/><path d="M3 8 12 13 12 21 3 16Z" fill="currentColor" opacity=".5"/><path d="M21 8 12 13 12 21 21 16Z" fill="currentColor" opacity=".72"/></symbol>
<symbol id="i-wire" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"><path d="M12 3 21 8 21 16 12 21 3 16 3 8Z"/><path d="M3 8 12 13 21 8M12 13 12 21"/></g></symbol>
<symbol id="i-xray" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round"><path d="M12 3 21 8 21 16 12 21 3 16 3 8Z"/><path d="M3 8 12 13 21 8M12 13 12 21" opacity=".95"/><path d="M3 8 12 8 21 8M12 8 12 3" stroke-dasharray="1.7 1.9" opacity=".5"/></g></symbol>
<symbol id="i-turntable" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"><ellipse cx="12" cy="15.5" rx="8.5" ry="3.1"/><path d="M9 8.6h6v4.3h-6z"/></g><path d="M20.2 14.1 21.4 15.9 19.2 16Z" fill="currentColor"/></symbol>
<symbol id="i-light" viewBox="0 0 24 24"><circle cx="13.5" cy="12" r="5.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M13.5 6.7a5.3 5.3 0 0 1 0 10.6z" fill="currentColor" opacity=".8"/><g stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M3 6 5.4 7.6M2.6 12h2.8M3 18 5.4 16.4"/></g></symbol>
<symbol id="i-frame" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 8.5V5h3.5M16.5 5H20v3.5M20 15.5V19h-3.5M7.5 19H4v-3.5"/></g><rect x="9.8" y="10.3" width="4.4" height="3.4" rx=".6" fill="currentColor"/></symbol>
<symbol id="i-snap" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8"/><path d="M12 4 8.4 10.2M19.4 8 12.5 9.6M19.4 16 14 11M12 20 15.6 13.8M4.6 16 11 12.4M4.6 8 10 13"/></g></symbol>
<symbol id="i-fault" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"><path d="M12 3 19 7 19 15 12 19 5 15 5 7Z"/><path d="M13 6.5 9.3 12 12.4 12 10.6 17"/></g></symbol>
<symbol id="i-move" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 13.5V4.6M12 4.6 10.2 6.7M12 4.6 13.8 6.7"/><path d="M12 13.5 19.2 17.6M19.2 17.6 16.6 17.5M19.2 17.6 18.9 15"/><path d="M12 13.5 4.8 17.6M4.8 17.6 7.4 17.5M4.8 17.6 5.1 15"/></g><circle cx="12" cy="13.5" r="1.4" fill="currentColor"/></symbol>
<symbol id="i-rotate" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9.6a7 7 0 1 1-1.3 5"/><path d="M6 9.6 5.5 6.5M6 9.6 9.1 9.2"/></g></symbol>
<symbol id="i-scale" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="13" width="7" height="7" rx="1"/><path d="M13.5 10.5 20 4"/><path d="M20 4 15.6 4M20 4 20 8.4"/><path d="M13.5 10.5 16 10.5M13.5 10.5 13.5 8"/></g></symbol>
<symbol id="i-generate" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"><path d="M12 3 20 7.5 20 16.5 12 21 4 16.5 4 7.5Z"/><path d="M4 7.5 12 12 20 7.5M12 12 12 21" opacity=".55"/><path d="M12 5.6V9.4M10.1 7.5H13.9"/></g></symbol>
<symbol id="i-eye" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 12C5 7.2 8.4 5 12 5s7 2.2 9.5 7c-2.5 4.8-5.9 7-9.5 7s-7-2.2-9.5-7Z"/><circle cx="12" cy="12" r="2.6"/></g></symbol>
<symbol id="i-eye-off" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 12C5 7.2 8.4 5 12 5s7 2.2 9.5 7c-2.5 4.8-5.9 7-9.5 7s-7-2.2-9.5-7Z" opacity=".55"/><circle cx="12" cy="12" r="2.6" opacity=".55"/><path d="M4 4 20 20"/></g></symbol>
<symbol id="i-upload" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V5M8 9l4-4 4 4"/><path d="M5 15v3a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 19 18v-3"/></g></symbol>
<symbol id="i-clock" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8"/><path d="M12 7.6V12l3 1.8"/></g></symbol>
<symbol id="i-play" viewBox="0 0 24 24"><path d="M9 7.2 17 12 9 16.8Z" fill="currentColor"/></symbol>
<symbol id="i-pause" viewBox="0 0 24 24"><rect x="8" y="7.5" width="2.7" height="9" rx=".8" fill="currentColor"/><rect x="13.3" y="7.5" width="2.7" height="9" rx=".8" fill="currentColor"/></symbol>
<symbol id="i-chevron" viewBox="0 0 24 24"><path d="M6 9 12 15 18 9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="thumb-rock" viewBox="0 0 24 24"><path d="M5 15 8 8 14 6 19 11 17 18 9 19Z" fill="currentColor"/></symbol>
<symbol id="thumb-tree" viewBox="0 0 24 24"><path d="M11 13h2v6h-2z" fill="currentColor" opacity=".6"/><path d="M12 4 17.5 13H6.5Z" fill="currentColor"/></symbol>
<symbol id="thumb-arch" viewBox="0 0 24 24"><path d="M5 19V11a7 7 0 0 1 14 0v8h-3.2v-8a3.8 3.8 0 0 0-7.6 0v8Z" fill="currentColor"/></symbol>
<symbol id="thumb-box" viewBox="0 0 24 24"><path d="M12 4 19 8 12 12 5 8Z" fill="currentColor" opacity=".95"/><path d="M5 8 12 12 12 20 5 16Z" fill="currentColor" opacity=".6"/><path d="M19 8 12 12 12 20 19 16Z" fill="currentColor" opacity=".78"/></symbol>
<symbol id="thumb-mushroom" viewBox="0 0 24 24"><path d="M6 11.5a6 6 0 0 1 12 0Z" fill="currentColor"/><path d="M10 11.5h4v7.5h-4z" fill="currentColor" opacity=".55"/></symbol>
<symbol id="thumb-terrain" viewBox="0 0 24 24"><path d="M3 18 9 11.5 13 15 21 7.5V20H3Z" fill="currentColor"/></symbol>
`;
