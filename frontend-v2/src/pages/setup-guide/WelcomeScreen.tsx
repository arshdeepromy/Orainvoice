import { Button } from '@/components/ui'

interface WelcomeScreenProps {
  isRerun: boolean
  onStart: () => void
}

export default function WelcomeScreen({ isRerun, onStart }: WelcomeScreenProps) {
  return (
    <div className="bg-canvas flex items-start justify-center px-4 py-12 sm:py-16">
      <div className="w-full max-w-lg">
        <div className="bg-card rounded-card shadow-card border border-border p-6 sm:p-8 text-center space-y-6">
          {isRerun ? (
            <>
              <h1 className="text-2xl font-bold text-text">Enable More Modules</h1>
              <p className="text-sm text-muted leading-relaxed">
                We'll walk you through the modules you previously skipped. Answer a few quick
                questions to enable the ones that fit your business.
              </p>
            </>
          ) : (
            <>
              <h1 className="text-2xl font-bold text-text">Welcome to OraInvoice</h1>
              <p className="text-sm text-muted leading-relaxed">
                Let's tailor OraInvoice to your business. We'll ask a few quick questions to
                figure out which features you need — it only takes a minute.
              </p>
              <p className="text-xs text-muted leading-relaxed">
                Don't worry if you're not sure about something. Any modules you skip now can be
                enabled later from Settings.
              </p>
            </>
          )}

          <Button variant="primary" size="md" onClick={onStart}>
            {isRerun ? 'Continue' : 'Get Started'}
          </Button>
        </div>
      </div>
    </div>
  )
}
