# Test Scenarios: Staff Schedule

Covers Requirements 36-38 (schedule gaps) and 56-60 (additional schedule gaps).

---

## TS-8.1: Create schedule entry via modal

**Precondition:** Active staff members exist.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "+ New Entry" in schedule header | Modal opens with "New Schedule Entry" title |
| 2 | Select a staff member from dropdown | Staff list populated from API |
| 3 | Enter title "Oil change — Toyota Hilux" | Field accepts input |
| 4 | Select entry type "Job" | Dropdown has: Job, Booking, Break, Leave, Other |
| 5 | Set start time and end time | Datetime pickers work |
| 6 | Enter notes | Textarea accepts input |
| 7 | Click "Create" | Entry created, calendar refreshes |

**Req:** 36.1, 36.2, 36.3

---

## TS-8.2: Edit schedule entry via modal

**Precondition:** Existing schedule entry on the calendar.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click on an entry card in the calendar | Modal opens with "Edit Schedule Entry" title |
| 2 | Fields pre-populated | Staff, title, type, times, notes all filled |
| 3 | Change the title | Field updates |
| 4 | Click "Update" | Entry updated, calendar refreshes |

**Req:** 36.4, 36.5

---

## TS-8.3: Conflict detection after save

**Precondition:** Staff member has an entry from 9:00-10:00.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Create a new entry for same staff, 9:30-10:30 | Entry created |
| 2 | Conflict warning banner appears | Shows "Scheduling conflict detected" with overlapping entry details |
| 3 | Click "OK, close" | Warning dismisses, modal closes |
| 4 | Entry is still saved | Correct (warning only, not blocking) |

**Req:** 36.6

---

## TS-8.4: Validation — end time before start time

**Precondition:** Create entry modal open.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Set start time to 10:00, end time to 9:00 | Click "Create" |
| 2 | Validation error | "End time must be after start time" |

**Req:** 36.3

---

## TS-8.5: Validation — required fields

**Precondition:** Create entry modal open.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Leave start and end time empty | Click "Create" |
| 2 | Validation errors | "Start time is required", "End time is required" |

**Req:** 36.3

---

## TS-8.6: Dual sidebar entries — Schedule vs Staff Schedule

**Precondition:** User with both `scheduling` and `branch_management` modules.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Schedule" in sidebar | Navigates to `/schedule`, shows full roster calendar |
| 2 | Click "Staff Schedule" in sidebar | Navigates to `/staff-schedule`, shows branch-scoped view |
| 3 | Both pages render distinct content | Not the same page |

**Req:** 37.1, 37.2, 37.3

---

## TS-8.7: Drag-and-drop rescheduling — same day

**Precondition:** Entry at 9:00-10:00 for Staff A in day view.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Drag the entry card from 9:00 slot to 14:00 slot | Entry moves |
| 2 | Check entry times | Start: 14:00, End: 15:00 (duration preserved) |
| 3 | Calendar refreshes | Entry appears in new slot |

**Req:** 38.1, 38.2, 38.3

---

## TS-8.8: Drag-and-drop — between staff columns

**Precondition:** Entry for Staff A at 9:00.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Drag entry from Staff A's column to Staff B's column at 11:00 | Entry moves |
| 2 | Check entry | Assigned to Staff B, time = 11:00-12:00 |

**Req:** 38.2

---

## TS-8.9: Drag-and-drop — conflict warning

**Precondition:** Staff B has an entry at 11:00-12:00.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Drag another entry to Staff B's 11:00 slot | Entry moves (not blocked) |
| 2 | Conflict warning banner appears | "Schedule Conflict" with details |
| 3 | Warning auto-dismisses after 5 seconds | Or click "✕" to dismiss |

**Req:** 38.4

---

## TS-8.10: Drag requires 8px distance (not accidental)

**Precondition:** Entry card on calendar.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click on entry card (no drag) | Opens edit modal (click, not drag) |
| 2 | Click and drag 3px then release | No drag initiated, opens edit modal |
| 3 | Click and drag 10px | Drag initiated, entry follows cursor |

**Req:** 38.1

---

## TS-8.11: Recurring entry — weekly

**Precondition:** Create entry modal open.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Fill in entry details | Staff, title, times |
| 2 | Set "Repeat" to "Weekly" | Helper text: "Entries will be created for up to 4 weeks ahead" |
| 3 | Click "Create" | Multiple entries created (4 weekly occurrences) |
| 4 | Check calendar | Entries appear on the same day for 4 consecutive weeks |
| 5 | Recurring entries show 🔁 icon | Visual distinction |

**Req:** 56.1, 56.2, 56.3

---

## TS-8.12: Recurring entry — daily

**Precondition:** Create entry modal open.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Set "Repeat" to "Daily" | Selected |
| 2 | Create entry starting Monday | Entries created for Mon-Sun for 4 weeks (28 entries) |

**Req:** 56.1

---

## TS-8.13: Recurring entry — fortnightly

**Precondition:** Create entry modal open.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Set "Repeat" to "Fortnightly" | Selected |
| 2 | Create entry | 2 entries created (2 fortnightly occurrences in 4 weeks) |

**Req:** 56.1

---

## TS-8.14: Shift templates — create and use

**Precondition:** Org admin access.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "Templates" in schedule header | Templates panel opens |
| 2 | Click "+ New Template" | Form appears |
| 3 | Enter name "Morning Shift", start 08:00, end 17:00, type "Job" | Fields accept input |
| 4 | Click "Save Template" | Template created, appears in list |
| 5 | Open create entry modal | "Use Template" dropdown visible |
| 6 | Select "Morning Shift" template | Title, times, and type pre-filled |

**Req:** 57.1, 57.2, 57.3

---

## TS-8.15: Shift templates — delete

**Precondition:** Existing shift template.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "✕" next to a template | Template removed from list |

**Req:** 57.2

---

## TS-8.16: Leave entry — create and display

**Precondition:** Active staff members.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "+ Add Leave" in schedule header | Modal opens with entry type pre-set to "Leave" |
| 2 | Select staff, set dates | Fill in details |
| 3 | Create leave entry | Entry appears on calendar |
| 4 | Check visual style | Grey/hatched background, strikethrough text |
| 5 | Leave blocks other entries | Conflict detected if overlapping |

**Req:** 58.1, 58.2, 58.3

---

## TS-8.17: Schedule print

**Precondition:** Schedule with entries visible.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "🖨 Print" button | Browser print dialog opens |
| 2 | Check print preview | Schedule grid is formatted for print |
| 3 | Non-print elements hidden | Buttons, templates panel not in print |

**Req:** 59.1

---

## TS-8.18: Schedule export CSV

**Precondition:** Schedule with entries visible.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Click "📥 Export CSV" button | CSV file downloads |
| 2 | Open CSV | Columns: Staff Name, Date, Start Time, End Time, Entry Type, Title, Notes |
| 3 | Check data | Matches visible entries |

**Req:** 59.2

---

## TS-8.19: Mobile schedule view — single column

**Precondition:** Open schedule on mobile device (< 768px).

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open schedule page | Single-column layout (not multi-column grid) |
| 2 | Staff switcher dropdown visible | Shows current staff member |
| 3 | Change staff member | View updates to show selected staff's entries |
| 4 | Time slots are vertical | One slot per row, 44px min height |

**Req:** 60.1, 60.2, 60.3

---

## TS-8.20: Mobile schedule — default to current user

**Precondition:** Logged-in staff member on mobile.

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Open schedule on mobile | Auto-selects the first staff member (or current user) |
| 2 | Entries shown for that staff member | Day view with their schedule |

**Req:** 60.2
