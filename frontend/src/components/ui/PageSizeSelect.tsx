const PAGE_SIZE_OPTIONS = [10, 25, 50]

interface PageSizeSelectProps {
  value: number
  onChange: (size: number) => void
}

export function PageSizeSelect({ value, onChange }: PageSizeSelectProps) {
  return (
    <div className="flex items-center gap-2 text-sm text-gray-600">
      <label htmlFor="page-size-select">Show</label>
      <select
        id="page-size-select"
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="rounded border border-gray-300 px-2 py-1 text-sm"
      >
        {PAGE_SIZE_OPTIONS.map((opt) => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>
      <span>per page</span>
    </div>
  )
}
