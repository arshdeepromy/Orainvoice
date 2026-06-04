/**
 * Barcode scanning utility using Web Barcode Detection API (Chrome/Edge)
 * with fallback to quagga2 library for other browsers.
 *
 * Validates: Requirement 9.10
 */

export interface BarcodeScanResult {
  rawValue: string
  format: string
}

export interface BarcodeScannerOptions {
  formats?: string[]
}

const DEFAULT_FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'qr_code']

/**
 * Check if the native BarcodeDetector API is available.
 */
export function isBarcodeDetectorSupported(): boolean {
  return typeof window !== 'undefined' && 'BarcodeDetector' in window
}

/**
 * Detect barcodes from an image source using the native BarcodeDetector API.
 */
async function detectWithNativeAPI(
  source: ImageBitmapSource,
  formats: string[],
): Promise<BarcodeScanResult[]> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const BarcodeDetector = (window as any).BarcodeDetector
  const detector = new BarcodeDetector({ formats })
  const barcodes = await detector.detect(source)
  return barcodes.map((b: { rawValue: string; format: string }) => ({
    rawValue: b.rawValue,
    format: b.format,
  }))
}

/**
 * Detect barcodes from an image source using quagga2 as a fallback.
 * Dynamically imports quagga2 only when needed.
 */
async function detectWithQuagga(imageDataUrl: string): Promise<BarcodeScanResult[]> {
  try {
    // Dynamic import with variable to avoid Vite static analysis
    const moduleName = 'quagga2'
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const Quagga = await (Function('m', 'return import(m)')(moduleName) as Promise<any>).then((m) => m.default || m)
    return new Promise((resolve) => {
      Quagga.decodeSingle(
        {
          src: imageDataUrl,
          numOfWorkers: 0,
          inputStream: { size: 800 },
          decoder: {
            readers: [
              'ean_reader',
              'ean_8_reader',
              'upc_reader',
              'upc_e_reader',
              'code_128_reader',
              'code_39_reader',
            ],
          },
        },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (result: any) => {
          if (result?.codeResult?.code) {
            resolve([{
              rawValue: result.codeResult.code,
              format: result.codeResult.format || 'unknown',
            }])
          } else {
            resolve([])
          }
        },
      )
    })
  } catch {
    console.warn('quagga2 not available, barcode scanning unavailable')
    return []
  }
}

/**
 * Scan barcodes from a video frame (canvas element or image bitmap).
 * Uses native BarcodeDetector when available, falls back to quagga2.
 */
export async function scanBarcode(
  source: HTMLCanvasElement | HTMLVideoElement | HTMLImageElement,
  options?: BarcodeScannerOptions,
): Promise<BarcodeScanResult[]> {
  const formats = options?.formats || DEFAULT_FORMATS

  if (isBarcodeDetectorSupported()) {
    try {
      return await detectWithNativeAPI(source, formats)
    } catch (err) {
      console.warn('Native BarcodeDetector failed, falling back to quagga2:', err)
    }
  }

  // Fallback: convert source to data URL for quagga2
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  if (!ctx) return []

  if (source instanceof HTMLVideoElement) {
    canvas.width = source.videoWidth
    canvas.height = source.videoHeight
    ctx.drawImage(source, 0, 0)
  } else if (source instanceof HTMLCanvasElement) {
    canvas.width = source.width
    canvas.height = source.height
    ctx.drawImage(source, 0, 0)
  } else {
    canvas.width = source.naturalWidth || source.width
    canvas.height = source.naturalHeight || source.height
    ctx.drawImage(source, 0, 0)
  }

  const dataUrl = canvas.toDataURL('image/png')
  return detectWithQuagga(dataUrl)
}

/**
 * Open the device camera and scan for a barcode.
 * Returns the first detected barcode or null if cancelled/failed.
 */
export async function scanBarcodeFromCamera(): Promise<BarcodeScanResult | null> {
  let stream: MediaStream | null = null

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' },
    })

    const video = document.createElement('video')
    video.srcObject = stream
    video.setAttribute('playsinline', 'true')
    await video.play()

    // Try scanning for up to 10 seconds
    const maxAttempts = 20
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, 500))
      const results = await scanBarcode(video)
      if (results.length > 0) {
        return results[0]
      }
    }

    return null
  } catch (err) {
    console.error('Camera access failed:', err)
    return null
  } finally {
    if (stream) {
      stream.getTracks().forEach((t) => t.stop())
    }
  }
}
