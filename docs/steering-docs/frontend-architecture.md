# Frontend Architecture — React Patterns for SaaS Applications

This document covers React architecture patterns for multi-tenant SaaS applications, including context usage, error handling, layout patterns, and common pitfalls.

## Why This Matters

Frontend architecture decisions compound over time. Poor patterns lead to:
- White-screen crashes that affect all users
- State management bugs that are hard to reproduce
- Layout issues that break on certain screen sizes
- Performance problems from unnecessary re-renders
- Accessibility failures that exclude users

---

## Pattern 1: Context Architecture

Use React Context for cross-cutting concerns that many components need:

```
App
├── AuthContext          — User identity, tokens, login/logout
├── TenantContext        — Organisation settings, branding, business type
├── ModuleContext        — Enabled/disabled feature modules
├── ThemeContext         — Dark mode, color preferences
└── [Feature Contexts]   — Feature-specific state (sparingly)
```

### Context Best Practices

```tsx
// 1. Provide typed context with sensible defaults
interface TenantContextValue {
  orgName: string
  businessType: string | null
  settings: OrgSettings | null
  isLoading: boolean
  refetch: () => void
}

const TenantContext = createContext<TenantContextValue>({
  orgName: '',
  businessType: null,
  settings: null,
  isLoading: true,
  refetch: () => {},
})

// 2. Custom hook for consuming (avoids null checks everywhere)
export function useTenant() {
  const context = useContext(TenantContext)
  if (!context) throw new Error('useTenant must be used within TenantProvider')
  return context
}

// 3. Provider fetches data with proper cleanup
export function TenantProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<OrgSettings | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const { user } = useAuth()

  useEffect(() => {
    if (!user || user.role === 'global_admin') {
      setIsLoading(false)
      return
    }
    const controller = new AbortController()
    const fetch = async () => {
      try {
        const res = await api.get('/org/settings', { signal: controller.signal })
        setData(res.data)
      } catch (err) {
        if (!controller.signal.aborted) console.error('Failed to load tenant')
      } finally {
        setIsLoading(false)
      }
    }
    fetch()
    return () => controller.abort()
  }, [user])

  // ... render provider
}
```

### When NOT to Use Context

- **Frequently changing values** (mouse position, scroll offset) — causes re-renders of all consumers
- **Server state** — use a data-fetching library (React Query, SWR) instead
- **Form state** — keep local to the form component
- **Derived/computed values** — compute in the component, don't store in context

---

## Pattern 2: Layout Architecture

### Fixed Layout with Scrollable Content

```tsx
// Root layout — fills viewport, no scroll
<div className="h-screen flex overflow-hidden">
  {/* Sidebar — fixed width, scrolls independently */}
  <aside className="w-64 overflow-y-auto border-r">
    <nav>...</nav>
  </aside>
  
  {/* Main content area — fills remaining space, scrolls */}
  <div className="flex-1 flex flex-col overflow-hidden">
    {/* Header — fixed at top */}
    <header className="h-16 border-b flex items-center px-6">...</header>
    
    {/* Scrollable content */}
    <main className="flex-1 overflow-y-auto p-4 lg:p-6">
      {/* Page content renders here */}
      <Outlet />
    </main>
  </div>
</div>
```

### Critical Rule: Pages Inside Layouts

Pages rendered inside a layout should NEVER use viewport-relative heights:

```tsx
// WRONG — conflicts with layout's scroll container
function OrdersPage() {
  return <div className="min-h-screen">...</div>  // ← breaks scrolling
}

// CORRECT — fills parent or flows naturally
function OrdersPage() {
  return <div className="h-full">...</div>  // ← fills the <main> container
}

// CORRECT — for edge-to-edge layouts (split panes, POS)
function SplitPanePage() {
  return <div className="h-full -m-4 lg:-m-6">...</div>  // ← cancels parent padding
}
```

### Standalone Pages (No Layout)

Auth pages, public pages, and full-screen experiences that own their viewport:

```tsx
// These CAN use viewport heights — they're not inside a layout
function LoginPage() {
  return <div className="min-h-screen flex items-center justify-center">...</div>
}
```

---

## Pattern 3: Error Boundaries

Wrap major sections in error boundaries to prevent one component crash from taking down the entire app:

```tsx
import { Component, ErrorInfo, ReactNode } from 'react'

class ErrorBoundary extends Component<
  { children: ReactNode; fallback?: ReactNode },
  { hasError: boolean; error: Error | null }
> {
  state = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info.componentStack)
    // Send to error tracking service
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback || (
        <div className="p-8 text-center">
          <h2 className="text-lg font-semibold text-red-600">Something went wrong</h2>
          <p className="mt-2 text-gray-600">Please refresh the page or try again later.</p>
          <button onClick={() => this.setState({ hasError: false })} className="mt-4 btn">
            Try Again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
```

**Where to place error boundaries:**
- Around each major page/route
- Around third-party components (charts, maps, editors)
- Around data-dependent sections that might crash on malformed data
- NOT around the entire app (you'd lose all UI on any error)

---

## Pattern 4: Loading and Empty States

Every data-fetching component needs three states:

```tsx
function OrderList() {
  const [orders, setOrders] = useState<Order[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Loading state
  if (isLoading) return <Spinner />
  
  // Error state
  if (error) return <ErrorBanner message={error} onRetry={refetch} />
  
  // Empty state
  if (orders.length === 0) return <EmptyState title="No orders yet" action={...} />
  
  // Data state
  return <OrderTable orders={orders} />
}
```

**Never leave a blank screen.** Users should always see feedback about what's happening.

---

## Pattern 5: Route Guards

Protect routes based on authentication, roles, or feature flags:

```tsx
function RequireAuth({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth()
  if (isLoading) return <Spinner />
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

function RequireRole({ roles, children }: { roles: string[]; children: ReactNode }) {
  const { user } = useAuth()
  if (!user || !roles.includes(user.role)) return <Navigate to="/dashboard" replace />
  return <>{children}</>
}

function RequireModule({ module, children }: { module: string; children: ReactNode }) {
  const { isModuleEnabled } = useModules()
  if (!isModuleEnabled(module)) return <Navigate to="/dashboard" replace />
  return <>{children}</>
}

// Usage in router
<Route path="/admin/*" element={
  <RequireRole roles={['global_admin']}>
    <AdminLayout />
  </RequireRole>
} />
```

---

## Pattern 6: API Client Configuration

```typescript
import axios from 'axios'

const apiClient = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// Auth interceptor — attach token to every request
apiClient.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Response interceptor — handle 401 (token expired)
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401 && !error.config._retry) {
      error.config._retry = true
      const newToken = await refreshToken()
      if (newToken) {
        error.config.headers.Authorization = `Bearer ${newToken}`
        return apiClient(error.config)
      }
    }
    return Promise.reject(error)
  }
)
```

---

## Pattern 7: Form Handling

For complex forms, keep state local and validate before submission:

```tsx
function CreateOrderForm() {
  const [formData, setFormData] = useState<OrderFormData>(initialState)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [isSubmitting, setIsSubmitting] = useState(false)

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {}
    if (!formData.customerName) newErrors.customerName = 'Required'
    if (formData.items.length === 0) newErrors.items = 'Add at least one item'
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!validate()) return
    setIsSubmitting(true)
    try {
      await api.post('/orders', formData)
      navigate('/orders')
    } catch (err) {
      setErrors({ form: 'Failed to create order. Please try again.' })
    } finally {
      setIsSubmitting(false)
    }
  }

  return <form onSubmit={handleSubmit}>...</form>
}
```

---

## Pattern 8: Responsive Design Rules

For SaaS applications that work on desktop and tablet:

```tsx
// Mobile-first breakpoints
<div className="
  grid grid-cols-1        // Mobile: single column
  md:grid-cols-2          // Tablet: two columns
  lg:grid-cols-3          // Desktop: three columns
  gap-4
">

// Hide on mobile, show on desktop
<div className="hidden lg:block">Desktop sidebar</div>

// Stack on mobile, row on desktop
<div className="flex flex-col md:flex-row gap-4">
```

### Touch Targets

All interactive elements must be at least 44×44 CSS pixels:

```tsx
<button className="min-h-[44px] min-w-[44px] px-4 py-2">
  Click me
</button>
```

---

## Common Mistakes to Avoid

| Mistake | Correct Approach |
|---------|-----------------|
| `min-h-screen` inside a layout | Use `h-full` or let content flow naturally |
| Fetching in context without AbortController | Always return cleanup function |
| `as any` on API responses | Use typed generics on API calls |
| Hardcoding currency symbols | Use `Intl.NumberFormat` with locale |
| Storing server state in context | Use React Query/SWR for server state |
| One giant error boundary | Multiple boundaries around major sections |
| No loading/empty states | Always show feedback for all states |
| Inline styles for layout | Use Tailwind utility classes consistently |

---

## Checklist

- [ ] Context providers have AbortController cleanup in useEffect
- [ ] Context providers handle the case where user is not authenticated
- [ ] Pages inside layouts don't use viewport-relative heights
- [ ] Error boundaries wrap major page sections
- [ ] Every data-fetching component has loading, error, and empty states
- [ ] Routes are protected with appropriate guards (auth, role, module)
- [ ] API client has auth interceptor and token refresh logic
- [ ] Forms validate before submission and show field-level errors
- [ ] Interactive elements meet 44×44px minimum touch target
- [ ] No `as any` type assertions on API responses
