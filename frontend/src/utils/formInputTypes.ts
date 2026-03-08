/**
 * Maps form field types to the correct HTML input attributes for mobile keyboards.
 *
 * Ensures phone fields trigger the phone dialer, email fields trigger the email keyboard,
 * and numeric/currency fields trigger the numeric keyboard.
 */

export type FormFieldType = 'phone' | 'email' | 'currency' | 'numeric' | 'text'

export interface InputAttributes {
  type: string
  inputMode?: string
}

/**
 * Returns the correct HTML input `type` and optional `inputMode` attributes
 * for a given form field type, ensuring the correct mobile keyboard is triggered.
 */
export function getInputAttributes(fieldType: FormFieldType): InputAttributes {
  switch (fieldType) {
    case 'phone':
      return { type: 'tel' }
    case 'email':
      return { type: 'email' }
    case 'currency':
      return { type: 'text', inputMode: 'numeric' }
    case 'numeric':
      return { type: 'text', inputMode: 'numeric' }
    case 'text':
      return { type: 'text' }
  }
}
