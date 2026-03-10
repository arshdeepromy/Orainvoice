/**
 * Pure helper functions for BookingForm logic.
 * Extracted for testability (property-based testing).
 */

/**
 * Determines whether a customer search API call should be triggered
 * based on the query length. Minimum 2 characters required.
 */
export function shouldTriggerCustomerSearch(query: string): boolean {
  return query.trim().length >= 2
}

/**
 * Determines whether the "Add new customer" option should be shown
 * in the dropdown. Shown when search returns zero results and
 * the query is at least 2 characters.
 */
export function shouldShowAddNewOption(
  query: string,
  resultCount: number,
): boolean {
  return resultCount === 0 && query.trim().length >= 2
}

/**
 * Determines whether a search query looks like a name (alphabetic
 * characters and spaces only) and returns the pre-populated value
 * for the inline customer first name field.
 * Returns the trimmed query if it looks like a name, otherwise empty string.
 */
export function getPrePopulatedFirstName(query: string): string {
  const trimmed = query.trim()
  if (/^[a-zA-Z\s]+$/.test(trimmed) && trimmed.length > 0) {
    return trimmed
  }
  return ''
}

/**
 * Represents a service catalogue item with active status and optional pricing.
 */
export interface ServiceCatalogueItem {
  name: string
  is_active: boolean
  default_price: string | null
}

/**
 * Filters service catalogue items to only include active services
 * that have valid pricing (non-null, non-empty default_price).
 * Used by the Service_Selector to ensure only bookable services are shown.
 */
export function filterActiveServicesWithPricing(
  services: ServiceCatalogueItem[],
): ServiceCatalogueItem[] {
  return services.filter(
    (s) => s.is_active === true && s.default_price != null && s.default_price.trim() !== '',
  )
}

