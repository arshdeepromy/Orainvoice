/**
 * Validates the discount_value field based on the selected discount_type.
 *
 * Returns an error string if invalid, or null if valid.
 */
export function validateDiscountValue(
  discountValue: string | number,
  discountType: string,
): string | null {
  const dv = Number(discountValue)
  if (!discountValue || isNaN(dv)) {
    return 'Discount value is required'
  }
  if (discountType === 'percentage') {
    if (dv < 1 || dv > 100) return 'Must be between 1 and 100'
  } else if (discountType === 'fixed_amount') {
    if (dv <= 0) return 'Must be greater than 0'
  } else if (discountType === 'trial_extension') {
    if (dv <= 0 || !Number.isInteger(dv)) return 'Must be a whole number greater than 0'
  }
  return null
}
