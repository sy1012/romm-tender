---
status: accepted
decided: 2026-11-16
amends: [0029]
---

# A wide page sets Steam's Expanded class on the Quick Access placeholder itself

## Context

[ADR-0029](0029-wide-qam-pages-drive-steams-friends-expansion.md) widens a Quick Access page with two levers: a
stylesheet that lifts Steam's 300 px cap on the tab's content panel, and a `QamFriendsExpanded` message that sets the
FriendsUI store's `qamFriendsExpanded` observable, from which Steam drew the `Expanded` class that slides the Quick
Access container from `translateX(506px)` to `0`.

On the Steam client measured on the reference Deck (Chrome 126), Steam's Quick Access component computes that class as
`qamFriendsExpanded && activeTab == Friends` (`steamui/sp.js`, both the browser-view and the embedded variants), or from
a context menu open inside the menu. The message still lands — the store's handler still sets the observable — but under
any tab other than Friends the class is never applied. Measured on the device with Tender's Settings page open: the
stylesheet was in, the content panel was 806 px wide, and the container stayed at 506 px, so the page was drawn 806 px
wide behind a 348 px window and cut off at the right. Every wide page (Sync, Library, Settings, Data Management) was
affected; the narrow ones measured whole.

No message reaches the class from a tab that is not Friends, and the active tab cannot be made Friends without showing
Friends' panel.

## Decision

**A wide page also puts Steam's own `Expanded` class on the Quick Access `ViewPlaceholder` element in Steam's main
window, for exactly as long as it holds the stylesheet.** Both class names are read by key from
`quickAccessMenuClasses`, the class map that already supplies `TabGroupPanel` and `ActiveTab`; no hashed name is
written. The element is reached through `findSP()`.

- **Held, not set once.** Steam's render owns the element's `className` and rewrites it whenever what it computes
  changes, so a `MutationObserver` on the element's `class` puts `Expanded` back while the page holds it.
- **Released on every path that releases the width** — unmount, the page's tab losing `ActiveTab`, the menu closing —
  together with the stylesheet and the hide message, so the existing collapse paths carry it.
- **Never Steam's own.** If the element already carries `Expanded` when the page expands, Tender neither holds it nor
  takes it away.
- **The message stays.** It keeps Steam's own reading of the flag in step with the panel, and it is still the whole of
  the mechanism on a client that honours it under any tab.
- **Degrades to the message.** With either class key or the element missing, nothing is set and only the message goes
  out.

Measured before deciding: adding the class by hand over the debugger slid the menu to full width with Tender's Settings
page fully readable, and the width held across navigation inside and outside the panel.

## Consequences

- Tender now writes to an element of Steam's own UI, where ADR-0029 only sent a message Steam itself understands. The
  write is one class Steam defines for this very purpose, on the element Steam applies it to, and it is undone on every
  collapse path; a path that failed to undo it would leave Steam's menu wide until its own render dropped the class or
  Steam restarted.
- Releasing the class takes it off even if Steam's own computation would want it on at that instant — the Friends tab
  becoming active with its own expansion in the same moment. Steam's next render of the element puts its own value back.
- If a later client stops honouring the class, renames the keys, or stops having the browser view follow the element,
  wide pages are cut off at the right again; nothing in the start-up check asks after class-map keys, so the symptom is
  what shows it.
