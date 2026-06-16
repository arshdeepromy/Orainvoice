/**
 * Pure pane-resolution logic for the responsive invoice screen.
 *
 * Feature: responsive-invoice-layout
 *
 * This module contains the single pure function that decides which panes
 * (list / detail) and the Back-to-list control are visible on the invoice
 * screen as the viewport crosses the Wide_Threshold (1280px). Keeping the
 * decision pure makes it unit/property testable independently of the DOM and
 * any layout engine.
 *
 * See the design "Pure pane-resolution helper" section for the truth table.
 */

/** Which pane a sub-Wide_Threshold user is currently viewing. */
export type NarrowPane = 'list' | 'detail'

/** The visibility outcome the InvoiceList component renders from. */
export interface PaneVisibility {
  /** Render the Invoice_List_Column (master region). */
  showList: boolean
  /** Render the Invoice_Detail_Region (detail/preview or Create_View). */
  showDetail: boolean
  /** Render the Back_To_List_Control (collapsed single-pane mode only). */
  showBackControl: boolean
}

/**
 * Decide which panes are visible on the invoice screen.
 *
 * At/above the Wide_Threshold (`isWide === true`) both panes are always shown
 * side-by-side and the Back control is hidden, regardless of the other inputs
 * (including the Create_View) — Req 8.3.
 *
 * Below the Wide_Threshold exactly one pane is visible:
 * - `isCreating` forces the Create_View to be the sole pane with a Back
 *   control (Req 8.1, 8.2);
 * - otherwise the detail pane shows only when an invoice is selected AND the
 *   user's explicit `narrowPane` intent is `'detail'`;
 * - the Back control is shown iff the detail pane is shown below Wide.
 *
 * Encodes Req 1.1, 1.2, 1.3, 1.4, 1.6, 2.1, 2.2, 8.1, 8.2, 8.3.
 *
 * @param isWide      viewport is at/above the Wide_Threshold (1280px)
 * @param hasSelection an invoice is currently selected
 * @param narrowPane  the explicit pane intent below the Wide_Threshold
 * @param isCreating  the Create_View (`/invoices/new`) is active
 */
export function resolvePaneVisibility(
  isWide: boolean,
  hasSelection: boolean,
  narrowPane: NarrowPane,
  isCreating: boolean,
): PaneVisibility {
  if (isWide) {
    // Side-by-side unchanged, including the Create_View (Req 8.3).
    return { showList: true, showDetail: true, showBackControl: false }
  }
  // Below Wide: the Create_View is the sole pane with a Back control (Req 8.1, 8.2).
  const showDetail = isCreating || (hasSelection && narrowPane === 'detail')
  return { showList: !showDetail, showDetail, showBackControl: showDetail }
}
