/**
 * staffInitials — derive avatar initials from a staff member's first and last
 * name for the Staff list Name cell (R4.1).
 *
 * The rule (Property 7): the initials are the uppercased first character of the
 * first name followed by the uppercased first character of the last name,
 * omitting the second initial when there is no last name.
 *
 * Names are trimmed first so leading/trailing whitespace does not produce a
 * blank initial. When a name part is empty (or whitespace-only) it contributes
 * nothing, so an empty first name yields just the last initial (or '' when both
 * are empty), keeping the helper robust to partial data.
 *
 * _Requirements: 4.1_
 */
export function staffInitials(
  firstName: string | null | undefined,
  lastName: string | null | undefined,
): string {
  const first = (firstName ?? '').trim()
  const last = (lastName ?? '').trim()
  const firstInitial = first ? first.charAt(0).toUpperCase() : ''
  const lastInitial = last ? last.charAt(0).toUpperCase() : ''
  return firstInitial + lastInitial
}

export default staffInitials
