/**
 * Vehicles page barrel (Task 25).
 *
 * Mirrors frontend/src/pages/vehicles — VehicleList (paginated list + bulk
 * refresh + manual-entry + CarJam onboard) and VehicleProfile (detail + expiry
 * indicators + PpsrCard + tabs). Both are routed under /vehicles, gated by the
 * automotive trade family AND the `vehicles` module (matching the original
 * router).
 */
export { default as VehicleList } from './VehicleList'
export { default as VehicleProfile } from './VehicleProfile'
