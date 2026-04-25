/** Standard paginated list response wrapper */
export interface PaginatedResponse<T> {
  items: T[]
  total: number
}
