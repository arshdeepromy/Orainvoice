export interface StepInfo {
  label: string
  completed: boolean
  skipped: boolean
}

interface StepIndicatorProps {
  steps: StepInfo[]
  currentStep: number
}

export function StepIndicator({ steps, currentStep }: StepIndicatorProps) {
  const totalSteps = steps.length

  return (
    <nav aria-label="Setup wizard progress" className="mb-8">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-text">
          Step {currentStep + 1} of {totalSteps}
        </span>
        <span className="text-sm text-muted">{steps[currentStep]?.label}</span>
      </div>
      <div
        className="flex gap-1.5"
        role="progressbar"
        aria-valuenow={currentStep + 1}
        aria-valuemin={1}
        aria-valuemax={totalSteps}
        aria-label={`Step ${currentStep + 1} of ${totalSteps}: ${steps[currentStep]?.label}`}
      >
        {steps.map((step, i) => {
          let colorClass = 'bg-border'
          if (i < currentStep || step.completed) {
            colorClass = 'bg-accent'
          } else if (i === currentStep) {
            colorClass = 'bg-accent/60'
          } else if (step.skipped) {
            colorClass = 'bg-warn'
          }

          return (
            <div
              key={i}
              className={`h-2 flex-1 rounded-full transition-colors ${colorClass}`}
              title={`${step.label}${step.completed ? ' (completed)' : step.skipped ? ' (skipped)' : ''}`}
            />
          )
        })}
      </div>
      {/* Step dots for larger screens */}
      <ol className="hidden sm:flex justify-between mt-3">
        {steps.map((step, i) => (
          <li
            key={i}
            className={`text-xs text-center flex-1 ${
              i === currentStep
                ? 'text-accent font-medium'
                : i < currentStep || step.completed
                  ? 'text-muted'
                  : 'text-muted-2'
            }`}
          >
            {step.label}
          </li>
        ))}
      </ol>
    </nav>
  )
}
