import { useInstallPrompt } from '@/hooks/useInstallPrompt'

export function InstallPromptBanner() {
  const { isInstallable, promptInstall, dismissPrompt } = useInstallPrompt()

  if (!isInstallable) return null

  return (
    <div
      role="banner"
      aria-label="Install app"
      className="fixed bottom-4 left-4 right-4 z-50 mx-auto max-w-md rounded-lg bg-slate-900 p-4 text-white shadow-lg sm:left-auto sm:right-4"
    >
      <div className="flex items-start gap-3">
        <div className="flex-1">
          <p className="font-medium">Install WorkshopPro</p>
          <p className="mt-1 text-sm text-slate-300">
            Add to your home screen for quick access and a better experience.
          </p>
        </div>
        <button
          onClick={dismissPrompt}
          className="text-slate-400 hover:text-white"
          aria-label="Dismiss install prompt"
        >
          ✕
        </button>
      </div>
      <div className="mt-3 flex gap-2">
        <button
          onClick={promptInstall}
          className="flex-1 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          Install App
        </button>
        <button
          onClick={dismissPrompt}
          className="rounded-md px-4 py-2 text-sm text-slate-300 hover:text-white"
        >
          Not now
        </button>
      </div>
    </div>
  )
}
