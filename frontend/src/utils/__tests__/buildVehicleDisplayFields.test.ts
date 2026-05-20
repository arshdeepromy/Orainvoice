/**
 * Unit tests for buildVehicleDisplayFields utility.
 *
 * Validates: Requirements 1.1, 1.3, 2.1–2.7, 3.1–3.4
 */
import { describe, it, expect } from 'vitest'
import {
  buildVehicleDisplayFields,
  VehicleDisplayData,
} from '../buildVehicleDisplayFields'

const baseData: VehicleDisplayData = {
  rego: 'ABC123',
  make: 'Toyota',
  model: 'Hilux',
  year: 2019,
  odometer: 85000,
  inspection_type: 'wof',
  wof_expiry: '2026-08-15',
  cof_expiry: null,
  service_due_date: '2026-09-01',
  wof_updated: false,
  cof_updated: false,
  service_due_updated: false,
}

const issueDate = '2025-06-01'

describe('buildVehicleDisplayFields', () => {
  describe('Display order', () => {
    it('returns fields in correct order: Registration → Vehicle → Odometer → WOF Expiry', () => {
      const fields = buildVehicleDisplayFields(baseData, issueDate)
      const labels = fields.map((f) => f.label)
      expect(labels).toEqual(['Registration', 'Vehicle', 'Odometer', 'WOF Expiry'])
    })

    it('returns fields in correct order with service due replacing odometer', () => {
      const data: VehicleDisplayData = {
        ...baseData,
        service_due_updated: true,
        wof_updated: true,
      }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const labels = fields.map((f) => f.label)
      expect(labels).toEqual(['Registration', 'Vehicle', 'Service Due', 'WOF Expiry'])
    })
  })

  describe('Null omission', () => {
    it('omits fields with null values', () => {
      const data: VehicleDisplayData = {
        ...baseData,
        rego: null,
        make: null,
        model: null,
        year: null,
        odometer: null,
        wof_expiry: null,
      }
      const fields = buildVehicleDisplayFields(data, issueDate)
      expect(fields).toEqual([])
    })

    it('returns empty array when all fields are null', () => {
      const data: VehicleDisplayData = {
        rego: null,
        make: null,
        model: null,
        year: null,
        odometer: null,
        inspection_type: null,
        wof_expiry: null,
        cof_expiry: null,
        service_due_date: null,
        wof_updated: false,
        cof_updated: false,
        service_due_updated: false,
      }
      const fields = buildVehicleDisplayFields(data, issueDate)
      expect(fields).toEqual([])
    })

    it('omits odometer when value is 0', () => {
      const data: VehicleDisplayData = { ...baseData, odometer: 0 }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const labels = fields.map((f) => f.label)
      expect(labels).not.toContain('Odometer')
    })
  })

  describe('Service Due Date conditional logic', () => {
    it('shows Service Due and omits Odometer when service_due_updated is true', () => {
      const data: VehicleDisplayData = { ...baseData, service_due_updated: true }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const labels = fields.map((f) => f.label)
      expect(labels).toContain('Service Due')
      expect(labels).not.toContain('Odometer')
    })

    it('shows Odometer and omits Service Due when service_due_updated is false', () => {
      const data: VehicleDisplayData = { ...baseData, service_due_updated: false }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const labels = fields.map((f) => f.label)
      expect(labels).toContain('Odometer')
      expect(labels).not.toContain('Service Due')
    })

    it('omits Service Due when service_due_updated is true but service_due_date is null', () => {
      const data: VehicleDisplayData = {
        ...baseData,
        service_due_updated: true,
        service_due_date: null,
      }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const labels = fields.map((f) => f.label)
      expect(labels).not.toContain('Service Due')
      expect(labels).not.toContain('Odometer')
    })
  })

  describe('Service Due hint calculation', () => {
    it('includes hint "or due at {odometer + 10000} km" when odometer > 0', () => {
      const data: VehicleDisplayData = {
        ...baseData,
        service_due_updated: true,
        odometer: 115000,
      }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const serviceDue = fields.find((f) => f.label === 'Service Due')
      expect(serviceDue?.hint).toBe('or due at 125,000 km')
    })

    it('omits hint when odometer is null', () => {
      const data: VehicleDisplayData = {
        ...baseData,
        service_due_updated: true,
        odometer: null,
      }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const serviceDue = fields.find((f) => f.label === 'Service Due')
      expect(serviceDue?.hint).toBeUndefined()
    })

    it('omits hint when odometer is 0', () => {
      const data: VehicleDisplayData = {
        ...baseData,
        service_due_updated: true,
        odometer: 0,
      }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const serviceDue = fields.find((f) => f.label === 'Service Due')
      expect(serviceDue?.hint).toBeUndefined()
    })
  })

  describe('WOF/COF conditional visibility', () => {
    it('shows WOF when wof_updated is true', () => {
      const data: VehicleDisplayData = { ...baseData, wof_updated: true }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const labels = fields.map((f) => f.label)
      expect(labels).toContain('WOF Expiry')
    })

    it('shows WOF when wof_updated is false and wof_expiry is after issueDate', () => {
      const data: VehicleDisplayData = {
        ...baseData,
        wof_updated: false,
        wof_expiry: '2026-08-15', // after issueDate 2025-06-01
      }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const labels = fields.map((f) => f.label)
      expect(labels).toContain('WOF Expiry')
    })

    it('hides WOF when wof_updated is false and wof_expiry is before issueDate', () => {
      const data: VehicleDisplayData = {
        ...baseData,
        wof_updated: false,
        wof_expiry: '2025-01-01', // before issueDate 2025-06-01
      }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const labels = fields.map((f) => f.label)
      expect(labels).not.toContain('WOF Expiry')
    })

    it('hides WOF when wof_updated is false and wof_expiry equals issueDate', () => {
      const data: VehicleDisplayData = {
        ...baseData,
        wof_updated: false,
        wof_expiry: '2025-06-01', // equals issueDate
      }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const labels = fields.map((f) => f.label)
      expect(labels).not.toContain('WOF Expiry')
    })

    it('shows COF when inspection_type is cof and cof_updated is true', () => {
      const data: VehicleDisplayData = {
        ...baseData,
        inspection_type: 'cof',
        cof_expiry: '2026-03-01',
        cof_updated: true,
      }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const labels = fields.map((f) => f.label)
      expect(labels).toContain('COF Expiry')
      expect(labels).not.toContain('WOF Expiry')
    })

    it('hides COF when cof_updated is false and cof_expiry is before issueDate', () => {
      const data: VehicleDisplayData = {
        ...baseData,
        inspection_type: 'cof',
        cof_expiry: '2024-12-01',
        cof_updated: false,
      }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const labels = fields.map((f) => f.label)
      expect(labels).not.toContain('COF Expiry')
    })

    it('labels field as WOF Expiry when inspection_type is wof', () => {
      const data: VehicleDisplayData = {
        ...baseData,
        inspection_type: 'wof',
        wof_updated: true,
      }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const expiry = fields.find((f) => f.label.includes('Expiry'))
      expect(expiry?.label).toBe('WOF Expiry')
    })

    it('labels field as COF Expiry when inspection_type is cof', () => {
      const data: VehicleDisplayData = {
        ...baseData,
        inspection_type: 'cof',
        cof_expiry: '2026-08-15',
        cof_updated: true,
      }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const expiry = fields.find((f) => f.label.includes('Expiry'))
      expect(expiry?.label).toBe('COF Expiry')
    })
  })

  describe('Backward compatibility (fallback mode)', () => {
    it('returns empty array when vehicleDisplay is null and no fallback', () => {
      const fields = buildVehicleDisplayFields(null, issueDate)
      expect(fields).toEqual([])
    })

    it('returns empty array when vehicleDisplay is undefined and no fallback', () => {
      const fields = buildVehicleDisplayFields(undefined, issueDate)
      expect(fields).toEqual([])
    })

    it('uses fallback fields when vehicleDisplay is null', () => {
      const fields = buildVehicleDisplayFields(null, issueDate, {
        vehicle_rego: 'XYZ789',
        vehicle_make: 'Ford',
        vehicle_model: 'Ranger',
        vehicle_year: 2020,
        vehicle_odometer: 50000,
        vehicle: { wof_expiry: '2026-01-01', inspection_type: 'wof' },
      })
      expect(fields).toEqual([
        { label: 'Registration', value: 'XYZ789' },
        { label: 'Vehicle', value: '2020 Ford Ranger' },
        { label: 'Odometer', value: '50,000 km' },
        { label: 'WOF Expiry', value: '2026-01-01' },
      ])
    })

    it('shows COF in fallback mode when inspection_type is cof', () => {
      const fields = buildVehicleDisplayFields(null, issueDate, {
        vehicle: { cof_expiry: '2026-03-01', inspection_type: 'cof' },
      })
      const labels = fields.map((f) => f.label)
      expect(labels).toContain('COF Expiry')
      expect(labels).not.toContain('WOF Expiry')
    })

    it('fallback mode shows all available data without conditional logic', () => {
      // In fallback mode, WOF is shown regardless of date comparison
      const fields = buildVehicleDisplayFields(null, '2027-01-01', {
        vehicle_rego: 'ABC123',
        vehicle_odometer: 100000,
        vehicle: { wof_expiry: '2025-01-01', inspection_type: 'wof' },
      })
      const labels = fields.map((f) => f.label)
      // WOF shown even though it's in the past (no conditional logic in fallback)
      expect(labels).toContain('WOF Expiry')
    })

    it('omits null fallback fields', () => {
      const fields = buildVehicleDisplayFields(null, issueDate, {
        vehicle_rego: null,
        vehicle_make: null,
        vehicle_model: null,
        vehicle_year: null,
        vehicle_odometer: null,
        vehicle: null,
      })
      expect(fields).toEqual([])
    })
  })

  describe('Vehicle string formatting', () => {
    it('combines year, make, and model', () => {
      const data: VehicleDisplayData = {
        ...baseData,
        make: 'Toyota',
        model: 'Hilux',
        year: 2019,
      }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const vehicle = fields.find((f) => f.label === 'Vehicle')
      expect(vehicle?.value).toBe('2019 Toyota Hilux')
    })

    it('shows only make and model when year is null', () => {
      const data: VehicleDisplayData = { ...baseData, year: null }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const vehicle = fields.find((f) => f.label === 'Vehicle')
      expect(vehicle?.value).toBe('Toyota Hilux')
    })

    it('shows only year and make when model is null', () => {
      const data: VehicleDisplayData = { ...baseData, model: null }
      const fields = buildVehicleDisplayFields(data, issueDate)
      const vehicle = fields.find((f) => f.label === 'Vehicle')
      expect(vehicle?.value).toBe('2019 Toyota')
    })
  })
})
