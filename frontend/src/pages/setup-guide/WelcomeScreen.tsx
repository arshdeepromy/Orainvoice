import { Button } from '@/components/ui/Button'

interface WelcomeScreenProps {
  isRerun: boolean
  onStart: () => void
}

export default function WelcomeScreen({ isRerun, onStart }: WelcomeScreenProps) {
  return (
    <div className="bg-gray-50 flex items-start justify-center px-4 py-12 sm:py-16">
      <div className="w-full max-w-lg">
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 sm:p-8 text-center space-y-6">
          {isRerun ? (
            <>
              <h1 className="text-2xl font-bold text-gray-900">Enable More Modules</h1>
              <p className="text-sm text-gray-600 leading-relaxed">
                We'll walk you through the modules you previously skipped. Answer a few quick
                questions to enable the ones that fit your business.
              </p>
            </>
          ) : (
            <>
              <h1 className="text-2xl font-bold text-gray-900">Welcome to OraInvoice</h1>
              <p className="text-sm text-gray-600 leading-relaxed">
                Let's tailor OraInvoice to your business. We'll ask a few quick questions to
                figure out which features you need — it only takes a minute.
              </p>
              <p className="text-xs text-gray-500 leading-relaxed">
                Don't worry if you're not sure about something. Any modules you skip now can be
                enabled later from Settings.
              </p>
            </>
          )}

          <Button variant="primary" size="lg" onClick={onStart}>
            {isRerun ? 'Continue' : 'Get Started'}
          </Button>
        </div>
      </div>
    </div>
  )
}
