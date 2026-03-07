import { useState, useCallback } from 'react'

export interface ValidationRule {
  validate: (value: string) => boolean
  message: string
}

export interface FieldConfig {
  rules: ValidationRule[]
}

export interface FormValidationConfig {
  [fieldName: string]: FieldConfig
}

export interface FormValidationResult {
  values: Record<string, string>
  errors: Record<string, string>
  touched: Record<string, boolean>
  setValue: (field: string, value: string) => void
  setTouched: (field: string) => void
  validateField: (field: string) => string
  validateAll: () => boolean
  reset: () => void
  getFieldProps: (field: string) => {
    value: string
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => void
    onBlur: () => void
  }
}

export function useFormValidation(
  config: FormValidationConfig,
  initialValues: Record<string, string> = {},
): FormValidationResult {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const defaults: Record<string, string> = {}
    for (const key of Object.keys(config)) {
      defaults[key] = initialValues[key] ?? ''
    }
    return defaults
  })

  const [errors, setErrors] = useState<Record<string, string>>({})
  const [touched, setTouchedState] = useState<Record<string, boolean>>({})

  const validateField = useCallback(
    (field: string): string => {
      const fieldConfig = config[field]
      if (!fieldConfig) return ''

      const value = values[field] ?? ''
      for (const rule of fieldConfig.rules) {
        if (!rule.validate(value)) {
          setErrors((prev) => ({ ...prev, [field]: rule.message }))
          return rule.message
        }
      }
      setErrors((prev) => {
        const next = { ...prev }
        delete next[field]
        return next
      })
      return ''
    },
    [config, values],
  )

  const setValue = useCallback((field: string, value: string) => {
    setValues((prev) => ({ ...prev, [field]: value }))
  }, [])

  const setTouched = useCallback(
    (field: string) => {
      setTouchedState((prev) => ({ ...prev, [field]: true }))
      validateField(field)
    },
    [validateField],
  )

  const validateAll = useCallback((): boolean => {
    const newErrors: Record<string, string> = {}
    const newTouched: Record<string, boolean> = {}
    let valid = true

    for (const field of Object.keys(config)) {
      newTouched[field] = true
      const fieldConfig = config[field]
      const value = values[field] ?? ''
      for (const rule of fieldConfig.rules) {
        if (!rule.validate(value)) {
          newErrors[field] = rule.message
          valid = false
          break
        }
      }
    }

    setErrors(newErrors)
    setTouchedState(newTouched)
    return valid
  }, [config, values])

  const reset = useCallback(() => {
    const defaults: Record<string, string> = {}
    for (const key of Object.keys(config)) {
      defaults[key] = initialValues[key] ?? ''
    }
    setValues(defaults)
    setErrors({})
    setTouchedState({})
  }, [config, initialValues])

  const getFieldProps = useCallback(
    (field: string) => ({
      value: values[field] ?? '',
      onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
        setValue(field, e.target.value)
      },
      onBlur: () => {
        setTouched(field)
      },
    }),
    [values, setValue, setTouched],
  )

  return {
    values,
    errors,
    touched,
    setValue,
    setTouched,
    validateField,
    validateAll,
    reset,
    getFieldProps,
  }
}

/** Common validation rules using plain language messages */
export const rules = {
  required: (label: string): ValidationRule => ({
    validate: (v) => v.trim().length > 0,
    message: `Please enter your ${label.toLowerCase()}`,
  }),
  email: (): ValidationRule => ({
    validate: (v) => v === '' || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v),
    message: 'Please enter a valid email address',
  }),
  minLength: (label: string, min: number): ValidationRule => ({
    validate: (v) => v.length === 0 || v.length >= min,
    message: `${label} must be at least ${min} characters`,
  }),
  phone: (): ValidationRule => ({
    validate: (v) => v === '' || /^[\d\s+()-]{7,20}$/.test(v),
    message: 'Please enter a valid phone number',
  }),
}
