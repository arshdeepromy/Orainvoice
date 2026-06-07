import { useState } from 'react'
import type { VehicleLookupResult } from './types'
import { getInspectionLabel, getInspectionExpiry } from '@/utils/vehicleHelpers'

/* ── Types ── */

interface KioskVehicleSummaryProps {
  vehicle: VehicleLookupResult
  vehicleCount: number
  onConfirm: (odometer_km: number | null) => void
  onAddAnother: () => void
  onBack: () => void
}

/* ── KioskVehicleSummary ──
 * Design: the "VEHICLE SUMMARY" screen in OraInvoice_Handoff/app/Kiosk.html.
 * Odometer capture + confirm / add-another / back logic is unchanged. */

export function KioskVehicleSummary({
  vehicle,
  vehicleCount,
  onConfirm,
  onAddAnother,
  onBack,
}: KioskVehicleSummaryProps) {
  const [odometerInput, setOdometerInput] = useState('')

  const parseOdometer = (): number | null => {
    const value = odometerInput.trim()
    return value ? Number(value) : null
  }

  const handleConfirm = () => {
    onConfirm(parseOdometer())
  }

  const handleAddAnother = () => {
    onConfirm(parseOdometer())
    onAddAnother()
  }

  const vehicleName = [vehicle.year, vehicle.make, vehicle.model].filter(Boolean).join(' ')
  const inspectionLabel = getInspectionLabel(vehicle)
  const inspectionExpiry = getInspectionExpiry(vehicle)

  return (
    <>
      <button type="button" className="k-back" onClick={onBack}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M15 18l-6-6 6-6" />
        </svg>
        Back
      </button>

      <div className="k-card">
        <div className="k-ico" style={{ background: 'var(--ok-soft)' }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="var(--ok)" strokeWidth={2}>
            <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>

        <h1 style={{ fontSize: '28px' }}>Is this your vehicle?</h1>

        {vehicleCount > 0 && (
          <p className="mono" style={{ textAlign: 'center', color: 'var(--ok)', fontSize: '13px', fontWeight: 600, marginTop: '8px' }}>
            {vehicleCount} already added
          </p>
        )}

        <div style={{ textAlign: 'center', marginTop: '8px' }}>
          <span
            className="mono"
            style={{
              fontSize: '22px',
              fontWeight: 600,
              letterSpacing: '.1em',
              background: 'var(--canvas)',
              padding: '6px 16px',
              borderRadius: '10px',
            }}
          >
            {vehicle.rego}
          </span>
        </div>

        {vehicleName && (
          <div style={{ textAlign: 'center', fontSize: '20px', fontWeight: 600, marginTop: '16px' }}>
            {vehicleName}
          </div>
        )}

        <div className="veh-spec">
          <div className="s">
            <div className="l">{inspectionLabel || 'WoF expiry'}</div>
            <div className="v">{inspectionExpiry ?? '—'}</div>
          </div>
          <div className="s">
            <div className="l">Rego expiry</div>
            <div className="v">{vehicle.rego_expiry ?? '—'}</div>
          </div>
        </div>

        <div style={{ marginBottom: '22px' }}>
          <label className="k-label" htmlFor="kiosk-odometer">
            Current odometer (km) — optional
          </label>
          <input
            id="kiosk-odometer"
            className="k-field mono"
            type="number"
            min={0}
            value={odometerInput}
            onChange={(e) => setOdometerInput(e.target.value)}
            placeholder="e.g. 84210"
            aria-label="Current odometer in kilometres"
          />
        </div>

        <button type="button" className="btn-kiosk primary" onClick={handleConfirm}>
          Yes, that&apos;s me
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </button>

        <button
          type="button"
          className="btn-kiosk ghost"
          style={{ marginTop: '12px' }}
          onClick={handleAddAnother}
        >
          Add another vehicle
        </button>

        <button
          type="button"
          className="btn-kiosk ghost"
          style={{ marginTop: '12px' }}
          onClick={onBack}
        >
          No, try another plate
        </button>

        <div className="step-dots">
          <i />
          <i className="on" />
          <i />
        </div>
      </div>
    </>
  )
}

export default KioskVehicleSummary
